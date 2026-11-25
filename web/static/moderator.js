/**
 * EEECi FA'26 — EEE Brain Battle (Module 06)
 * Moderator Console — Fully Rewired Controller
 * 100% Offline • Server-Authoritative WebSocket • Zero Stubs
 */

(function () {
  "use strict";

  // ── DOM References ──────────────────────────────────────────────
  var pinGate   = document.getElementById("pinGate");
  var panel     = document.getElementById("panel");
  var pinForm   = document.getElementById("pinForm");
  var pinInput  = document.getElementById("pinInput");
  var pinError  = document.getElementById("pinError");

  var actionToast   = document.getElementById("actionToast");
  var actionMessage = document.getElementById("actionMessage");
  var btnUndo       = document.getElementById("btnUndo");
  var btnCorrect    = document.getElementById("btnCorrect");
  var btnWrong      = document.getElementById("btnWrong");
  var shortcutsToggle = document.getElementById("shortcutsToggle");

  // ── Session State ───────────────────────────────────────────────
  var pin           = sessionStorage.getItem("moderator_pin") || "";
  var client        = null;
  var latestState   = {};
  var toastTimer    = null;
  var autoAdvanceTimer = null;

  // ── Timer State ─────────────────────────────────────────────────
  var timerHandle     = null;
  var timerEndsAt     = 0;
  var timerIsRunning  = false;
  var lastRenderedSec = -1;
  var lastRenderedRunning = false;

  // Ring geometry (r=82, circumference = 2π·82 ≈ 515.2)
  var RING_CIRC = 2 * Math.PI * 82;

  // ── HTTP Helper ─────────────────────────────────────────────────
  function api(path, options) {
    return fetch(path, Object.assign({ credentials: "same-origin",
      headers: { "Content-Type": "application/json" } }, options || {}));
  }

  // ── Toast ───────────────────────────────────────────────────────
  function showToast(text, isError) {
    if (actionToast) {
      actionToast.textContent = text;
      actionToast.className = "action-toast " + (isError ? "error" : "success");
      actionToast.classList.remove("hidden");
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(function () { actionToast.classList.add("hidden"); }, 4000);
    }
    if (actionMessage) {
      actionMessage.textContent = text;
      actionMessage.className = "action-message " + (isError ? "error" : "success");
    }
  }

  // ── Auth ────────────────────────────────────────────────────────
  function setAuthenticated(value) {
    pinGate.classList.toggle("hidden", value);
    panel.classList.toggle("hidden", !value);
    if (value) { connect(); }
    else if (client && client.stop) { client.stop(); }
  }

  function connect() {
    if (!window.QuizClient) { showToast("Client library unavailable.", true); return; }
    if (client && client.stop) client.stop();

    client = new window.QuizClient({
      role: "moderator",
      pin: pin || "1111",
      pinOrCode: pin || "1111",
      onStatusChange: function (status, text) {
        setStatus(text || status, status === "online" ? "connected" : "reconnecting");
      },
      onLatency: function (ms) {
        var badge = document.getElementById("latencyBadge");
        if (badge) {
          badge.textContent = Math.round(ms) + " ms";
          badge.className = "latency " + (ms > 80 ? "bad" : ms > 35 ? "warn" : "good");
        }
      },
      onState:  renderState,
      onEvent:  handleEvent,
      onAck:    handleAck,
      onError:  handleError
    });
    client.init();
  }

  function setStatus(text, cls) {
    var el = document.getElementById("statusBanner");
    if (el) { el.textContent = text.toUpperCase(); el.className = "status " + cls; }
  }

  // ── Send Action ─────────────────────────────────────────────────
  function send(action, payload, reason) {
    if (!client || !client.sendAction) {
      showToast("Console not connected. Waiting for WebSocket...", true);
      return false;
    }
    // Cancel any pending auto-advance if the moderator takes manual control
    if (["next_question","previous_question","select_question","undo_last_action"].indexOf(action) !== -1) {
      if (autoAdvanceTimer) { clearTimeout(autoAdvanceTimer); autoAdvanceTimer = null; }
    }
    var ok = client.sendAction(action, payload || {}, reason || "");
    if (!ok) showToast("Cannot send while disconnected.", true);
    return ok;
  }

  // ── ACK Handler (auto-advance after scoring) ────────────────────
  function handleAck(message) {
    var act = (message.action || "action").replace(/_/g, " ");
    showToast(act.toUpperCase() + " applied.", false);

    if (message.action === "mark_correct" || message.action === "mark_wrong") {
      var result = message.result || {};
      var round  = (latestState && latestState.round) || {};
      var shouldAdvance = false;

      if (message.action === "mark_correct") {
        // Always advance after correct (unless sudden death — match ended)
        if (!result.sudden_death_winner) shouldAdvance = true;
      } else {
        // Wrong in Rapid Fire always advances; in buzzer only advance if closed
        if (round.phase === "RAPID_FIRE" || result.question_closed || result.both_failed || !result.passed_to) {
          shouldAdvance = true;
        }
      }

      if (shouldAdvance) {
        var matrix   = (latestState && latestState.question_matrix) || {};
        var statuses = matrix.statuses || [];
        var hasUnasked = statuses.some(function (s) { return s.status === "unasked"; });
        var currentNum = Number(matrix.current_question_num) || 0;
        var totalNum   = Number(matrix.total_questions) || statuses.length || 15;

        if (hasUnasked || currentNum < totalNum) {
          if (autoAdvanceTimer) clearTimeout(autoAdvanceTimer);
          autoAdvanceTimer = setTimeout(function () {
            autoAdvanceTimer = null;
            send("next_question");
          }, 300);
        }
      }
    }
  }

  function handleError(message) {
    showToast(message.message || "Action rejected by server.", true);
  }

  // ── Event Handler ───────────────────────────────────────────────
  function handleEvent(event) {
    var name = event.name;
    if (name === "timer_tick" || name === "timer_started" || name === "timer_resumed") {
      var sec = event.seconds_remaining != null ? event.seconds_remaining : (event.seconds || 0);
      updateTimer(sec, Boolean(event.running !== undefined ? event.running : true));
    } else if (name === "timer_paused") {
      var sec = event.seconds_remaining != null ? event.seconds_remaining : (event.seconds || 0);
      updateTimer(sec, false);
    } else if (name === "timer_reset") {
      var sec = event.seconds_remaining != null ? event.seconds_remaining : (event.seconds != null ? event.seconds : 120);
      updateTimer(sec, false);
    } else if (name === "timer_expired") {
      updateTimer(0, false);
      showToast("⏰ Time expired!", false);
    } else if (name === "buzz_first") {
      if (window.QuizBuzzerSFX) window.QuizBuzzerSFX.playRealBuzzer("STAGE");
      flashBuzzWinner(event.team);
    } else if (name === "fairness_telemetry") {
      renderFairness(event);
    } else if (name === "buzz_confirmed") {
      showToast("Buzz confirmed: " + (event.team || "team"), false);
    } else if (name === "sudden_death_started" || name === "buzzer_battle_started") {
      showToast("⚡ " + (name === "sudden_death_started" ? "SUDDEN DEATH" : "BUZZER BATTLE") + " — Buzzers armed!", false);
    }
  }

  function flashBuzzWinner(teamId) {
    var match  = (latestState && latestState.current_match) || {};
    var side   = teamId === match.team_a_id ? "A" : (teamId === match.team_b_id ? "B" : null);
    if (!side) return;

    var opp = side === "A" ? "B" : "A";
    var card    = document.getElementById("teamCard" + side);
    var buzzBadge = document.getElementById("team" + side + "BuzzBadge");
    if (card) card.classList.add("buzz-winner");
    if (buzzBadge) buzzBadge.classList.remove("hidden");

    setTimeout(function () {
      if (card) card.classList.remove("buzz-winner");
      if (buzzBadge) buzzBadge.classList.add("hidden");
    }, 3500);
  }

  function renderFairness(data) {
    var stamp = document.getElementById("buzzTimestamp");
    if (stamp) stamp.textContent = "Team " + (data.team || "--") + " arrived first. Delta: +" + (data.delta_ms || 0) + "ms";
  }

  // ── State Renderer ──────────────────────────────────────────────
  function renderState(state) {
    latestState = state || {};

    var match   = state.current_match || {};
    var round   = state.round || {};
    var matrix  = state.question_matrix || {};
    var teams   = state.teams || {};
    var buzzers = state.buzzers || {};
    var telemetry = state.telemetry || {};

    var teamAId = match.team_a_id || "team_1";
    var teamBId = match.team_b_id || "team_2";
    var teamA   = teams[teamAId] || {};
    var teamB   = teams[teamBId] || {};
    var phase   = String(round.phase || "IDLE");

    // ── Topbar telemetry
    var mNum = match.match_number || 1;
    var mStage = String(match.stage || round.stage || "QUALIFIER").toUpperCase();
    setText("matchBadge",   "MATCH " + String(mNum).padStart(2, "0") + " • " + mStage);
    setText("progressPill", mNum + " / " + (match.total_matches || 13));

    var phasePill = document.getElementById("phasePill");
    if (phasePill) {
      phasePill.textContent = phase.replace(/_/g, " ");
      phasePill.className   = "phase-pill " + phaseClass(phase);
    }

    var sourcePill = document.getElementById("buzzerSourcePill");
    if (sourcePill) sourcePill.textContent = state.buzzer_source_mode || "ESP32";

    // ── Workflow banner
    updateWorkflowBanner(phase, round, buzzers, teamA, teamB, teamAId, teamBId);

    // ── Team cards
    var routingMode  = matrix.routing_mode || round.routing_mode || "BUZZER_OPEN";
    var activeTeamId = round.active_team_id;
    var isTurnA = routingMode !== "BUZZER_OPEN" && activeTeamId === teamAId;
    var isTurnB = routingMode !== "BUZZER_OPEN" && activeTeamId === teamBId;

    renderTeamCard("A", teamA, match.scores ? (match.scores[teamAId] || 0) : 0, isTurnA, matrix.team_a_correct, buzzers, teamAId, teamBId);
    renderTeamCard("B", teamB, match.scores ? (match.scores[teamBId] || 0) : 0, isTurnB, matrix.team_b_correct, buzzers, teamAId, teamBId);

    // ── Center column: timer vs buzzer radar
    var isBuzzerPhase = (phase === "BUZZER_BATTLE" || phase === "SUDDEN_DEATH");
    var timerPanel  = document.getElementById("timerPanel");
    var buzzerPanel = document.getElementById("buzzerPanel");
    if (timerPanel)  timerPanel.classList.toggle("hidden", isBuzzerPhase);
    if (buzzerPanel) buzzerPanel.classList.toggle("hidden", !isBuzzerPhase);

    if (isBuzzerPhase) {
      renderBuzzerRadar(buzzers, teamAId, teamBId, teamA.name, teamB.name, phase);
    } else {
      if (typeof round.timer_seconds_remaining === "number") {
        updateTimer(round.timer_seconds_remaining, Boolean(round.timer_running));
      }
    }

    // ── Verdict bar
    updateVerdictBar(phase, buzzers);

    // ── Question matrix
    renderMatrix(matrix, round, teamAId, teamBId);

    // ── Team quick verdicts (shown only in buzzer mode)
    var showTeamVerdicts = isBuzzerPhase;
    var teamARow = document.getElementById("teamAVerdictRow");
    var teamBRow = document.getElementById("teamBVerdictRow");
    if (teamARow) teamARow.classList.toggle("hidden", !showTeamVerdicts);
    if (teamBRow) teamBRow.classList.toggle("hidden", !showTeamVerdicts);

    // ── Telemetry
    setText("paceTelemetry",  Number(telemetry.average_seconds_per_question || 0).toFixed(2) + "s/Q");
    setText("streakTelemetry", String(telemetry.current_streak || 0));

    // ── Bank warning
    if (state.question_bank_warning) showToast(state.question_bank_warning, true);
  }

  function phaseClass(phase) {
    if (phase === "RAPID_FIRE")    return "rf";
    if (phase === "BUZZER_BATTLE") return "bb";
    if (phase === "SUDDEN_DEATH")  return "sd";
    if (phase === "RESULT")        return "result";
    return "";
  }

  // ── Workflow Banner ─────────────────────────────────────────────
  function updateWorkflowBanner(phase, round, buzzers, teamA, teamB, teamAId, teamBId) {
    var labelEl  = document.getElementById("workflowStepLabel");
    var hintEl   = document.getElementById("workflowHint");
    var btn      = document.getElementById("primaryActionBtn");
    var iconEl   = document.getElementById("primaryActionIcon");
    var labelBtn = document.getElementById("primaryActionLabel");
    if (!btn) return;

    var config = getBannerConfig(phase, round, buzzers, teamA, teamB, teamAId, teamBId);

    if (labelEl)  labelEl.textContent  = config.step;
    if (hintEl)   hintEl.textContent   = config.hint;
    if (iconEl)   iconEl.textContent   = config.icon;
    if (labelBtn) labelBtn.textContent = config.label;
    btn.dataset.action = config.action;
    btn.dataset.bannerTeam = config.team || "";
    btn.className = "primary-action-btn " + (config.cls || "");

    // Show/hide based on whether there's a sensible primary action
    btn.style.display = config.action ? "" : "none";
  }

  function getBannerConfig(phase, round, buzzers, teamA, teamB, teamAId, teamBId) {
    var nameA = (teamA.name || "Team A").toUpperCase();
    var nameB = (teamB.name || "Team B").toUpperCase();

    if (phase === "IDLE") {
      return {
        step: "PHASE", hint: "Start Rapid Fire for Team A to begin the match.",
        icon: "▶", label: "START RAPID FIRE • " + nameA,
        action: "_banner_start_rf_a", cls: "rf-mode"
      };
    }

    if (phase === "RAPID_FIRE") {
      var activeId = round.active_team_id;
      var activeName = activeId === teamAId ? nameA : nameB;
      var nextTeam   = activeId === teamAId ? "b" : "a";
      var nextName   = nextTeam === "b" ? nameB : nameA;
      if (round.timer_running) {
        return {
          step: "IN PROGRESS", hint: activeName + " rapid fire running. Press SPACE to pause.",
          icon: "⏸", label: "PAUSE TIMER",
          action: "pause_timer", cls: "rf-mode"
        };
      } else if (round.timer_seconds_remaining > 0) {
        return {
          step: "TIMER PAUSED", hint: activeName + " rapid fire paused. Resume or switch turn.",
          icon: "▶", label: "RESUME TIMER",
          action: "_banner_resume_timer", cls: "rf-mode"
        };
      } else {
        return {
          step: "RAPID FIRE DONE", hint: nameA + " done. Start " + nextName + " now, or go to Buzzer Battle.",
          icon: "▶", label: "RAPID FIRE • " + nextName,
          action: "_banner_start_rf_" + nextTeam, cls: "rf-mode"
        };
      }
    }

    if (phase === "BUZZER_BATTLE") {
      if (!buzzers || buzzers.locked && !buzzers.first_team && !buzzers.passed_to_team) {
        return {
          step: "BUZZER BATTLE", hint: "Buzzers ARMED. Read the question aloud. First buzz wins.",
          icon: "📡", label: "BUZZERS ARMED", action: "", cls: "bb-mode"
        };
      }
      if (buzzers.first_team) {
        var winName = buzzers.first_team === teamAId ? nameA : nameB;
        return {
          step: "BUZZ REGISTERED", hint: winName + " buzzed first. Mark their answer.",
          icon: "⚡", label: winName + " BUZZED", action: "", cls: "bb-mode"
        };
      }
      if (buzzers.passed_to_team) {
        var passName = buzzers.passed_to_team === teamAId ? nameA : nameB;
        return {
          step: "STEAL WINDOW", hint: "Question passed to " + passName + ". Waiting for their buzz.",
          icon: "🔀", label: passName + " STEAL", action: "", cls: "bb-mode"
        };
      }
      return {
        step: "BUZZER BATTLE", hint: "Open next question to continue the round.",
        icon: "⚡", label: "OPEN QUESTION",
        action: "open_question", cls: "bb-mode"
      };
    }

    if (phase === "SUDDEN_DEATH") {
      return {
        step: "SUDDEN DEATH ⚠", hint: "Scores tied. First correct answer wins the match.",
        icon: "💀", label: "SUDDEN DEATH ACTIVE", action: "", cls: "sd-mode"
      };
    }

    if (phase === "RESULT") {
      return {
        step: "MATCH COMPLETE", hint: "Match finished. Advance to next match from Admin panel.",
        icon: "🏆", label: "MATCH RESULT", action: "", cls: "result-mode"
      };
    }

    return { step: "NEXT STEP", hint: "Select a phase to begin.", icon: "⚡", label: "START", action: "" };
  }

  // ── Team Card ───────────────────────────────────────────────────
  function renderTeamCard(side, team, score, isTurn, hitsCount, buzzers, teamAId, teamBId) {
    var card       = document.getElementById("teamCard" + side);
    var nameEl     = document.getElementById("team" + side + "Name");
    var speakerEl  = document.getElementById("team" + side + "Speaker");
    var hitsEl     = document.getElementById("team" + side + "Hits");
    var scoreEl    = document.getElementById("team" + side + "Score");
    var turnBadge  = document.getElementById("team" + side + "TurnBadge");
    var passedBadge = document.getElementById("team" + side + "PassedBadge");

    var color = team.accent_color || (side === "A" ? "#0ea5e9" : "#f97316");
    if (card) {
      card.style.setProperty("--team-color", color);
      card.classList.toggle("active-turn", Boolean(isTurn));
      // Steal window highlight
      var teamId  = side === "A" ? teamAId : (side === "B" ? teamBId : "");
      var isSteal = buzzers && buzzers.passed_to_team && buzzers.passed_to_team === teamId;
      card.classList.toggle("steal-window", Boolean(isSteal));
    }
    if (nameEl)    nameEl.textContent    = team.name    || ("TEAM " + side);
    if (speakerEl) speakerEl.textContent = "SPEAKER: "  + (team.designated_speaker || "--");
    if (hitsEl)    hitsEl.textContent    = "HITS: "     + (hitsCount != null ? hitsCount : 0);
    if (scoreEl)   scoreEl.textContent   = score != null ? score : 0;
    if (turnBadge) turnBadge.classList.toggle("hidden", !isTurn);
    if (passedBadge) {
      var teamId2 = side === "A" ? teamAId : teamBId;
      passedBadge.classList.toggle("hidden", !(buzzers && buzzers.passed_to_team === teamId2));
    }
  }

  // ── Buzzer Radar ────────────────────────────────────────────────
  function renderBuzzerRadar(buzzers, teamAId, teamBId, nameA, nameB, phase) {
    var radar  = document.getElementById("radarWrap");
    var core   = document.getElementById("radarCore");
    var banner = document.getElementById("buzzerBanner");
    var stamp  = document.getElementById("buzzTimestamp");
    var panelLabel = document.getElementById("buzzerPanelLabel");

    if (panelLabel) panelLabel.textContent = phase === "SUDDEN_DEATH" ? "SUDDEN DEATH" : "BUZZER BATTLE";

    var radarState = "locked";
    var bannerState = "locked";
    var bannerText  = "BUZZERS LOCKED";
    var coreIcon    = "🔒";

    if (buzzers && buzzers.passed_to_team) {
      var passName = buzzers.passed_to_team === teamAId ? (nameA || "Team A") : (nameB || "Team B");
      radarState  = "passed";
      bannerState = "passed";
      bannerText  = "PASSED TO " + passName.toUpperCase();
      coreIcon    = "🔀";
    } else if (buzzers && buzzers.first_team) {
      var winName = buzzers.first_team === teamAId ? (nameA || "Team A") : (nameB || "Team B");
      radarState  = "won";
      bannerState = "winner";
      bannerText  = winName.toUpperCase() + " — BUZZED FIRST";
      coreIcon    = "⚡";
    } else if (buzzers && !buzzers.locked) {
      radarState  = "open";
      bannerState = "open";
      bannerText  = "BUZZERS OPEN — LISTENING";
      coreIcon    = "📡";
    }

    if (radar) radar.className = "radar-wrap " + radarState;
    if (core)  { core.className = "radar-core " + radarState; core.querySelector("span").textContent = coreIcon; }
    if (banner) { banner.textContent = bannerText; banner.className = "buzzer-banner " + bannerState; }
    if (stamp && buzzers && buzzers.press_timestamp) {
      stamp.textContent = "Press: " + buzzers.press_timestamp;
    } else if (stamp && buzzers && !buzzers.first_team) {
      stamp.textContent = "No press registered.";
    }
  }

  // ── Verdict Bar ─────────────────────────────────────────────────
  function updateVerdictBar(phase, buzzers) {
    var hint = document.getElementById("scoreHint");
    if (phase === "RAPID_FIRE") {
      if (btnCorrect) btnCorrect.textContent = "✓ CORRECT (+10)";
      if (btnWrong)   btnWrong.textContent   = "✗ WRONG (0)";
      if (hint) hint.textContent = "Rapid Fire: +10 Correct / 0 Wrong. Auto-advances on mark.";
    } else if (phase === "BUZZER_BATTLE") {
      if (btnCorrect) btnCorrect.textContent = "✓ CORRECT (+15)";
      if (btnWrong)   btnWrong.textContent   = "✗ WRONG (−5 & PASS)";
      if (hint) hint.textContent = "Buzzer Battle: +15 Correct / −5 and pass to opponent on Wrong.";
    } else if (phase === "SUDDEN_DEATH") {
      if (btnCorrect) btnCorrect.textContent = "✓ CORRECT (WIN MATCH)";
      if (btnWrong)   btnWrong.textContent   = "✗ WRONG (PASS)";
      if (hint) hint.textContent = "Sudden Death: first correct answer wins the match!";
    } else {
      if (btnCorrect) btnCorrect.textContent = "✓ CORRECT";
      if (btnWrong)   btnWrong.textContent   = "✗ WRONG";
      if (hint) hint.textContent = "Select a phase above to begin the match.";
    }

    if (btnUndo) btnUndo.disabled = !((latestState && latestState.log && latestState.log.length > 0));
  }

  // ── Question Matrix ─────────────────────────────────────────────
  function renderMatrix(matrix, round, teamAId, teamBId) {
    var grid = document.getElementById("questionMatrix");
    if (!grid) return;
    grid.innerHTML = "";

    var total    = Number(matrix.total_questions) || 15;
    var statuses = matrix.statuses || [];
    if (!Array.isArray(statuses) || !statuses.length) {
      statuses = [];
      for (var n = 1; n <= total; n++) statuses.push({ num: n, status: "unasked", winner_side: null });
    }

    var currentNum = Number(matrix.current_question_num);
    var mode      = matrix.routing_mode || round.routing_mode || "BUZZER_OPEN";
    var startSide = matrix.turn_start_side || round.turn_start_side || "A";
    var blockSize = Number(matrix.team_block_size || round.team_block_size || 10);
    var asked = 0;

    statuses.forEach(function (item) {
      var number     = Number(item.num);
      var status     = item.status || "unasked";
      var winnerSide = item.winner_side;

      var blockIdx  = mode === "TEAM_BLOCK" ? Math.floor((number - 1) / Math.max(1, blockSize)) : number - 1;
      var sideIsA   = (blockIdx % 2 === 0) === (String(startSide).toUpperCase() === "A");

      var tile = document.createElement("button");
      tile.type = "button";

      var classes = ["question-tile"];
      if (mode === "TEAM_BLOCK") classes.push(sideIsA ? "block-a" : "block-b");
      if (number === currentNum) classes.push("current");

      if (status === "won") {
        classes.push(winnerSide === "A" ? "won-a" : winnerSide === "B" ? "won-b" : "won");
      } else if (status === "dead" || status === "skipped") {
        classes.push("dead");
      } else if (status === "active") {
        classes.push("active");
      } else {
        classes.push("unasked");
      }

      tile.className = classes.join(" ");
      tile.textContent = "Q" + number + (status === "won" ? " ✓" : (status === "dead" ? " ✕" : ""));
      tile.title = "Q" + number + " (" + status + (winnerSide ? " by " + winnerSide : "") + ")";
      tile.addEventListener("click", function () {
        send("select_question", { question_number: number, number: number });
      });
      grid.appendChild(tile);

      if (status !== "unasked") asked++;
    });

    setText("questionNumber", currentNum ? "NOW: Q" + currentNum : "Q–");
    setText("currentStat",    currentNum ? "Q" + currentNum : "Q–");
    setText("askedStat",      String(asked));
    setText("remainingStat",  String(Math.max(0, statuses.length - asked)));
    setText("matrixAHits",    String(matrix.team_a_correct != null ? matrix.team_a_correct : 0));
    setText("matrixBHits",    String(matrix.team_b_correct != null ? matrix.team_b_correct : 0));

    var modeBadge = document.getElementById("matrixMode");
    if (modeBadge) modeBadge.textContent = mode.replace(/_/g, " ");
  }

  // ── Timer ───────────────────────────────────────────────────────
  function updateTimer(seconds, running) {
    seconds = Math.max(0, Number(seconds) || 0);

    if (!running) {
      if (timerHandle) { clearInterval(timerHandle); timerHandle = null; }
      timerIsRunning = false;
      timerEndsAt    = 0;
      renderTimerDisplay(seconds, false);
      return;
    }

    var now = Date.now();
    // Only resync endpoint if drift > 1s or not yet running
    if (!timerIsRunning || timerEndsAt === 0 || Math.abs(((timerEndsAt - now) / 1000) - seconds) > 1.0) {
      timerEndsAt = now + seconds * 1000;
    }
    timerIsRunning = true;

    var current = Math.max(0, Math.ceil((timerEndsAt - now) / 1000));
    renderTimerDisplay(current, true);

    if (!timerHandle) {
      timerHandle = setInterval(function () {
        if (!timerIsRunning || timerEndsAt === 0) {
          clearInterval(timerHandle); timerHandle = null; return;
        }
        var rem = Math.max(0, Math.ceil((timerEndsAt - Date.now()) / 1000));
        renderTimerDisplay(rem, true);
        if (rem <= 0) {
          clearInterval(timerHandle); timerHandle = null; timerIsRunning = false;
          renderTimerDisplay(0, false);
        }
      }, 100);
    }
  }

  function renderTimerDisplay(remaining, running) {
    remaining = Math.max(0, remaining);
    if (remaining === lastRenderedSec && running === lastRenderedRunning) return;
    lastRenderedSec = remaining;
    lastRenderedRunning = running;

    var round      = (latestState && latestState.round) || {};
    var phase      = round.phase || "RAPID_FIRE";
    var maxSeconds = (phase === "BUZZER_BATTLE" || phase === "SUDDEN_DEATH") ? 30 : 120;
    if (remaining > maxSeconds) maxSeconds = remaining;

    var mins = Math.floor(remaining / 60);
    var secs = remaining % 60;
    var timeStr = String(mins).padStart(2, "0") + ":" + String(secs).padStart(2, "0");

    var timerClass = remaining < 10 ? "critical" : remaining <= 30 ? "warning" : "";

    setText("timerDisplay", timeStr);
    var display = document.getElementById("timerDisplay");
    if (display) display.className = "timer-digits " + timerClass;

    setText("timerRawSec", remaining + " SEC");

    var phasePill = document.getElementById("timerPhase");
    if (phasePill) {
      phasePill.textContent = running ? "RUNNING" : (remaining <= 0 ? "EXPIRED" : (remaining === maxSeconds ? "READY" : "PAUSED"));
      phasePill.className   = "timer-state-pill " + (running ? "running" : (remaining <= 0 ? "expired" : (remaining === maxSeconds ? "ready" : "paused")));
    }

    // Ring fill (SVG arc)
    var ringFill = document.getElementById("ringFill");
    if (ringFill) {
      var pct    = maxSeconds > 0 ? (remaining / maxSeconds) : 0;
      var offset = RING_CIRC * (1 - Math.max(0, Math.min(1, pct)));
      ringFill.style.strokeDashoffset = offset;
      ringFill.className = "ring-fill " + timerClass;
    }

    // Start/Resume button
    var btnSR = document.getElementById("btnStartResume");
    if (btnSR) {
      if (running) {
        btnSR.textContent = "▶ RUNNING...";
        btnSR.className   = "btn btn-outline btn-timer-main";
      } else if (remaining > 0 && remaining < maxSeconds) {
        btnSR.textContent = "▶ RESUME (" + remaining + "s)";
        btnSR.className   = "btn btn-success btn-timer-main";
      } else {
        btnSR.textContent = "▶ START " + maxSeconds + "s";
        btnSR.className   = "btn btn-success btn-timer-main";
      }
    }
  }

  // ── Payload Builder ─────────────────────────────────────────────
  function getPayload(action, button) {
    var match  = latestState.current_match || {};
    var teamAId = match.team_a_id || "team_1";
    var teamBId = match.team_b_id || "team_2";

    if (action === "set_total_questions") {
      var inp = document.getElementById("totalQuestions");
      return { total_questions: Number(inp ? inp.value : 15) };
    }

    if (action === "configure_routing") {
      return {
        mode:       (document.getElementById("routingMode")  || {}).value || "AUTO_ALTERNATE",
        start_side: (document.getElementById("routingStart") || {}).value || "A",
        block_size:  Number((document.getElementById("blockSize") || { value: 10 }).value)
      };
    }

    if (action === "switch_turn")    return { reset_seconds: 120 };

    if (action === "start_rapid_fire") {
      var side = button ? button.dataset.team : "a";
      return { team_id: side === "b" ? teamBId : teamAId, duration_seconds: 120 };
    }

    if (action === "warning_logged" || action === "foul_penalty") {
      var side = button ? button.dataset.team : "a";
      var reason = (document.getElementById("violationReason") || {}).value || "General Violation";
      return { team_id: side === "b" ? teamBId : teamAId, violation: reason };
    }

    if (action === "confirm_first_buzz") {
      var target = button ? button.dataset.team : "";
      if (target === "clear") return { team_id: "clear" };
      if (target === "a")     return { team_id: teamAId };
      if (target === "b")     return { team_id: teamBId };
      return {};
    }

    if (action === "mark_correct" || action === "mark_wrong") {
      var round   = latestState.round || {};
      var buzzers = latestState.buzzers || {};
      var teamSide = button ? button.dataset.teamSide : null;
      var targetTeam = null;

      if (teamSide === "a") targetTeam = teamAId;
      else if (teamSide === "b") targetTeam = teamBId;
      else if (round.phase === "RAPID_FIRE") {
        targetTeam = round.active_team_id || teamAId;
      } else if (buzzers.passed_to_team || buzzers.first_team) {
        targetTeam = buzzers.passed_to_team || buzzers.first_team;
      }
      return targetTeam ? { team_id: targetTeam } : {};
    }

    return {};
  }

  // ── Click Dispatcher ────────────────────────────────────────────
  document.addEventListener("click", function (e) {
    var button = e.target.closest("[data-action]");
    if (!button) return;
    var action = button.dataset.action;
    if (!action) return;

    // Confirm dialogs
    if (action === "end_match" && !window.confirm("End the match and reveal results?")) return;
    if (action === "reset_question_matrix" && !window.confirm("Reset all matrix statuses?")) return;

    // ── Banner virtual actions
    if (action === "_banner_start_rf_a") {
      var match = latestState.current_match || {};
      send("start_rapid_fire", { team_id: match.team_a_id || "team_1", duration_seconds: 120 });
      return;
    }
    if (action === "_banner_start_rf_b") {
      var match = latestState.current_match || {};
      send("start_rapid_fire", { team_id: match.team_b_id || "team_2", duration_seconds: 120 });
      return;
    }
    if (action === "_banner_resume_timer") {
      send("resume_timer");
      return;
    }

    // ── Timer controls
    if (action === "start_timer") {
      var round = (latestState && latestState.round) || {};
      if (round.timer_running) return;
      if (round.timer_seconds_remaining > 0) {
        send("resume_timer");
      } else {
        var maxSec = (round.phase === "BUZZER_BATTLE" || round.phase === "SUDDEN_DEATH") ? 30 : 120;
        send("start_timer", { seconds: maxSec });
      }
      return;
    }

    if (action === "reset_timer") {
      var round = (latestState && latestState.round) || {};
      var maxSec = (round.phase === "BUZZER_BATTLE" || round.phase === "SUDDEN_DEATH") ? 30 : 120;
      send("reset_timer", { seconds: maxSec });
      return;
    }

    if (action === "set_timer_preset") {
      var sec = Number(button.dataset.seconds) || 120;
      send("reset_timer", { seconds: sec });
      return;
    }

    if (action === "adjust_timer_delta") {
      var exactSec = button.dataset.seconds;
      if (exactSec !== undefined && exactSec !== null && exactSec !== "") {
        send("adjust_timer", { seconds: Number(exactSec) });
      } else {
        send("adjust_timer", { delta_seconds: Number(button.dataset.delta) || 0 });
      }
      return;
    }

    send(action, getPayload(action, button));
  });

  // ── Keyboard Shortcuts ──────────────────────────────────────────
  document.addEventListener("keydown", function (e) {
    if (!shortcutsToggle || !shortcutsToggle.checked) return;
    var tag = (document.activeElement && document.activeElement.tagName) || "";
    if (/input|select|textarea/i.test(tag)) return;

    var code = e.code;
    var key  = (e.key || "").toLowerCase();

    if (code === "Space") {
      e.preventDefault();
      var round = (latestState && latestState.round) || {};
      if (round.timer_running) {
        send("pause_timer");
      } else if (round.timer_seconds_remaining > 0) {
        send("resume_timer");
      } else {
        var maxSec = (round.phase === "BUZZER_BATTLE" || round.phase === "SUDDEN_DEATH") ? 30 : 120;
        send("start_timer", { seconds: maxSec });
      }
    } else if (key === "c") {
      e.preventDefault();
      send("mark_correct", getPayload("mark_correct"));
    } else if (key === "w") {
      e.preventDefault();
      send("mark_wrong", getPayload("mark_wrong"));
    } else if (key === "n") {
      e.preventDefault();
      send("next_question");
    } else if (key === "z") {
      e.preventDefault();
      send("undo_last_action");
    } else if (key === "m") {
      e.preventDefault();
      toggleSfxMute();
    }
  });

  // ── SFX Mute Toggle ─────────────────────────────────────────────
  var sfxMuteBtn = document.getElementById("sfxMuteBtn");
  function syncSfxMuteBtn() {
    if (!sfxMuteBtn || !window.QuizBuzzerSFX) return;
    var muted = window.QuizBuzzerSFX.isMuted();
    sfxMuteBtn.innerHTML = muted ? "&#128263; SFX MUTED" : "&#128266; SFX ON";
    sfxMuteBtn.classList.toggle("muted", muted);
  }
  function toggleSfxMute() {
    if (!window.QuizBuzzerSFX) return;
    window.QuizBuzzerSFX.unlock();
    var nextMuted = !window.QuizBuzzerSFX.isMuted();
    window.QuizBuzzerSFX.setMuted(nextMuted);
    syncSfxMuteBtn();
    if (!nextMuted) window.QuizBuzzerSFX.playArmReset();
  }
  if (sfxMuteBtn) {
    syncSfxMuteBtn();
    sfxMuteBtn.addEventListener("click", toggleSfxMute);
  }

  // ── Utility ─────────────────────────────────────────────────────
  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  // ── Auth Form ───────────────────────────────────────────────────
  pinForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var entered = (pinInput.value || "").trim();
    if (!entered) return;
    api("/api/moderator/auth", { method: "POST", body: JSON.stringify({ pin: entered }) })
      .then(function (r) {
        if (!r.ok) throw new Error("Invalid Moderator PIN");
        pin = entered;
        sessionStorage.setItem("moderator_pin", pin);
        pinError.textContent = "";
        setAuthenticated(true);
      })
      .catch(function (err) { pinError.textContent = err.message; });
  });

  var logoutBtn = document.getElementById("logout");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", function () {
      api("/api/moderator/logout", { method: "POST" }).finally(function () {
        sessionStorage.removeItem("moderator_pin");
        pin = "";
        setAuthenticated(false);
      });
    });
  }

  // ── Init: render empty matrix, check session ─────────────────────
  renderMatrix(
    { total_questions: 15, routing_mode: "BUZZER_OPEN", turn_start_side: "A", team_block_size: 10 },
    {}, "team_1", "team_2"
  );

  api("/api/moderator/session")
    .then(function (r) { return r.json(); })
    .then(function (result) {
      if (result && result.authenticated) {
        if (!pin) pin = "1111";
        sessionStorage.setItem("moderator_pin", pin);
        setAuthenticated(true);
      } else if (pin) {
        setAuthenticated(true);
      } else {
        setAuthenticated(false);
      }
    })
    .catch(function () { setAuthenticated(Boolean(pin)); });

})();
