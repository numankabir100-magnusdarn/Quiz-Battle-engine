(() => {
  const body = document.body;
  const configuredRole = body.dataset.role || "buzzer_a";
  const query = new URLSearchParams(window.location.search);
  const pairingGate = document.getElementById("pairingGate");
  const buzzerApp = document.getElementById("buzzerApp");
  const pairingForm = document.getElementById("pairingForm");
  const pairingInput = document.getElementById("pairingInput");
  const pairingError = document.getElementById("pairingError");
  const roleLabel = document.getElementById("roleLabel");
  const teamName = document.getElementById("teamName");
  const speakerName = document.getElementById("speakerName");
  const score = document.getElementById("score");
  const connection = document.getElementById("connection");
  const latency = document.getElementById("latency");
  const wakeBadge = document.getElementById("wakeBadge");
  const soundToggle = document.getElementById("soundToggle");
  const statusLine = document.getElementById("statusLine");
  const fairnessLine = document.getElementById("fairnessLine");
  const feedback = document.getElementById("feedback");
  const button = document.getElementById("buzzButton");
  const buttonLabel = document.getElementById("buttonLabel");
  const buttonSubtitle = document.getElementById("buttonSubtitle");

  let client = null;
  let currentState = null;
  let currentRole = configuredRole;
  let testMode = false;
  let pending = false;
  let pendingTimer = null;
  let pendingStartedAt = 0;
  let wakeLock = null;
  let soundOn = false;
  let lastWinner = "";
  let lastSteal = "";
  let opponentGap = null;

  const roleFromCode = (code) => code === "BUZZ_A" ? "buzzer_a" : code === "BUZZ_B" ? "buzzer_b" : null;
  const codeForRole = (role) => role === "buzzer_b" ? "BUZZ_B" : "BUZZ_A";
  const ownTeamId = (state) => currentRole === "buzzer_b" ? state?.current_match?.team_b_id : state?.current_match?.team_a_id;

  function vibrate(pattern) {
    if (navigator.vibrate) {
      try { navigator.vibrate(pattern); } catch (error) { /* optional device feature */ }
    }
  }

  function tone(frequency = 600) {
    if (!soundOn) return;
    const context = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.06, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.18);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.2);
  }

  async function keepScreenAwake() {
    if (!("wakeLock" in navigator)) {
      wakeBadge.textContent = "SCREEN AWAKE: BROWSER LIMIT";
      wakeBadge.className = "wake-badge warning";
      return;
    }
    try {
      wakeLock = await navigator.wakeLock.request("screen");
      wakeBadge.textContent = "SCREEN AWAKE";
      wakeBadge.className = "wake-badge active";
      wakeLock.addEventListener("release", () => { wakeBadge.textContent = "SCREEN AWAKE: RELEASED"; });
    } catch (error) {
      wakeBadge.textContent = "SCREEN AWAKE: TAP TO ENABLE";
      wakeBadge.className = "wake-badge warning";
    }
  }

  function setMode(mode, title, subtitle) {
    body.className = `state-${mode}`;
    button.className = `buzz-button ${mode}`;
    button.disabled = mode !== "ready";
    buttonLabel.textContent = title;
    buttonSubtitle.textContent = subtitle;
    statusLine.textContent = title;
  }

  function updateIdentity(state) {
    currentState = state;
    const teamId = ownTeamId(state);
    const team = teamId && state.teams ? state.teams[teamId] : null;
    const match = state.current_match || {};
    const teamScore = match.scores?.[teamId] ?? 0;
    teamName.textContent = team?.name || (currentRole === "buzzer_b" ? "TEAM B" : "TEAM A");
    speakerName.textContent = `DESIGNATED SPEAKER: ${team?.designated_speaker || "--"}`;
    score.textContent = teamScore;
    body.style.setProperty("--team-accent", team?.accent_color || (currentRole === "buzzer_b" ? "#f97316" : "#0ea5e9"));
    roleLabel.textContent = currentRole === "buzzer_b" ? "BUZZER B" : "BUZZER A";
  }

  function updateState(state) {
    updateIdentity(state);
    const ownTeam = ownTeamId(state);
    const round = state.round || {};
    const question = state.question || {};
    const buzzers = state.buzzers || {};

    const buzzerMode = (state.buzzer_source_mode || state.buzzers?.source_mode || "ESP32").toUpperCase();
    if (buzzerMode === "ESP32" && !testMode) {
      setMode("standby", "STANDBY MODE", "ESP32 Hardware Buzzers Active on Stage");
      return;
    }

    if (pending && buzzers.first_team) pending = false;
    if (buzzers.first_team === ownTeam) {
      const key = `${state.question_matrix?.current_question_num || ""}:${ownTeam}`;
      if (lastWinner !== key) {
        lastWinner = key;
        vibrate([250, 80, 250]);
        tone(780);
      }
      setMode("winner", "YOU BUZZED FIRST!", `SPEAK INTO MIC${opponentGap == null ? " • +0ms" : ` • +${opponentGap}ms FIRST`}`);
      return;
    }
    if (buzzers.first_team && buzzers.first_team !== ownTeam) {
      setMode("opponent", "OPPONENT BUZZED FIRST", opponentGap == null ? "STAND BY" : `+${opponentGap}ms BEHIND`);
      return;
    }
    if (buzzers.penalised_team === ownTeam && buzzers.passed_to_team !== ownTeam) {
      setMode("passed", "WRONG (-5) — PASSED", "QUESTION PASSED TO OPPONENT");
      return;
    }
    if (buzzers.passed_to_team === ownTeam) {
      const key = `${state.question_matrix?.current_question_num || ""}:${ownTeam}`;
      if (lastSteal !== key) {
        lastSteal = key;
        vibrate([120, 60, 120]);
        tone(560);
      }
      setMode("ready", "TAP TO BUZZ!", "STEAL OPPORTUNITY — PASSED TO YOU");
      return;
    }
    if (pending) {
      setMode("pending", "BUZZING...", "WAITING FOR SERVER ARRIVAL CONFIRMATION");
      return;
    }
    const activePhase = ["BUZZER_BATTLE", "SUDDEN_DEATH"].includes(round.phase);
    if ((!activePhase || !question.is_open) && !testMode) {
      setMode("locked", "LOCKED", "BUZZER LOCKED — WAIT FOR HOST");
      return;
    }
    if (buzzers.locked && !testMode) {
      setMode("locked", "LOCKED", "BUZZER LOCKED — WAIT FOR HOST");
      return;
    }
    setMode("ready", "TAP TO BUZZ!", testMode ? "BUZZER TEST MODE — NO SCORE" : "SERVER DECIDES ARRIVAL ORDER");
  }

  function updateConnection(status, message) {
    connection.className = `connection ${status}`;
    connection.textContent = status === "online" ? "CONNECTED" : (message || status).toUpperCase();
    if (status !== "online") {
      button.disabled = true;
      statusLine.textContent = (message || status).toUpperCase();
    } else if (currentState) updateState(currentState);
  }

  function flashTestPulse() {
    vibrate([150, 70, 150]);
    tone(920);
    feedback.textContent = "HUB TEST PULSE RECEIVED!";
    body.classList.add("test-pulse");
    setTimeout(() => { feedback.textContent = ""; body.classList.remove("test-pulse"); }, 1600);
  }

  function startBuzzer(role, pairingCode) {
    currentRole = role;
    pairingGate.classList.add("hidden");
    buzzerApp.classList.remove("hidden");
    client = new QuizClient({
      role,
      pinOrCode: pairingCode,
      deviceName: role === "buzzer_b" ? "Buzzer Phone B" : "Buzzer Phone A",
      onState: updateState,
      onRoleChange: (nextRole) => {
        currentRole = nextRole;
        opponentGap = null;
        if (currentState) updateState(currentState);
      },
      onStatusChange: updateConnection,
      onLatency: (value) => {
        latency.textContent = `${Math.round(value)} ms`;
        latency.className = `latency ${value > 80 ? "bad" : value > 60 ? "warn" : "good"}`;
      },
      onEvent: (event) => {
        if (event.name === "hub_test_pulse") flashTestPulse();
        if (event.name === "hub_test_mode_changed") {
          testMode = Boolean(event.enabled);
          if (currentState) updateState(currentState);
        }
        if (event.name === "fairness_telemetry" && event.team !== ownTeamId(currentState)) {
          opponentGap = event.delta_ms;
          if (currentState) updateState(currentState);
        }
        if (["buzz_first", "buzz_cleared", "buzzers_locked", "buzzers_unlocked", "round_reset"].includes(event.name) && currentState) updateState(currentState);
      },
      onAck: (message) => {
        if (message.action === "buzz" && message.success && message.result?.test_mode) {
          setTimeout(() => { pending = false; if (currentState) updateState(currentState); }, Math.max(0, 300 - (Date.now() - pendingStartedAt)));
          feedback.textContent = "TEST BUZZ ACK RECEIVED — NO SCORE";
        }
      },
      onError: (message) => {
        if (message.action === "buzz") {
          pending = false;
          feedback.textContent = message.message || "BUZZ REJECTED BY SERVER";
          if (currentState) updateState(currentState);
        }
      }
    });
    client.init();
    keepScreenAwake();
  }

  button.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    if (button.disabled || pending) return;
    const buzzerMode = (currentState?.buzzer_source_mode || currentState?.buzzers?.source_mode || "ESP32").toUpperCase();
    if (buzzerMode === "ESP32" && !testMode) {
      setMode("standby", "STANDBY MODE", "ESP32 Hardware Buzzers Active on Stage");
      return;
    }
    pending = true;
    pendingStartedAt = Date.now();
    const started = Date.now();
    pendingTimer = setTimeout(() => { pendingTimer = null; }, 300);
    keepScreenAwake();
    vibrate(90);
    tone(440);
    setMode("pending", "BUZZING...", "WAITING FOR SERVER ARRIVAL CONFIRMATION");
    client.sendBuzz();
  });
  button.addEventListener("pointerup", () => {});
  button.addEventListener("pointercancel", () => {});
  soundToggle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    soundOn = !soundOn;
    soundToggle.textContent = `SOUND: ${soundOn ? "ON" : "OFF"}`;
    if (soundOn) tone(520);
  });
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") keepScreenAwake(); });

  function tryPair(code) {
    const normalized = code.trim().toUpperCase();
    const role = roleFromCode(normalized);
    if (!role) {
      pairingError.textContent = "Invalid pairing code. Use BUZZ_A or BUZZ_B.";
      return;
    }
    pairingError.textContent = "";
    startBuzzer(role, normalized);
  }

  pairingForm.addEventListener("submit", (event) => { event.preventDefault(); tryPair(pairingInput.value); });
  const queryCode = (query.get("pairing") || query.get("code") || "").toUpperCase();
  if (roleFromCode(queryCode)) startBuzzer(roleFromCode(queryCode), queryCode);
  else pairingInput.value = codeForRole(configuredRole);
})();
