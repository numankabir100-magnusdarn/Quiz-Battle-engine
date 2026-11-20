(() => {
  const $ = (id) => document.getElementById(id);
  const stage = $("stage");
  const arena = $("arena");
  const CHECK_SVG = '<svg class="tile-check" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5 9.2 17 19 7"></path></svg>';

  const ui = {
    matchLabel: $("matchLabel"),
    modeBadge: $("modeBadge"),
    livePip: $("livePip"),
    link: $("linkStatus"),
    linkText: $("linkText"),
    soundInd: $("soundInd"),
    chrono: $("chrono"),
    chronoTime: $("chronoTime"),
    chronoSvg: $("chronoSvg"),
    tactical: $("tactical"),
    stakes: $("stakesPill"),
    hitName: $("hitName"),
    hitSpeaker: $("hitSpeaker"),
    hitMeta: $("hitMeta"),
    stealTitle: $("stealTitle"),
    stealTarget: $("stealTarget"),
    urgency: $("urgency"),
    matrix: $("matrix"),
    pips: $("pips"),
    teleQ: $("teleQ"),
    teleLeft: $("teleLeft"),
    telePace: $("telePace"),
    victory: $("victory"),
    crown: $("crown"),
    victoryKicker: $("victoryKicker"),
    victoryName: $("victoryName"),
    victorySpeaker: $("victorySpeaker")
  };

  const sides = {
    A: {
      wing: $("wingA"),
      name: $("nameA"),
      speaker: $("speakerA"),
      score: $("scoreA"),
      badge: $("badgeA"),
      streak: $("streakA"),
      ready: $("readyA"),
      delta: $("deltaA"),
      kicker: $("kickerA")
    },
    B: {
      wing: $("wingB"),
      name: $("nameB"),
      speaker: $("speakerB"),
      score: $("scoreB"),
      badge: $("badgeB"),
      streak: $("streakB"),
      ready: $("readyB"),
      delta: $("deltaB"),
      kicker: $("kickerB")
    }
  };

  let state = null;
  let manualView = null;
  let seenServerView = null;
  let lastPhase = "";
  let lastModeText = "";
  let timerCeiling = 120;
  let timerRemaining = 120;
  let timerRunning = false;
  let lastTickSpoken = null;
  let matrixSig = "";
  let pipSig = "";
  let scoreReady = false;
  let matchKey = "";
  let prevScores = { A: 0, B: 0 };
  let shockKey = "";
  let passKey = "";
  let devices = [];
  let transport = "offline";
  let soundOn = false;
  let audioCtx = null;
  let arrivals = {};
  let championFired = "";
  let resultKey = "";
  let bracketPaint = 0;

  try {
    soundOn = window.localStorage.getItem("ebb-display-sound") === "1";
  } catch (error) {
    soundOn = false;
  }

  function fit() {
    const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    stage.style.transform = `translate(-50%, -50%) scale(${scale})`;
  }

  function safeColor(value, fallback) {
    return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value || "") ? value : fallback;
  }

  function teamById(id) {
    if (!id || !state || !state.teams) return null;
    return state.teams[id] || null;
  }

  function teamName(id, fallback) {
    const team = teamById(id);
    return (team && team.name) || fallback;
  }

  function speakerOf(id) {
    const team = teamById(id);
    return (team && team.designated_speaker) || "—";
  }

  function phaseOf(snapshot) {
    return String((snapshot && snapshot.round && snapshot.round.phase) || "IDLE").toUpperCase();
  }

  function modeOf(phase) {
    if (phase === "RAPID_FIRE") return "rapid-fire";
    if (phase === "BUZZER_BATTLE") return "buzzer-battle";
    if (phase === "SUDDEN_DEATH") return "sudden-death";
    return "idle";
  }

  function modeLabel(phase) {
    if (phase === "RAPID_FIRE") return "RAPID FIRE";
    if (phase === "BUZZER_BATTLE") return "BUZZER BATTLE";
    if (phase === "SUDDEN_DEATH") return "SUDDEN DEATH";
    if (phase === "RESULT") return "FINAL";
    return "IDLE";
  }

  function padMatch(n) {
    return String(n || 1).padStart(2, "0");
  }

  function fmtTime(seconds) {
    const safe = Math.max(0, Math.floor(Number(seconds) || 0));
    const mins = Math.floor(safe / 60);
    const rest = safe % 60;
    return `${String(mins).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }

  function scoreOf(snapshot, teamId) {
    if (!teamId || !snapshot || !snapshot.current_match || !snapshot.current_match.scores) return 0;
    const value = snapshot.current_match.scores[teamId];
    return Number.isFinite(Number(value)) ? Number(value) : 0;
  }

  function viewFor(snapshot) {
    const serverView = (snapshot && snapshot.display_view) || "auto";
    if (serverView !== "auto") return serverView === "match" ? "stage" : serverView;
    if (manualView) return manualView;
    if (phaseOf(snapshot) === "RESULT") return "result";
    return "stage";
  }

  function setView(view) {
    const name = view === "match" ? "stage" : view;
    stage.dataset.view = name;
    ["stage", "bracket", "result"].forEach((key) => {
      const node = $(`view${key.charAt(0).toUpperCase()}${key.slice(1)}`);
      if (node) node.classList.toggle("is-on", key === name);
    });
    document.querySelectorAll("#viewInd span")?.forEach((node) => {
      node.classList.toggle("on", node.dataset.view === name);
    });
    if (name === "bracket") requestAnimationFrame(drawBracketLinks);
    if (name === "result") maybeCelebrate();
  }

  function buildChrono() {
    const radius = 112;
    const cx = 130;
    const cy = 130;
    const ticks = [];
    for (let i = 0; i < 60; i += 1) {
      const angle = (i / 60) * Math.PI * 2 - Math.PI / 2;
      const inner = i % 5 === 0 ? 96 : 104;
      const outer = 116;
      const x1 = cx + Math.cos(angle) * inner;
      const y1 = cy + Math.sin(angle) * inner;
      const x2 = cx + Math.cos(angle) * outer;
      const y2 = cy + Math.sin(angle) * outer;
      ticks.push(`<line x1="${x1.toFixed(2)}" y1="${y1.toFixed(2)}" x2="${x2.toFixed(2)}" y2="${y2.toFixed(2)}" stroke="rgba(255,255,255,0.28)" stroke-width="${i % 5 === 0 ? 2 : 1}"></line>`);
    }
    const circ = (2 * Math.PI * radius).toFixed(2);
    ui.chronoSvg.innerHTML = `
      <defs>
        <linearGradient id="gradCalm" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" style="stop-color: var(--chrono-color, #f97316)"></stop>
          <stop offset="100%" style="stop-color: var(--orange, #f97316)"></stop>
        </linearGradient>
      </defs>
      ${ticks.join("")}
      <circle cx="130" cy="130" r="${radius}" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="10"></circle>
      <circle id="chronoArc" class="chrono-progress" cx="130" cy="130" r="${radius}" fill="none" stroke="url(#gradCalm)" stroke-width="10" stroke-linecap="round" stroke-dasharray="${circ}" stroke-dashoffset="0" transform="rotate(-90 130 130)"></circle>
    `;
  }

  function paintChrono() {
    const arc = $("chronoArc");
    if (!arc) return;
    const radius = 112;
    const circ = 2 * Math.PI * radius;
    const total = Math.max(1, timerCeiling);
    const ratio = Math.max(0, Math.min(1, timerRemaining / total));
    arc.style.strokeDasharray = String(circ);
    arc.style.strokeDashoffset = String(circ * (1 - ratio));
    ui.chronoTime.textContent = fmtTime(timerRemaining);
    ui.chrono.classList.toggle("is-running", timerRunning && timerRemaining > 0);
    ui.chrono.classList.toggle("is-amber", timerRemaining < 30 && timerRemaining >= 15);
    ui.chrono.classList.toggle("is-crimson", timerRemaining < 15);
    const rapid = arena.dataset.mode === "rapid-fire";
    ui.urgency.classList.toggle("hot", rapid && timerRunning && timerRemaining > 0 && timerRemaining <= 10);
  }

  function noteTimer(seconds, running, total) {
    if (Number.isFinite(Number(total)) && Number(total) > 0) timerCeiling = Number(total);
    else if (Number(seconds) > timerCeiling) timerCeiling = Number(seconds);
    timerRemaining = Math.max(0, Number(seconds) || 0);
    timerRunning = Boolean(running);
    paintChrono();
  }

  function ensureAudio() {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!audioCtx) audioCtx = new Ctx();
    if (audioCtx.state === "suspended") audioCtx.resume();
    return audioCtx;
  }

  function tone(freq, duration, type, gainValue, delay) {
    if (!soundOn) return;
    const ctx = ensureAudio();
    if (!ctx) return;
    const start = ctx.currentTime + (delay || 0);
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type || "sine";
    osc.frequency.setValueAtTime(freq, start);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(gainValue || 0.06, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(start);
    osc.stop(start + duration + 0.02);
  }

  function playCorrect() {
    tone(523.25, 0.12, "sine", 0.07, 0);
    tone(659.25, 0.14, "sine", 0.07, 0.09);
    tone(783.99, 0.22, "triangle", 0.06, 0.18);
  }

  function playWrong() {
    tone(196, 0.22, "sawtooth", 0.04, 0);
    tone(146, 0.28, "triangle", 0.05, 0.08);
  }

  function playBuzz() {
    tone(880, 0.08, "square", 0.04, 0);
    tone(1320, 0.12, "square", 0.035, 0.07);
  }

  function playTick() {
    tone(1480, 0.045, "square", 0.03, 0);
  }

  function playUndo() {
    tone(440, 0.1, "sine", 0.04, 0);
    tone(330, 0.14, "sine", 0.04, 0.08);
  }

  function setSound(next) {
    soundOn = next;
    if (ui.soundInd) {
      ui.soundInd.textContent = soundOn ? "M · SND" : "M · MUTE";
      ui.soundInd.classList.toggle("on", soundOn);
    }
    try {
      window.localStorage.setItem("ebb-display-sound", soundOn ? "1" : "0");
    } catch (error) {
      /* projector storage may be blocked */
    }
    if (soundOn) tone(660, 0.08, "sine", 0.04, 0);
  }

  function tweenScore(el, next) {
    const from = Number(el.dataset.value || el.textContent) || 0;
    const target = Number(next) || 0;
    el.dataset.value = String(target);
    if (from === target) {
      el.textContent = String(target);
      return;
    }
    const proxy = { value: from };
    const write = () => {
      el.textContent = String(Math.round(proxy.value));
    };
    if (window.anime) {
      window.anime({
        targets: proxy,
        value: target,
        duration: 700,
        easing: "easeOutCubic",
        update: write,
        complete: () => {
          el.textContent = String(target);
        }
      });
      return;
    }
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / 700);
      const eased = 1 - ((1 - t) ** 3);
      proxy.value = from + (target - from) * eased;
      write();
      if (t < 1) requestAnimationFrame(step);
      else el.textContent = String(target);
    };
    requestAnimationFrame(step);
  }

  function spawnDelta(anchor, text, kind) {
    const pill = document.createElement("div");
    pill.className = `delta ${kind}`;
    pill.textContent = text;
    anchor.appendChild(pill);
    if (window.anime) {
      window.anime({
        targets: pill,
        translateY: -72,
        opacity: [1, 0],
        duration: 1100,
        easing: "easeOutCubic",
        complete: () => pill.remove()
      });
    } else {
      pill.classList.add("float");
      window.setTimeout(() => pill.remove(), 1100);
    }
  }

  function applyScores(snapshot, teamA, teamB) {
    const key = `${snapshot.event && snapshot.event.match_number}|${teamA}|${teamB}`;
    if (key !== matchKey) {
      matchKey = key;
      scoreReady = false;
      arrivals = {};
    }
    const next = { A: scoreOf(snapshot, teamA), B: scoreOf(snapshot, teamB) };
    const lastLog = (snapshot.log || []).slice(-1)[0];
    const undo = lastLog && lastLog.action === "undo_last_action";
    let undoPlayed = false;
    ["A", "B"].forEach((side) => {
      const el = sides[side].score;
      if (!scoreReady) {
        el.textContent = String(next[side]);
        el.dataset.value = String(next[side]);
        return;
      }
      if (next[side] === prevScores[side]) return;
      const delta = next[side] - prevScores[side];
      const kind = undo ? "undo" : delta > 0 ? "up" : "down";
      const label = undo ? "UNDO" : `${delta > 0 ? "+" : ""}${delta}`;
      spawnDelta(sides[side].delta, label, kind);
      tweenScore(el, next[side]);
      if (undo) {
        if (!undoPlayed) playUndo();
        undoPlayed = true;
      } else if (delta > 0) playCorrect();
      else if (delta < 0) playWrong();
    });
    prevScores = next;
    scoreReady = true;
  }

  function readyState(side, teamId, buzzers) {
    const bar = sides[side].ready;
    const label = bar.querySelector("span");
    let mode = "standby";
    let text = "ARMED & LISTENING";
    if (buzzers.passed_to_team) {
      if (teamId && teamId === buzzers.passed_to_team) {
        mode = "armed";
        text = "STEAL WINDOW";
      } else {
        mode = "locked";
        text = "LOCKED OUT";
      }
    } else if (buzzers.first_team) {
      if (teamId && teamId === buzzers.first_team) {
        mode = "armed";
        text = "LOCKED IN";
      } else {
        mode = "locked";
        text = "LOCKED OUT";
      }
    } else if (!buzzers.locked) {
      mode = "armed";
      text = "ARMED & LISTENING";
    }
    bar.classList.toggle("armed", mode === "armed");
    bar.classList.toggle("standby", mode === "standby");
    label.textContent = text;
    return mode;
  }

  function renderWings(snapshot) {
    const match = snapshot.current_match || {};
    const round = snapshot.round || {};
    const buzzers = snapshot.buzzers || {};
    const phase = phaseOf(snapshot);
    const rapid = phase === "RAPID_FIRE";
    const duel = phase === "BUZZER_BATTLE" || phase === "SUDDEN_DEATH";
    const ids = { A: match.team_a_id, B: match.team_b_id };
    const streak = Number((snapshot.telemetry && snapshot.telemetry.current_streak) || 0);
    const active = round.active_team_id;

    ["A", "B"].forEach((side) => {
      const id = ids[side];
      const color = safeColor(teamById(id) && teamById(id).accent_color, side === "A" ? "#38bdf8" : "#f97316");
      const wing = sides[side].wing;
      wing.style.setProperty("--team-color", color);
      sides[side].kicker.textContent = side === "A" ? "TEAM A" : "TEAM B";
      sides[side].name.textContent = teamName(id, side === "A" ? "Team A" : "Team B");
      sides[side].speaker.textContent = speakerOf(id);
      const live = rapid && active && id === active;
      const waiting = rapid && active && id && id !== active;
      const status = duel ? readyState(side, id, buzzers) : "standby";
      wing.classList.toggle("is-live", Boolean(live));
      wing.classList.toggle("is-dim", Boolean(waiting));
      wing.classList.toggle("is-locked", duel && status === "locked");
      wing.classList.toggle("is-buzzed", duel && buzzers.first_team && id === buzzers.first_team);
      sides[side].badge.classList.toggle("is-on", Boolean(live));
      const showStreak = live && streak >= 1;
      sides[side].streak.hidden = !showStreak;
      if (showStreak) sides[side].streak.textContent = `🔥 ${streak} STREAK`;
    });

    const colorA = sides.A.wing.style.getPropertyValue("--team-color") || "#38bdf8";
    const colorB = sides.B.wing.style.getPropertyValue("--team-color") || "#f97316";
    document.documentElement.style.setProperty("--team-a-color", colorA);
    document.documentElement.style.setProperty("--team-b-color", colorB);
    const clockColor = rapid && active ? (active === ids.A ? colorA : colorB) : "#f97316";
    ui.chrono.style.setProperty("--chrono-color", clockColor);
    applyScores(snapshot, ids.A, ids.B);
    renderTactical(snapshot, ids);
  }

  function msLabel(value) {
    if (value === null || value === undefined || Number(value) === 0) return "+0ms";
    return `+${Math.max(0, Math.round(Number(value)))}ms`;
  }

  function renderTactical(snapshot, ids) {
    const buzzers = snapshot.buzzers || {};
    const phase = phaseOf(snapshot);
    const question = (snapshot.question && snapshot.question.current_question) || {};
    const points = Number(question.points) || (phase === "RAPID_FIRE" ? 10 : 15);
    let tac = "lock";
    if (buzzers.first_team) tac = "hit";
    else if (buzzers.passed_to_team) tac = "steal";
    else if (!buzzers.locked && (phase === "BUZZER_BATTLE" || phase === "SUDDEN_DEATH")) tac = "live";
    ui.tactical.dataset.tac = tac;

    if (phase === "SUDDEN_DEATH") ui.stakes.textContent = "SUDDEN DEATH · INSTANT WIN";
    else ui.stakes.textContent = `+${points} PTS · −5 PASS`;

    if (tac === "hit") {
      const winner = buzzers.first_team;
      const other = winner === ids.A ? ids.B : ids.A;
      const bannerName = teamName(winner, "TEAM").toUpperCase();
      ui.hitName.textContent = `${bannerName} BUZZED FIRST`;
      const banner = $("shockBannerText");
      if (banner) banner.textContent = `${bannerName} BUZZED FIRST!`;
      ui.hitSpeaker.textContent = speakerOf(winner);
      const winnerDelta = arrivals[winner];
      const otherDelta = other ? arrivals[other] : null;
      const otherText = otherDelta === null || otherDelta === undefined ? "NO CONTACT" : msLabel(otherDelta);
      ui.hitMeta.textContent = `LOCKED IN · ${msLabel(winnerDelta)} · OPPONENT ${otherText}`;
      const color = winner === ids.A
        ? sides.A.wing.style.getPropertyValue("--team-color")
        : sides.B.wing.style.getPropertyValue("--team-color");
      const key = `${winner}|${buzzers.press_timestamp || ""}`;
      if (key !== shockKey) {
        shockKey = key;
        triggerShock(color || "#ffffff", `${teamName(winner, "TEAM").toUpperCase()} BUZZED FIRST!`);
      }
    } else {
      shockKey = "";
    }

    if (tac === "steal") {
      const passed = buzzers.passed_to_team;
      const penalised = buzzers.penalised_team;
      ui.stealTitle.textContent = "STEAL OPPORTUNITY";
      ui.stealTarget.textContent = `PASSED TO ${teamName(passed, "OPPOSING TEAM").toUpperCase()}`;
      const key = `${penalised}|${passed}`;
      sides.A.wing.classList.toggle("is-steal", passed && passed === ids.A);
      sides.B.wing.classList.toggle("is-steal", passed && passed === ids.B);
      if (key !== passKey) {
        passKey = key;
        const penalSide = penalised === ids.A ? "A" : penalised === ids.B ? "B" : "";
        if (penalSide) {
          const wing = sides[penalSide].wing;
          wing.classList.remove("is-penalized");
          void wing.offsetWidth;
          wing.classList.add("is-penalized");
        }
        const stealSide = passed === ids.A ? "A" : "B";
        const wing = sides[stealSide].wing;
        wing.classList.remove("is-steal");
        void wing.offsetWidth;
        wing.classList.add("is-steal");
      }
    } else {
      passKey = "";
      sides.A.wing.classList.remove("is-steal", "is-penalized");
      sides.B.wing.classList.remove("is-steal", "is-penalized");
    }
  }

  function triggerShock(color, label) {
    stage.style.setProperty("--shock", color);
    if (label) $("shockBannerText").textContent = label;
    stage.classList.remove("is-shock");
    void stage.offsetWidth;
    stage.classList.add("is-shock");
    const ring = $("shockRing");
    if (window.anime && ring) {
      window.anime.remove(ring);
      window.anime({
        targets: ring,
        scale: [0.2, 6.2],
        opacity: [0.9, 0],
        duration: 900,
        easing: "easeOutExpo"
      });
    }
    window.setTimeout(() => stage.classList.remove("is-shock"), 1100);
  }

  function tileFace(num) {
    const tile = document.createElement("div");
    tile.className = "tile";
    tile.dataset.num = String(num);
    tile.innerHTML = `
      <div class="tile-inner">
        <div class="tile-face tile-front">
          <span class="tile-kicker">CURRENT</span>
          <span class="tile-num">Q${num}</span>
        </div>
        <div class="tile-face tile-back">${CHECK_SVG}</div>
      </div>`;
    return tile;
  }

  function paintTile(tile, item, colors) {
    const status = item.status || "unasked";
    const prev = tile.dataset.status || "";
    tile.dataset.status = status;
    tile.classList.toggle("is-active", status === "active");
    tile.classList.toggle("is-dead", status === "dead");
    tile.classList.toggle("is-won", status === "won");
    const back = tile.querySelector(".tile-back");
    if (status === "won") {
      const color = item.winner_side === "B" ? colors.B : colors.A;
      back.style.background = color;
      back.style.borderColor = "transparent";
    }
    if (status === "won" && prev && prev !== "won") {
      tile.classList.remove("no-anim");
    } else if (status === "won" && !prev) {
      tile.classList.add("no-anim");
    }
  }

  function renderMatrix(snapshot) {
    const matrix = snapshot.question_matrix || {};
    const statuses = matrix.statuses || [];
    const routing = matrix.routing_mode || (snapshot.round && snapshot.round.routing_mode) || "BUZZER_OPEN";
    const block = Number(matrix.team_block_size) || 10;
    const start = matrix.turn_start_side || "A";
    const colors = {
      A: sides.A.wing.style.getPropertyValue("--team-color") || "#38bdf8",
      B: sides.B.wing.style.getPropertyValue("--team-color") || "#f97316"
    };
    const sig = `${statuses.length}|${routing}|${block}|${start}`;
    if (sig !== matrixSig) {
      matrixSig = sig;
      ui.matrix.replaceChildren();
      const split = routing === "TEAM_BLOCK" && statuses.length > block;
      const groups = split
        ? [
          { side: start === "A" ? "A" : "B", items: statuses.slice(0, block) },
          { side: start === "A" ? "B" : "A", items: statuses.slice(block) }
        ]
        : [{ side: "", items: statuses }];
      groups.forEach((group, index) => {
        if (index === 1) {
          const divider = document.createElement("div");
          divider.className = "matrix-divider";
          ui.matrix.appendChild(divider);
        }
        const wrap = document.createElement("div");
        wrap.className = "matrix-block";
        if (group.side) {
          const caption = document.createElement("div");
          caption.className = "matrix-caption";
          caption.textContent = group.side === "A" ? "TEAM A BLOCK" : "TEAM B BLOCK";
          wrap.appendChild(caption);
        }
        const grid = document.createElement("div");
        grid.className = "matrix-grid";
        grid.style.setProperty("--cols", String(Math.max(1, group.items.length)));
        group.items.forEach((item) => grid.appendChild(tileFace(item.num)));
        wrap.appendChild(grid);
        ui.matrix.appendChild(wrap);
      });
    }
    statuses.forEach((item) => {
      const tile = ui.matrix.querySelector(`.tile[data-num="${item.num}"]`);
      if (tile) paintTile(tile, item, colors);
    });
    requestAnimationFrame(() => {
      ui.matrix.querySelectorAll(".tile.no-anim").forEach((tile) => tile.classList.remove("no-anim"));
    });

    const current = matrix.current_question_num;
    ui.teleQ.textContent = current ? `Q${current}` : "—";
    ui.teleLeft.textContent = String(matrix.questions_remaining ?? Math.max(0, statuses.length));
    const pace = Number(snapshot.telemetry && snapshot.telemetry.average_seconds_per_question);
    ui.telePace.textContent = pace > 0 ? pace.toFixed(1) : "—";

    const pipKey = statuses.map((item) => `${item.num}:${item.status}:${item.winner_side || ""}`).join("|");
    if (pipKey !== pipSig || ui.pips.childElementCount !== statuses.length) {
      pipSig = pipKey;
      ui.pips.replaceChildren();
      statuses.forEach((item) => {
        const pip = document.createElement("i");
        pip.className = "pip";
        if (item.status === "active") pip.classList.add("is-active");
        if (item.status === "dead") pip.classList.add("is-dead");
        if (item.status === "won") {
          pip.style.background = item.winner_side === "B" ? colors.B : colors.A;
          pip.style.borderColor = "transparent";
        }
        ui.pips.appendChild(pip);
      });
    }
  }

  function renderHeader(snapshot) {
    const event = snapshot.event || {};
    const match = snapshot.current_match || {};
    const stageName = String(event.stage || match.stage || "Qualifier").toUpperCase();
    const number = event.match_number || match.match_number || 1;
    ui.matchLabel.textContent = `${stageName} · MATCH ${padMatch(number)} OF 13`;
    const phase = phaseOf(snapshot);
    const label = modeLabel(phase);
    ui.modeBadge.dataset.phase = phase === "RESULT" ? "RESULT" : phase;
    if (label !== lastModeText) {
      ui.modeBadge.textContent = label;
      ui.modeBadge.classList.remove("morph");
      void ui.modeBadge.offsetWidth;
      ui.modeBadge.classList.add("morph");
      lastModeText = label;
    }
    const live = phase !== "IDLE" && phase !== "RESULT";
    ui.livePip.classList.toggle("on", live || transport === "online");
  }

  function relBox(el, root) {
    let x = 0;
    let y = 0;
    let node = el;
    while (node && node !== root) {
      x += node.offsetLeft;
      y += node.offsetTop;
      node = node.offsetParent;
    }
    return { x, y, w: el.offsetWidth, h: el.offsetHeight };
  }

  const BRACKET_WINGS = [
    { key: "Left", qual: [1, 2, 3], qf: [7, 8], sf: [11] },
    { key: "Right", qual: [4, 5, 6], qf: [9, 10], sf: [12] },
  ];

  function curve(a, b) {
    const forward = b.x >= a.x;
    const x1 = forward ? a.x + a.w : a.x;
    const x2 = forward ? b.x : b.x + b.w;
    const y1 = a.y + a.h / 2;
    const y2 = b.y + b.h / 2;
    const mid = (x1 + x2) / 2;
    return `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`;
  }

  function renderBracket(snapshot) {
    const board = snapshot.event && snapshot.event.bracket;
    const matches = (board && board.matches) || [];
    const byNum = {};
    matches.forEach((match) => { byNum[match.match_number] = match; });
    const current = (snapshot.event && snapshot.event.match_number) || 0;
    const stages = [
      ["Qual", "QUALIFIERS"],
      ["Qf", "QUARTERFINALS"],
      ["Sf", "SEMIFINAL"]
    ];
    BRACKET_WINGS.forEach((wing) => {
      stages.forEach(([tag, label]) => {
        const root = $(`col${tag}${wing.key}`);
        if (!root) return;
        root.replaceChildren();
        const heading = document.createElement("div");
        heading.className = "col-label";
        heading.textContent = label;
        const stack = document.createElement("div");
        stack.className = "col-matches";
        wing[tag.toLowerCase()].forEach((num) => stack.appendChild(matchCard(byNum[num], num, current)));
        root.append(heading, stack);
      });
    });
    const finalRoot = $("finalMatches");
    if (finalRoot) {
      finalRoot.replaceChildren();
      finalRoot.appendChild(matchCard(byNum[13], 13, current));
    }
    renderWild(snapshot, byNum);
    bracketPaint += 1;
    const token = bracketPaint;
    requestAnimationFrame(() => {
      if (token === bracketPaint) drawBracketLinks();
    });
  }

  function matchCard(match, num, current) {
    const card = document.createElement("article");
    card.className = "match-card";
    card.id = `match-card-${num}`;
    const data = match || { match_number: num, status: "PENDING", scores: {} };
    if (data.status === "IN_PROGRESS" || num === current) card.classList.add("live");
    const head = document.createElement("header");
    const id = document.createElement("span");
    id.textContent = `M${padMatch(num)}`;
    const status = document.createElement("span");
    status.textContent = data.status || "PENDING";
    head.append(id, status);
    card.appendChild(head);
    [["A", data.team_a_id], ["B", data.team_b_id]].forEach(([side, teamId]) => {
      const row = document.createElement("div");
      row.className = "match-team";
      if (data.winner_id && teamId && data.winner_id === teamId) row.classList.add("winner");
      const name = document.createElement("b");
      name.textContent = teamName(teamId, "TBD");
      const score = document.createElement("span");
      const value = data.scores ? data.scores[teamId] : null;
      score.textContent = value === null || value === undefined || !teamId ? "" : String(value);
      row.append(name, score);
      card.appendChild(row);
      if (side === "A" && !card.dataset.accent && teamId) {
        const color = safeColor(teamById(teamId) && teamById(teamId).accent_color, "");
        if (color) card.style.setProperty("--accent", color);
      }
    });
    return card;
  }

  function drawBracketLinks() {
    const board = $("bracketBoard");
    const svg = $("bracketSvg");
    if (!board || !svg) return;
    const box = (num) => {
      const el = $(`match-card-${num}`);
      return el ? relBox(el, board) : null;
    };
    const paths = [];
    BRACKET_WINGS.forEach((wing) => {
      const groups = [wing.qual, wing.qf, wing.sf].map((nums) => nums.map(box).filter(Boolean));
      for (let index = 0; index < groups.length - 1; index += 1) {
        groups[index].forEach((from) => {
          groups[index + 1].forEach((to) => paths.push(curve(from, to)));
        });
      }
      const final = box(13);
      if (groups[2][0] && final) paths.push(curve(groups[2][0], final));
    });
    svg.setAttribute("viewBox", `0 0 ${board.clientWidth} ${board.clientHeight}`);
    const arrow = '<defs><marker id="bracketArrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9 Z" fill="#f97316"></path></marker></defs>';
    svg.innerHTML = arrow + paths.map(
      (d) => `<path d="${d}" fill="none" stroke="#f97316" stroke-opacity="0.72" stroke-width="1.8" marker-end="url(#bracketArrow)"></path>`
    ).join("");
  }

  function renderWild(snapshot, byNum) {
    const root = $("wildCard");
    const bracket = (snapshot.event && snapshot.event.bracket) || {};
    const wild = new Set(bracket.wild_cards || []);
    const tied = new Set(bracket.wild_card_tied_teams || []);
    root.replaceChildren();
    const title = document.createElement("h3");
    title.textContent = "TOP-2 WILD-CARD STANDINGS";
    const copy = document.createElement("p");
    copy.textContent = "Highest-scoring qualifier runners-up advance.";
    const rowBox = document.createElement("div");
    rowBox.className = "wild-rows";
    root.append(title, copy, rowBox);
    const rows = [];
    for (let num = 1; num <= 6; num += 1) {
      const match = byNum[num];
      if (!match || !match.loser_id) continue;
      rows.push({
        id: match.loser_id,
        name: teamName(match.loser_id, match.loser_id),
        score: Number((match.scores && match.scores[match.loser_id]) || 0)
      });
    }
    rows.sort((a, b) => b.score - a.score);
    if (!rows.length) {
      const empty = document.createElement("p");
      empty.textContent = "Standings appear after the qualifier matches.";
      rowBox.appendChild(empty);
      return;
    }
    rows.forEach((row, index) => {
      const line = document.createElement("div");
      line.className = "wild-row";
      if (wild.has(row.id)) line.classList.add("qualifies");
      const rank = document.createElement("span");
      rank.textContent = String(index + 1).padStart(2, "0");
      const name = document.createElement("b");
      name.textContent = row.name;
      const score = document.createElement("em");
      score.textContent = String(row.score);
      line.append(rank, name, score);
      if (tied.has(row.id)) {
        const flag = document.createElement("span");
        flag.className = "flag";
        flag.textContent = "TIE";
        line.appendChild(flag);
      }
      rowBox.appendChild(line);
    });
    if (tied.size) {
      const banner = document.createElement("div");
      banner.className = "tie-banner";
      banner.textContent = "TIE — SUDDEN DEATH REQUIRED";
      root.appendChild(banner);
    }
  }

  function renderResult(snapshot) {
    const match = snapshot.current_match || {};
    const bracket = (snapshot.event && snapshot.event.bracket) || {};
    const matrix = snapshot.question_matrix || {};
    const winnerId = match.winner_id || null;
    const showChampion = Boolean(bracket.champion) && match.match_number === 13 && winnerId === bracket.champion;
    ui.crown.hidden = !showChampion;
    ui.victory.classList.toggle("is-champion", showChampion);
    if (showChampion) {
      ui.victoryKicker.textContent = "GRAND CHAMPION";
      ui.victoryName.textContent = teamName(bracket.champion, "Champion");
      ui.victorySpeaker.textContent = speakerOf(bracket.champion);
    } else if (winnerId) {
      ui.victoryKicker.textContent = `MATCH ${padMatch(match.match_number || snapshot.event.match_number)} WINNER`;
      ui.victoryName.textContent = teamName(winnerId, "Winner");
      ui.victorySpeaker.textContent = speakerOf(winnerId);
    } else {
      ui.victoryKicker.textContent = phaseOf(snapshot) === "SUDDEN_DEATH" ? "SUDDEN DEATH" : "MATCH RESULT";
      ui.victoryName.textContent = "Awaiting Result";
      ui.victorySpeaker.textContent = "The host will close the match";
    }
    const aId = match.team_a_id;
    const bId = match.team_b_id;
    $("resNameA").textContent = teamName(aId, "Team A");
    $("resNameB").textContent = teamName(bId, "Team B");
    $("resScoreA").textContent = String(scoreOf(snapshot, aId));
    $("resScoreB").textContent = String(scoreOf(snapshot, bId));
    $("resSideA").classList.toggle("winner", Boolean(winnerId) && winnerId === aId);
    $("resSideB").classList.toggle("winner", Boolean(winnerId) && winnerId === bId);
    $("hitLabelA").textContent = `${teamName(aId, "TEAM A")} HITS`;
    $("hitLabelB").textContent = `${teamName(bId, "TEAM B")} HITS`;
    $("hitA").textContent = String(matrix.team_a_correct || 0);
    $("hitB").textContent = String(matrix.team_b_correct || 0);
    $("hitDead").textContent = String(matrix.unanswered_count || 0);
    const key = `${showChampion ? bracket.champion : winnerId || "open"}|${match.match_number || ""}`;
    if (key !== resultKey) {
      resultKey = key;
      ui.victory.classList.remove("enter");
      void ui.victory.offsetWidth;
      ui.victory.classList.add("enter");
      if (window.anime) {
        window.anime.remove(ui.victory);
        window.anime({
          targets: ui.victory,
          opacity: [0, 1],
          duration: 700,
          easing: "easeOutCubic"
        });
      }
    }
  }

  function maybeCelebrate() {
    if (!state) return;
    const bracket = state.event && state.event.bracket;
    const champion = bracket && bracket.champion;
    const matchNo = (state.current_match && state.current_match.match_number) || (state.event && state.event.match_number);
    if (!champion || matchNo !== 13 || stage.dataset.view !== "result") return;
    if (championFired === champion) return;
    championFired = champion;
    launchConfetti(safeColor(teamById(champion) && teamById(champion).accent_color, "#f5c16c"));
  }

  function launchConfetti(color) {
    const canvas = $("confettiCanvas");
    canvas.width = 1920;
    canvas.height = 1080;
    const colors = [color, "#f5c16c", "#ffffff", "#67e8f9", "#fb923c"];
    if (window.confetti) {
      const fire = window.confetti.create(canvas, { resize: false, useWorker: false });
      fire({ particleCount: 160, spread: 78, startVelocity: 46, origin: { x: 0.5, y: 0.45 }, colors, scalar: 1.1 });
      window.setTimeout(() => {
        fire({ particleCount: 80, spread: 110, origin: { x: 0.2, y: 0.3 }, colors });
        fire({ particleCount: 80, spread: 110, origin: { x: 0.8, y: 0.3 }, colors });
      }, 280);
      return;
    }
    fallbackConfetti(canvas, colors);
  }

  function fallbackConfetti(canvas, colors) {
    const ctx = canvas.getContext("2d");
    const pieces = Array.from({ length: 140 }, () => ({
      x: 960 + (Math.random() - 0.5) * 400,
      y: 480,
      vx: (Math.random() - 0.5) * 16,
      vy: -Math.random() * 14 - 4,
      r: Math.random() * 6 + 3,
      color: colors[Math.floor(Math.random() * colors.length)],
      life: 90 + Math.random() * 40
    }));
    let frame = 0;
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      pieces.forEach((piece) => {
        piece.x += piece.vx;
        piece.y += piece.vy;
        piece.vy += 0.28;
        piece.life -= 1;
        ctx.globalAlpha = Math.max(0, piece.life / 120);
        ctx.fillStyle = piece.color;
        ctx.fillRect(piece.x, piece.y, piece.r, piece.r * 0.6);
      });
      frame += 1;
      if (frame < 140) requestAnimationFrame(draw);
      else ctx.clearRect(0, 0, canvas.width, canvas.height);
    };
    draw();
  }

  function renderLink() {
    if (!ui.link || !ui.linkText) return;
    const buzzers = devices.filter((device) => device.role === "buzzer_a" || device.role === "buzzer_b");
    const esp = devices.some((device) => /esp/i.test(`${device.device_name || ""} ${device.user_agent || ""} ${device.role || ""}`));
    ui.linkText.textContent = esp ? "ESP32" : "LINK";
    ui.link.classList.remove("live", "partial", "offline");
    if (transport === "offline") ui.link.classList.add("offline");
    else if (buzzers.length >= 2) ui.link.classList.add("live");
    else if (buzzers.length === 1) ui.link.classList.add("partial");
  }

  function upsertDevice(device) {
    if (!device || !device.device_id) return;
    devices = devices.filter((item) => item.device_id !== device.device_id);
    devices.push(device);
    renderLink();
  }

  async function refreshDevices() {
    try {
      const response = await fetch("/api/devices", { cache: "no-store" });
      if (!response.ok) return;
      const payload = await response.json();
      devices = payload.devices || [];
      renderLink();
    } catch (error) {
      /* display keeps the last link snapshot */
    }
  }

  function render(snapshot) {
    if (!snapshot) return;
    try {
      state = snapshot;
      const phase = phaseOf(snapshot);
      const serverView = snapshot.display_view || "auto";
      if (seenServerView !== null && serverView !== seenServerView) manualView = null;
      seenServerView = serverView;
      if (phase === "RESULT" && lastPhase !== "RESULT" && serverView === "auto") manualView = null;
      lastPhase = phase;
      arena.dataset.mode = modeOf(phase);
      const round = snapshot.round || {};
      if (phase === "RAPID_FIRE") {
        noteTimer(round.timer_seconds_remaining, round.timer_running, round.timer_duration_seconds);
      } else {
        timerRunning = false;
        ui.urgency.classList.remove("hot");
        ui.chrono.classList.remove("is-running", "is-amber", "is-crimson");
      }
      renderHeader(snapshot);
      renderWings(snapshot);
      renderMatrix(snapshot);
      renderBracket(snapshot);
      renderResult(snapshot);
      setView(viewFor(snapshot));
      if (!buzzersLive(snapshot)) arrivals = snapshot.buzzers && snapshot.buzzers.first_team ? arrivals : {};
    } catch (error) {
      console.error(error);
    }
  }

  function buzzersLive(snapshot) {
    const buzzers = (snapshot && snapshot.buzzers) || {};
    return Boolean(buzzers.first_team || buzzers.passed_to_team);
  }

  function handleEvent(message) {
    if (!message) return;
    const name = message.name;
    if (name === "timer_tick" || name === "timer_started" || name === "timer_resumed") {
      const seconds = message.seconds_remaining ?? message.seconds ?? 0;
      const total = name === "timer_started" ? seconds : null;
      noteTimer(seconds, message.running !== undefined ? message.running : true, total);
      if (soundOn && arena.dataset.mode === "rapid-fire" && seconds > 0 && seconds <= 10 && seconds !== lastTickSpoken) {
        lastTickSpoken = seconds;
        playTick();
      }
    } else if (name === "timer_paused") {
      noteTimer(message.seconds_remaining ?? message.seconds ?? timerRemaining, false);
    } else if (name === "timer_expired") {
      noteTimer(0, false);
    } else if (name === "timer_reset") {
      const seconds = message.seconds_remaining ?? message.seconds ?? 120;
      timerCeiling = Math.max(120, Number(seconds) || 120);
      noteTimer(seconds, false, timerCeiling);
    } else if (name === "fairness_telemetry") {
      if (message.team) arrivals[message.team] = message.delta_ms;
      if (state) renderTactical(state, {
        A: state.current_match && state.current_match.team_a_id,
        B: state.current_match && state.current_match.team_b_id
      });
    } else if (name === "buzz_first") {
      playBuzz();
    } else if (name === "display_view_changed" && message.view) {
      manualView = message.view === "auto" ? null : (message.view === "match" ? "stage" : message.view);
      setView(manualView || viewFor(state || {}));
    } else if (name === "device_connected") {
      upsertDevice(message.device);
    } else if (name === "device_disconnected" && message.device) {
      devices = devices.filter((item) => item.device_id !== message.device.device_id);
      renderLink();
    } else if (name === "hub_test_pulse") {
      ui.livePip.classList.add("on");
    }
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen();
    }
  }

  window.addEventListener("resize", () => {
    fit();
    if (stage.dataset.view === "bracket") drawBracketLinks();
  });

  window.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();
    if (key === "1") {
      manualView = "stage";
      setView("stage");
    } else if (key === "2") {
      manualView = "bracket";
      setView("bracket");
    } else if (key === "3") {
      manualView = "result";
      setView("result");
    } else if (key === "f") {
      toggleFullscreen();
    } else if (key === "m") {
      setSound(!soundOn);
    }
  });

  buildChrono();
  paintChrono();
  setSound(soundOn);
  fit();
  setView("stage");

  const client = new window.QuizClient({
    role: "display",
    pinOrCode: "",
    onState: render,
    onEvent: handleEvent,
    onAck: () => {},
    onStatusChange: (status) => {
      transport = status === "online" ? "online" : "offline";
      renderLink();
    }
  });
  client.init();
  refreshDevices();
  window.setInterval(refreshDevices, 5000);
})();
