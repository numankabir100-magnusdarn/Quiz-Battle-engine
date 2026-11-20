/**
 * EEECi FA'26 — EEE Brain Battle (Module 06)
 * Moderator Console Client Controller
 * 100% Offline, Server-Authoritative Real-Time WebSocket Synchronization
 */

(function () {
  "use strict";

  // ── DOM References ───────────────────────────────────────────
  var pinGate = document.getElementById("pinGate");
  var panel = document.getElementById("panel");
  var pinForm = document.getElementById("pinForm");
  var pinInput = document.getElementById("pinInput");
  var pinError = document.getElementById("pinError");
  var actionToast = document.getElementById("actionToast");
  var actionMessage = document.getElementById("actionMessage");
  var btnUndo = document.getElementById("btnUndo");
  var btnCorrect = document.getElementById("btnCorrect");
  var btnWrong = document.getElementById("btnWrong");
  var shortcutsToggle = document.getElementById("shortcutsToggle");

  // ── Session & Client State ───────────────────────────────────
  var pin = sessionStorage.getItem("moderator_pin") || "";
  var client = null;
  var latestState = {};
  var timerHandle = null;
  var timerEndsAt = 0;
  var timerIsRunning = false;
  var lastRenderedSeconds = -1;
  var autoAdvanceTimer = null;
  var toastTimer = null;

  // ── HTTP API Helper ──────────────────────────────────────────
  function api(path, options) {
    return fetch(
      path,
      Object.assign(
        {
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" }
        },
        options || {}
      )
    );
  }

  // ── Authentication Management ────────────────────────────────
  function setAuthenticated(value) {
    pinGate.classList.toggle("hidden", value);
    panel.classList.toggle("hidden", !value);
    if (value) {
      connect();
    } else if (client && client.stop) {
      client.stop();
    }
  }

  function showToast(text, isError) {
    if (actionToast) {
      actionToast.textContent = text;
      actionToast.className = "action-toast " + (isError ? "error" : "success");
      actionToast.classList.remove("hidden");
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(function () {
        actionToast.classList.add("hidden");
      }, 4000);
    }
    if (actionMessage) {
      actionMessage.textContent = text;
      actionMessage.className = "action-message " + (isError ? "error" : "success");
    }
  }

  // ── WebSocket Connection via QuizClient ──────────────────────
  function connect() {
    if (!window.QuizClient) {
      showToast("Shared client library unavailable.", true);
      return;
    }

    if (client && client.stop) {
      client.stop();
    }

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
      onState: renderState,
      onEvent: handleEvent,
      onAck: handleAck,
      onError: handleError
    });

    client.init();
  }

  function setStatus(text, className) {
    var status = document.getElementById("statusBanner");
    if (status) {
      status.textContent = text.toUpperCase();
      status.className = "status " + className;
    }
  }

  function send(action, payload, reason) {
    if (!client || !client.sendAction) {
      showToast("Console is not connected yet. Waiting for WebSocket...", true);
      return false;
    }
    if (action === "next_question" || action === "previous_question" || action === "select_question" || action === "undo_last_action") {
      if (autoAdvanceTimer) {
        clearTimeout(autoAdvanceTimer);
        autoAdvanceTimer = null;
      }
    }
    var ok = client.sendAction(action, payload || {}, reason || "");
    if (!ok) {
      showToast("Unable to send action while disconnected.", true);
    }
    return ok;
  }

  // ── Incoming Message Handlers ─────────────────────────────────
  function handleAck(message) {
    var act = message.action ? message.action.replace(/_/g, " ") : "Action";
    showToast(act.toUpperCase() + " applied successfully.", false);

    // Auto-advance to next question upon scoring
    if (message.action === "mark_correct" || message.action === "mark_wrong") {
      var result = message.result || {};
      var round = (latestState && latestState.round) || {};
      var shouldAdvance = false;

      if (message.action === "mark_correct") {
        shouldAdvance = true;
      } else if (message.action === "mark_wrong") {
        // In Rapid Fire, wrong always closes the question and moves forward.
        // In other modes, advance if question closed / both failed / not passed to other team.
        if (round.phase === "RAPID_FIRE" || result.question_closed || result.both_failed || !result.passed_to) {
          shouldAdvance = true;
        }
      }

      if (shouldAdvance) {
        var matrix = (latestState && latestState.question_matrix) || {};
        var statuses = matrix.statuses || [];
        var currentNum = Number(matrix.current_question_num) || 0;
        var totalNum = Number(matrix.total_questions) || statuses.length || 15;
        var hasUnasked = statuses.some(function (item) {
          return item.status === "unasked";
        });

        if (hasUnasked || currentNum < totalNum) {
          if (autoAdvanceTimer) clearTimeout(autoAdvanceTimer);
          autoAdvanceTimer = setTimeout(function () {
            autoAdvanceTimer = null;
            send("next_question");
          }, 250);
        }
      }
    }
  }

  function handleError(message) {
    showToast(message.message || "Action rejected by server.", true);
  }

  function handleEvent(event) {
    if (event.name === "timer_tick" || event.name === "timer_started" || event.name === "timer_resumed") {
      var sec = event.seconds_remaining ?? event.seconds ?? 0;
      var isRun = event.running !== undefined ? Boolean(event.running) : true;
      updateTimer(sec, isRun);
    } else if (event.name === "timer_paused") {
      var sec = event.seconds_remaining ?? event.seconds ?? 0;
      updateTimer(sec, false);
    } else if (event.name === "timer_reset") {
      var sec = event.seconds_remaining ?? event.seconds ?? 120;
      updateTimer(sec, false);
    } else if (event.name === "timer_expired") {
      updateTimer(0, false);
      showToast("Time expired! Countdown completed.", false);
    } else if (event.name === "fairness_telemetry") {
      renderFairness(event);
    } else if (event.name === "buzz_confirmed") {
      showToast("Buzz confirmed for " + (event.team || "team") + ".", false);
    } else if (event.name === "buzz_cleared") {
      showToast("Active buzz cleared.", false);
    }
  }

  function renderFairness(data) {
    var stamp = document.getElementById("buzzTimestamp");
    if (stamp && data) {
      stamp.textContent = "First Arrival: Team " + (data.team || "--") + " • Delta: +" + (data.delta_ms || 0) + "ms";
    }
  }

  // ── State Renderer ───────────────────────────────────────────
  function renderState(state) {
    latestState = state || {};

    var match = state.current_match || {};
    var round = state.round || {};
    var matrix = state.question_matrix || {};
    var routing = state.routing || {};
    var telemetry = state.telemetry || {};
    var teams = state.teams || {};
    var buzzers = state.buzzers || {};

    var teamAId = match.team_a_id || "team_1";
    var teamBId = match.team_b_id || "team_2";
    var teamA = teams[teamAId] || {};
    var teamB = teams[teamBId] || {};

    // 1. Stagebar telemetry
    var stageEl = document.getElementById("stageDisplay");
    if (stageEl) {
      stageEl.textContent = String(round.stage || match.stage || (state.event && state.event.stage) || "QUALIFIER").toUpperCase();
    }

    var matchEl = document.getElementById("matchDisplay");
    if (matchEl) {
      var mNum = match.match_number || (state.event && state.event.match_number) || 1;
      matchEl.textContent = String(mNum).padStart(2, "0") + " / " + (match.total_matches || 13);
    }

    var phase = String(round.phase || "IDLE").replace(/_/g, " ").toUpperCase();
    var phaseEl = document.getElementById("phaseDisplay");
    if (phaseEl) phaseEl.textContent = phase;

    // Active turn detection
    var activeTeamId = round.active_team_id || routing.active_team_id;
    var routingMode = routing.mode || matrix.routing_mode || round.routing_mode || "BUZZER_OPEN";
    var turnEl = document.getElementById("activeTurnTeam");
    if (turnEl) {
      if (routingMode === "BUZZER_OPEN" || !activeTeamId) {
        turnEl.textContent = "BUZZER OPEN";
      } else if (activeTeamId === teamAId) {
        turnEl.textContent = (teamA.name || "TEAM A").toUpperCase();
      } else if (activeTeamId === teamBId) {
        turnEl.textContent = (teamB.name || "TEAM B").toUpperCase();
      } else {
        turnEl.textContent = String(activeTeamId).toUpperCase();
      }
    }

    // Undo availability
    var undoEl = document.getElementById("undoStatus");
    var hasUndo = state.can_undo !== undefined ? state.can_undo : (state.log && state.log.length > 0);
    if (undoEl) {
      undoEl.textContent = hasUndo ? "AVAILABLE" : "READY";
      undoEl.className = "stage-value " + (hasUndo ? "accent" : "ok");
    }
    if (btnUndo) {
      btnUndo.disabled = state.can_undo === false;
    }

    // 2. Team Cards
    var isTurnA = routingMode !== "BUZZER_OPEN" && activeTeamId === teamAId;
    var isTurnB = routingMode !== "BUZZER_OPEN" && activeTeamId === teamBId;
    renderTeamCard("A", teamA, match.scores?.[teamAId] ?? 0, isTurnA, matrix.team_a_correct);
    renderTeamCard("B", teamB, match.scores?.[teamBId] ?? 0, isTurnB, matrix.team_b_correct);

    // 3. Spoken-Only Question Matrix
    renderMatrix(matrix, round, teamAId, teamBId);

    // 4. Scoring button labels based on phase
    updateScoringButtons(round.phase);

    // 5. Buzzer Authority Panel
    renderBuzzerBanner(buzzers, teamAId, teamBId, teamA.name, teamB.name);

    // 6. Match Timer
    if (typeof round.timer_seconds_remaining === "number") {
      updateTimer(round.timer_seconds_remaining, Boolean(round.timer_running));
    }

    // 7. Telemetry strip
    renderTelemetry(telemetry);

    // 8. Warning notice
    if (state.question_bank_warning) {
      showToast(state.question_bank_warning, true);
    }
  }

  function renderTeamCard(side, team, score, isTurn, hitsCount) {
    var card = document.getElementById("teamCard" + side);
    var nameEl = document.getElementById("team" + side + "Name");
    var speakerEl = document.getElementById("team" + side + "Speaker");
    var hitsEl = document.getElementById("team" + side + "Hits");
    var scoreEl = document.getElementById("team" + side + "Score");
    var turnBadge = document.getElementById("team" + side + "TurnBadge");

    var color = team.accent_color || (side === "A" ? "#0ea5e9" : "#f97316");

    if (card) {
      card.style.setProperty("--team-color", color);
      card.classList.toggle("active-turn", Boolean(isTurn));
    }
    if (nameEl) nameEl.textContent = team.name || ("TEAM " + side);
    if (speakerEl) speakerEl.textContent = "DESIGNATED SPEAKER: " + (team.designated_speaker || "--");
    if (hitsEl) hitsEl.textContent = "HITS: " + (hitsCount ?? (team.correct_answers || team.hits || 0));
    if (scoreEl) scoreEl.textContent = score ?? 0;
    if (turnBadge) turnBadge.classList.toggle("hidden", !isTurn);
  }

  function updateScoringButtons(phase) {
    var hint = document.getElementById("scoreHint");
    if (phase === "RAPID_FIRE") {
      if (btnCorrect) btnCorrect.textContent = "CORRECT (+10)";
      if (btnWrong) btnWrong.textContent = "WRONG (0)";
      if (hint) hint.textContent = "Rapid Fire Mode: +10 pts on Correct, 0 on Wrong.";
    } else if (phase === "BUZZER_BATTLE") {
      if (btnCorrect) btnCorrect.textContent = "CORRECT (+15)";
      if (btnWrong) btnWrong.textContent = "WRONG (-5 & PASS)";
      if (hint) hint.textContent = "Buzzer Battle: +15 on Correct, -5 and pass to opponent on Wrong.";
    } else if (phase === "SUDDEN_DEATH") {
      if (btnCorrect) btnCorrect.textContent = "CORRECT (WIN TIE-BREAKER)";
      if (btnWrong) btnWrong.textContent = "WRONG (PASS OVER)";
      if (hint) hint.textContent = "Sudden Death: first correct wins the match.";
    } else {
      if (btnCorrect) btnCorrect.textContent = "CORRECT";
      if (btnWrong) btnWrong.textContent = "WRONG / PASS";
      if (hint) hint.textContent = "Server validates the active scoring target.";
    }
  }

  function renderBuzzerBanner(buzzers, teamAId, teamBId, nameA, nameB) {
    var banner = document.getElementById("buzzerBanner");
    var stamp = document.getElementById("buzzTimestamp");
    if (!banner) return;

    if (buzzers.passed_to_team) {
      var passTarget = buzzers.passed_to_team === teamAId ? (nameA || "TEAM A") : (nameB || "TEAM B");
      banner.textContent = "PASSED TO " + passTarget.toUpperCase();
      banner.className = "buzzer-banner passed";
    } else if (buzzers.first_team) {
      var winTarget = buzzers.first_team === teamAId ? (nameA || "TEAM A") : (nameB || "TEAM B");
      var delta = buzzers.arrival_delta_ms != null ? " (+" + buzzers.arrival_delta_ms + "ms)" : "";
      banner.textContent = winTarget.toUpperCase() + " BUZZED FIRST" + delta;
      banner.className = "buzzer-banner winner";
    } else if (buzzers.locked) {
      banner.textContent = "BUZZERS LOCKED";
      banner.className = "buzzer-banner locked";
    } else {
      banner.textContent = "BUZZERS OPEN — LISTENING";
      banner.className = "buzzer-banner open";
    }

    if (stamp && buzzers.press_timestamp) {
      stamp.textContent = "Registered Press: " + buzzers.press_timestamp;
    } else if (stamp && !buzzers.first_team) {
      stamp.textContent = "No press registered.";
    }
  }

  function renderMatrix(matrix, round, teamAId, teamBId) {
    var grid = document.getElementById("questionMatrix");
    if (!grid) return;
    grid.innerHTML = "";

    var total = Number(matrix.total_questions) || 15;
    var statuses = matrix.statuses || [];

    if (!Array.isArray(statuses) || !statuses.length) {
      statuses = [];
      for (var n = 1; n <= total; n++) {
        statuses.push({ num: n, status: "unasked", winner_side: null });
      }
    }

    var currentNum = Number(matrix.current_question_num);
    var mode = matrix.routing_mode || round.routing_mode || "BUZZER_OPEN";
    var startSide = matrix.turn_start_side || round.turn_start_side || "A";
    var blockSize = Number(matrix.team_block_size || round.team_block_size || 10);

    var asked = 0;
    var hitsA = 0;
    var hitsB = 0;

    statuses.forEach(function (item) {
      var number = Number(item.num);
      var status = item.status || "unasked";
      var winnerSide = item.winner_side;

      // Calculate intended side when in team block mode
      var blockIdx = mode === "TEAM_BLOCK" ? Math.floor((number - 1) / Math.max(1, blockSize)) : number - 1;
      var sideIsA = (blockIdx % 2 === 0) === (String(startSide).toUpperCase() === "A");
      var intendedSide = sideIsA ? "A" : "B";

      var tile = document.createElement("button");
      tile.type = "button";

      var classes = ["question-tile"];
      if (mode === "TEAM_BLOCK") {
        classes.push(sideIsA ? "block-a" : "block-b");
      }

      if (number === currentNum) {
        classes.push("current");
      }

      if (status === "won") {
        if (winnerSide === "A") {
          classes.push("won-a");
          hitsA++;
        } else if (winnerSide === "B") {
          classes.push("won-b");
          hitsB++;
        } else {
          classes.push("won");
        }
      } else if (status === "dead" || status === "skipped") {
        classes.push("dead");
      } else if (status === "active") {
        classes.push("active");
      } else {
        classes.push("unasked");
      }

      tile.className = classes.join(" ");

      var label = "Q" + number;
      if (status === "won") label += " ✓";
      if (status === "dead" || status === "skipped") label += " ✕";
      tile.textContent = label;

      tile.title = "Item " + number + " (" + status + (winnerSide ? " by Team " + winnerSide : "") + ")";

      // Clicking any tile selects/opens that question number
      tile.addEventListener("click", function () {
        send("select_question", { question_number: number, number: number });
      });

      grid.appendChild(tile);

      if (status !== "unasked") asked++;
    });

    var qNumEl = document.getElementById("questionNumber");
    if (qNumEl) qNumEl.textContent = currentNum ? "NOW: Q" + currentNum : "Q-";

    var curStat = document.getElementById("currentStat");
    if (curStat) curStat.textContent = currentNum ? "Q" + currentNum : "Q-";

    var askedStat = document.getElementById("askedStat");
    if (askedStat) askedStat.textContent = asked;

    var remStat = document.getElementById("remainingStat");
    if (remStat) remStat.textContent = Math.max(0, statuses.length - asked);

    var aHitsEl = document.getElementById("matrixAHits");
    if (aHitsEl) aHitsEl.textContent = matrix.team_a_correct ?? hitsA;

    var bHitsEl = document.getElementById("matrixBHits");
    if (bHitsEl) bHitsEl.textContent = matrix.team_b_correct ?? hitsB;

    var modeBadge = document.getElementById("matrixMode");
    if (modeBadge) modeBadge.textContent = mode.replace(/_/g, " ");
  }

  function renderTelemetry(telemetry) {
    var paceEl = document.getElementById("paceTelemetry");
    if (paceEl) {
      paceEl.textContent = Number(telemetry.average_seconds_per_question || 0).toFixed(2) + "s/Q";
    }
    var streakEl = document.getElementById("streakTelemetry");
    if (streakEl) {
      streakEl.textContent = telemetry.current_streak || 0;
    }
  }

  // ── High-Precision Countdown Timer (Zero Jitter, Synchronized) ───
  function renderTimerDisplay(remaining, running) {
    remaining = Math.max(0, remaining);
    if (remaining === lastRenderedSeconds && running === timerIsRunning) {
      return;
    }
    lastRenderedSeconds = remaining;
    timerIsRunning = running;

    var round = (latestState && latestState.round) || {};
    var phase = round.phase || "RAPID_FIRE";
    var maxSeconds = phase === "BUZZER_BATTLE" || phase === "SUDDEN_DEATH" ? 30 : 120;
    if (remaining > maxSeconds) maxSeconds = remaining;

    var mins = Math.floor(remaining / 60);
    var secs = remaining % 60;
    var display = document.getElementById("timerDisplay");
    if (display) {
      display.textContent = String(mins).padStart(2, "0") + ":" + String(secs).padStart(2, "0");
      display.className = "timer " + (remaining < 10 ? "critical" : remaining <= 30 ? "warning" : "");
    }

    var phasePill = document.getElementById("timerPhase");
    if (phasePill) {
      phasePill.textContent = running ? "RUNNING" : (remaining <= 0 ? "EXPIRED" : (remaining === maxSeconds ? "READY" : "PAUSED"));
      phasePill.className = "timer-phase-pill " + (running ? "running" : (remaining <= 0 ? "expired" : (remaining === maxSeconds ? "ready" : "paused")));
    }

    var rawSecEl = document.getElementById("timerRawSec");
    if (rawSecEl) {
      rawSecEl.textContent = remaining + " SEC REMAINING";
    }

    var modeLabel = document.getElementById("timerModeLabel");
    if (modeLabel) {
      modeLabel.textContent = (phase || "MATCH").replace(/_/g, " ").toUpperCase() + " (" + maxSeconds + "s)";
    }

    var progressBar = document.getElementById("timerProgressBar");
    if (progressBar) {
      var pct = Math.max(0, Math.min(100, (remaining / maxSeconds) * 100));
      progressBar.style.width = pct + "%";
      progressBar.className = "timer-bar-fill " + (remaining < 10 ? "critical" : remaining <= 30 ? "warning" : "");
    }

    var btnStartResume = document.getElementById("btnStartResume");
    if (btnStartResume) {
      if (running) {
        btnStartResume.textContent = "▶ RUNNING (SPACE TO PAUSE)";
        btnStartResume.className = "btn btn-outline btn-timer-main";
      } else if (remaining > 0 && remaining < maxSeconds) {
        btnStartResume.textContent = "▶ RESUME (" + remaining + "s)";
        btnStartResume.className = "btn btn-success btn-timer-main";
      } else {
        btnStartResume.textContent = "▶ START " + maxSeconds + "s TIMER";
        btnStartResume.className = "btn btn-success btn-timer-main";
      }
    }
  }

  function updateTimer(seconds, running) {
    seconds = Math.max(0, Number(seconds) || 0);

    if (!running) {
      if (timerHandle) {
        clearInterval(timerHandle);
        timerHandle = null;
      }
      timerIsRunning = false;
      timerEndsAt = 0;
      renderTimerDisplay(seconds, false);
      return;
    }

    var now = Date.now();
    var projected = timerEndsAt > 0 ? (timerEndsAt - now) / 1000 : 0;
    // Resync only if drift is greater than 1.0s or timerEndsAt was 0 or wasn't running
    if (!timerIsRunning || timerEndsAt === 0 || Math.abs(projected - seconds) > 1.0) {
      timerEndsAt = now + seconds * 1000;
    }
    timerIsRunning = true;

    var currentRemaining = Math.max(0, Math.ceil((timerEndsAt - now) / 1000));
    renderTimerDisplay(currentRemaining, true);

    if (!timerHandle) {
      timerHandle = setInterval(function () {
        if (!timerIsRunning || timerEndsAt === 0) {
          clearInterval(timerHandle);
          timerHandle = null;
          return;
        }
        var rem = Math.max(0, Math.ceil((timerEndsAt - Date.now()) / 1000));
        renderTimerDisplay(rem, true);
        if (rem <= 0) {
          clearInterval(timerHandle);
          timerHandle = null;
          timerIsRunning = false;
        }
      }, 100);
    }
  }

  // ── Action Payload Builder ───────────────────────────────────
  function getPayload(action, button) {
    var match = latestState.current_match || {};
    var teamAId = match.team_a_id || "team_1";
    var teamBId = match.team_b_id || "team_2";

    if (action === "set_total_questions") {
      var totalInput = document.getElementById("totalQuestions");
      return { total_questions: Number(totalInput ? totalInput.value : 15) };
    }

    if (action === "configure_routing") {
      var modeEl = document.getElementById("routingMode");
      var startEl = document.getElementById("routingStart");
      var blockEl = document.getElementById("blockSize");
      return {
        mode: modeEl ? modeEl.value : "AUTO_ALTERNATE",
        start_side: startEl ? startEl.value : "A",
        block_size: Number(blockEl ? blockEl.value : 10)
      };
    }

    if (action === "switch_turn") {
      return { reset_seconds: 120 };
    }

    if (action === "start_rapid_fire") {
      var teamSide = button ? button.dataset.team : "a";
      return {
        team_id: teamSide === "b" ? teamBId : teamAId,
        duration_seconds: 120
      };
    }

    if (action === "warning_logged" || action === "foul_penalty") {
      var side = button ? button.dataset.team : "a";
      var reasonSelect = document.getElementById("violationReason");
      return {
        team_id: side === "b" ? teamBId : teamAId,
        violation: reasonSelect ? reasonSelect.value : "General Violation"
      };
    }

    if (action === "confirm_first_buzz") {
      var target = button ? button.dataset.team : "";
      if (target === "clear") return { team_id: "clear" };
      if (target === "a") return { team_id: teamAId };
      if (target === "b") return { team_id: teamBId };
      return {};
    }

    if (action === "start_timer") {
      return { seconds: 120 };
    }

    if (action === "reset_timer") {
      return { seconds: 120 };
    }

    if (action === "mark_correct" || action === "mark_wrong") {
      // Find designated target team if in Rapid Fire or Buzzer Battle
      var round = latestState.round || {};
      var buzzers = latestState.buzzers || {};
      var targetTeam = null;

      if (round.phase === "RAPID_FIRE") {
        targetTeam = round.active_team_id || teamAId;
      } else if (buzzers.first_team || buzzers.passed_to_team) {
        targetTeam = buzzers.passed_to_team || buzzers.first_team;
      }

      return targetTeam ? { team_id: targetTeam } : {};
    }

    return {};
  }

  // ── Click Action Dispatcher ──────────────────────────────────
  document.querySelectorAll("[data-action]").forEach(function (button) {
    button.addEventListener("click", function () {
      var action = button.dataset.action;
      if (!action) return;

      if (action === "end_match" && !window.confirm("Are you sure you want to END the match and reveal results?")) {
        return;
      }

      if (action === "reset_question_matrix" && !window.confirm("Reset all question matrix statuses to unasked?")) {
        return;
      }

      if (action === "start_timer") {
        var round = (latestState && latestState.round) || {};
        if (round.timer_running) {
          return;
        }
        if (round.timer_seconds_remaining > 0) {
          send("resume_timer");
          return;
        }
        var maxSec = round.phase === "BUZZER_BATTLE" || round.phase === "SUDDEN_DEATH" ? 30 : 120;
        send("start_timer", { seconds: maxSec });
        return;
      }

      if (action === "reset_timer") {
        var round = (latestState && latestState.round) || {};
        var maxSec = round.phase === "BUZZER_BATTLE" || round.phase === "SUDDEN_DEATH" ? 30 : 120;
        send("reset_timer", { seconds: maxSec });
        return;
      }

      if (action === "set_timer_preset") {
        var sec = Number(button ? button.dataset.seconds : 120) || 120;
        send("reset_timer", { seconds: sec });
        return;
      }

      if (action === "adjust_timer_delta") {
        var delta = button ? button.dataset.delta : null;
        var exactSec = button ? button.dataset.seconds : null;
        if (exactSec !== undefined && exactSec !== null) {
          send("adjust_timer", { seconds: Number(exactSec) });
        } else {
          send("adjust_timer", { delta_seconds: Number(delta) || 0 });
        }
        return;
      }

      send(action, getPayload(action, button));
    });
  });

  // ── Auth Form Handlers ───────────────────────────────────────
  pinForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var enteredPin = (pinInput.value || "").trim();
    if (!enteredPin) return;

    api("/api/moderator/auth", {
      method: "POST",
      body: JSON.stringify({ pin: enteredPin })
    })
      .then(function (response) {
        if (!response.ok) throw new Error("Invalid Moderator PIN");
        pin = enteredPin;
        sessionStorage.setItem("moderator_pin", pin);
        pinError.textContent = "";
        setAuthenticated(true);
      })
      .catch(function (error) {
        pinError.textContent = error.message;
      });
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

  // ── Keyboard Shortcuts (Space, C, W, N, Z) ───────────────────
  document.addEventListener("keydown", function (event) {
    if (!shortcutsToggle || !shortcutsToggle.checked) return;

    // Strict input-focus guard: don't trigger shortcuts when typing in inputs
    var activeTag = (document.activeElement && document.activeElement.tagName) || "";
    if (/input|select|textarea/i.test(activeTag)) return;

    var code = event.code;
    var key = (event.key || "").toLowerCase();

    if (code === "Space") {
      event.preventDefault();
      var round = (latestState && latestState.round) || {};
      if (round.timer_running) {
        send("pause_timer");
      } else if (round.timer_seconds_remaining > 0) {
        send("resume_timer");
      } else {
        send("start_timer", { seconds: 120 });
      }
    } else if (key === "c") {
      event.preventDefault();
      send("mark_correct", getPayload("mark_correct"));
    } else if (key === "w") {
      event.preventDefault();
      send("mark_wrong", getPayload("mark_wrong"));
    } else if (key === "n") {
      event.preventDefault();
      send("next_question");
    } else if (key === "z") {
      event.preventDefault();
      send("undo_last_action");
    }
  });

  // ── Initialization & Auto-Session Check ──────────────────────
  renderMatrix(
    { total_questions: 15, routing_mode: "BUZZER_OPEN", turn_start_side: "A", team_block_size: 10 },
    {},
    "team_1",
    "team_2"
  );

  api("/api/moderator/session")
    .then(function (response) {
      return response.json();
    })
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
    .catch(function () {
      setAuthenticated(Boolean(pin));
    });
})();
