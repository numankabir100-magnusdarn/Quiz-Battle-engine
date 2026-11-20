(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // DOM elements
  const activeModePill = $("activeModePill");
  const activeModeText = $("activeModeText");
  const cardEsp32 = $("cardEsp32");
  const cardMobile = $("cardMobile");
  const btnSetEsp32 = $("btnSetEsp32");
  const btnSetMobile = $("btnSetMobile");

  const esp32ConnStatus = $("esp32ConnStatus");
  const esp32LockedIp = $("esp32LockedIp");
  const esp32LastCmd = $("esp32LastCmd");
  const btnEsp32Test = $("btnEsp32Test");
  const btnEsp32Reset = $("btnEsp32Reset");

  const mobileAStatus = $("mobileAStatus");
  const mobileBStatus = $("mobileBStatus");
  const qrContainerA = $("qrContainerA");
  const qrContainerB = $("qrContainerB");
  const urlLinkA = $("urlLinkA");
  const urlLinkB = $("urlLinkB");
  const btnTestBuzzA = $("btnTestBuzzA");
  const btnTestBuzzB = $("btnTestBuzzB");
  const btnTestBuzzAll = $("btnTestBuzzAll");

  const strikeDisplay = $("strikeDisplay");
  const strikeStatus = $("strikeStatus");
  const metricSource = $("metricSource");
  const metricTeam = $("metricTeam");
  const metricDelta = $("metricDelta");
  const metricLock = $("metricLock");
  const btnClearBuzz = $("btnClearBuzz");
  const btnClearLog = $("btnClearLog");
  const signalFeed = $("signalFeed");

  let client = null;
  let currentMode = "ESP32";
  let logs = [];
  const MAX_LOGS = 150;

  function formatTime(date = new Date()) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${String(date.getMilliseconds()).padStart(3, "0")}`;
  }

  function appendLog(category, message) {
    const time = formatTime();
    const entry = `[${time}] [${category.toUpperCase()}] ${message}`;
    logs.unshift(entry);
    if (logs.length > MAX_LOGS) logs.pop();
    if (signalFeed) {
      signalFeed.textContent = logs.join("\n");
    }
  }

  // Render mode UI
  function applyMode(mode) {
    currentMode = (mode || "ESP32").toUpperCase();
    const isEsp32 = currentMode === "ESP32";

    if (activeModePill && activeModeText) {
      if (isEsp32) {
        activeModePill.className = "mode-pill esp32-active";
        activeModeText.textContent = "ESP32 HARDWARE PRIMARY";
      } else {
        activeModePill.className = "mode-pill mobile-active";
        activeModeText.textContent = "MOBILE FAILOVER ACTIVE";
      }
    }

    if (cardEsp32 && cardMobile) {
      if (isEsp32) {
        cardEsp32.classList.add("is-active");
        cardMobile.classList.remove("is-active");
        if (btnSetEsp32) {
          btnSetEsp32.textContent = "Active (ESP32 Mode)";
          btnSetEsp32.disabled = true;
        }
        if (btnSetMobile) {
          btnSetMobile.textContent = "Activate Mobile Failover";
          btnSetMobile.disabled = false;
        }
      } else {
        cardEsp32.classList.remove("is-active");
        cardMobile.classList.add("is-active");
        if (btnSetEsp32) {
          btnSetEsp32.textContent = "Switch to ESP32 Primary";
          btnSetEsp32.disabled = false;
        }
        if (btnSetMobile) {
          btnSetMobile.textContent = "Active (Mobile Mode)";
          btnSetMobile.disabled = true;
        }
      }
    }

    if (metricSource) {
      metricSource.textContent = isEsp32 ? "ESP32 PRIMARY" : "MOBILE FAILOVER";
    }
  }

  // Switch mode via REST & WebSocket
  async function setMode(mode) {
    const target = mode.toUpperCase();
    appendLog("ACTION", `Requesting buzzer source switch to ${target}...`);
    try {
      if (client?.ws?.readyState === WebSocket.OPEN) {
        client.sendAction("set_buzzer_source_mode", { mode: target }, `Switched to ${target} mode`);
      }
      const response = await fetch("/api/buzzers/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: target }),
      });
      if (response.ok) {
        const data = await response.json();
        applyMode(data.buzzer_source_mode);
        appendLog("SUCCESS", `Buzzer mode confirmed: ${data.buzzer_source_mode}`);
      } else {
        appendLog("ERROR", `Failed to switch mode via HTTP: status ${response.status}`);
      }
    } catch (err) {
      appendLog("ERROR", `Exception switching mode: ${err.message}`);
    }
  }

  // Update ESP32 telemetry
  function updateEsp32Telemetry(data) {
    const online = Boolean(data.esp32_detected);
    const ip = data.esp32_ip;
    const lastCmd = data.last_command;

    if (esp32ConnStatus) {
      if (online && ip) {
        esp32ConnStatus.className = "conn-pill online";
        esp32ConnStatus.textContent = `ONLINE • ${ip}`;
      } else {
        esp32ConnStatus.className = "conn-pill offline";
        esp32ConnStatus.textContent = "SEARCHING ON UDP 4210...";
      }
    }

    if (esp32LockedIp) {
      esp32LockedIp.textContent = ip || "—";
    }

    if (esp32LastCmd && lastCmd) {
      esp32LastCmd.textContent = lastCmd;
    }
  }

  // Update Mobile telemetry
  function updateMobileTelemetry(data) {
    const mobileA = Boolean(data.mobile_a_connected);
    const mobileB = Boolean(data.mobile_b_connected);

    if (mobileAStatus) {
      mobileAStatus.className = `conn-pill ${mobileA ? "online" : "offline"}`;
      mobileAStatus.textContent = mobileA ? "PHONE A: ONLINE" : "PHONE A: OFFLINE";
    }

    if (mobileBStatus) {
      mobileBStatus.className = `conn-pill ${mobileB ? "online" : "offline"}`;
      mobileBStatus.textContent = mobileB ? "PHONE B: ONLINE" : "PHONE B: OFFLINE";
    }
  }

  // Fetch telemetry via REST
  async function fetchTelemetry() {
    try {
      const res = await fetch("/api/buzzers/mode");
      if (!res.ok) return;
      const data = await res.json();
      if (data.buzzer_source_mode && data.buzzer_source_mode !== currentMode) {
        applyMode(data.buzzer_source_mode);
      }
      updateEsp32Telemetry(data);
      updateMobileTelemetry(data);
    } catch (err) {
      // Offline or network error handled gracefully
    }
  }

  // Load and inject QR codes
  async function loadQRCodes() {
    try {
      const res = await fetch("/api/buzzers/qr");
      if (!res.ok) return;
      const data = await res.json();
      const qrData = data.qr || {};
      const urls = data.urls || {};

      if (qrContainerA && qrData.buzzer_a) {
        qrContainerA.innerHTML = qrData.buzzer_a;
      }
      if (urlLinkA && urls.buzzer_a?.url) {
        urlLinkA.href = urls.buzzer_a.url;
        urlLinkA.textContent = urls.buzzer_a.url;
      }

      if (qrContainerB && qrData.buzzer_b) {
        qrContainerB.innerHTML = qrData.buzzer_b;
      }
      if (urlLinkB && urls.buzzer_b?.url) {
        urlLinkB.href = urls.buzzer_b.url;
        urlLinkB.textContent = urls.buzzer_b.url;
      }
      appendLog("SYSTEM", "Buzzer pairing QR codes and URLs loaded.");
    } catch (err) {
      appendLog("ERROR", `Failed to load QR codes: ${err.message}`);
    }
  }

  // Handle incoming QuizClient state
  function handleState(state) {
    if (!state) return;

    if (state.buzzers?.source_mode) {
      applyMode(state.buzzers.source_mode);
    }

    // Lock status
    const isLocked = Boolean(state.buzzers?.locked);
    if (metricLock) {
      metricLock.textContent = isLocked ? "LOCKED" : "OPEN";
      metricLock.style.color = isLocked ? "var(--orange)" : "var(--emerald)";
    }

    // First buzzer / strike info
    const firstTeam = state.buzzers?.first_buzzer;
    const match = state.current_match;
    const teams = state.teams || {};

    if (firstTeam) {
      const teamObj = teams[firstTeam];
      const teamName = teamObj?.name || (firstTeam === match?.team_a_id ? "TEAM A" : "TEAM B");
      const isTeamA = firstTeam === match?.team_a_id;

      if (metricTeam) {
        metricTeam.textContent = teamName;
      }

      if (strikeStatus) {
        strikeStatus.textContent = `FIRST HIT: ${teamName.toUpperCase()}`;
        strikeStatus.className = `strike-status ${isTeamA ? "hit-a" : "hit-b"}`;
      }
    } else if (!isLocked) {
      if (strikeStatus && !strikeStatus.textContent.includes("FIRST HIT")) {
        strikeStatus.textContent = "BUZZERS ARMED — READY FOR HIT";
        strikeStatus.className = "strike-status";
      }
      if (metricTeam && !metricTeam.textContent) {
        metricTeam.textContent = "—";
      }
    }
  }

  // Handle incoming WebSocket events
  function handleEvent(event) {
    if (!event || !event.name) return;
    const name = event.name;

    switch (name) {
      case "buzzer_source_mode_changed":
        applyMode(event.mode);
        appendLog("PROTOCOL", `Buzzer source mode switched to ${event.mode}`);
        break;

      case "buzz_first":
        if (strikeStatus) {
          const isA = event.team && String(event.team).includes("a");
          strikeStatus.textContent = `FIRST HIT: ${String(event.team || "UNKNOWN").toUpperCase()}`;
          strikeStatus.className = `strike-status ${isA ? "hit-a" : "hit-b"}`;
        }
        if (metricTeam) {
          metricTeam.textContent = String(event.team || "—").toUpperCase();
        }
        appendLog("BUZZ", `First buzz detected from team: ${event.team}`);
        break;

      case "esp32_buzz":
        appendLog("ESP32", `UDP Buzz packet processed: team=${event.side || event.team || "A/B"} accepted=${event.accepted}`);
        break;

      case "esp32_buzz_rejected":
        appendLog("WARN", `ESP32 buzz packet rejected: ${event.side || "A/B"} — Reason: ${event.reason || "question closed / locked"}`);
        break;

      case "esp32_test":
        appendLog("ESP32", `Outbound TEST pulse broadcasted: ${JSON.stringify(event)}`);
        break;

      case "esp32_reset":
        appendLog("ESP32", `Outbound RESET pulse broadcasted: ${JSON.stringify(event)}`);
        break;

      case "buzz_cleared":
        if (strikeStatus) {
          strikeStatus.textContent = "BUZZERS ARMED — READY FOR HIT";
          strikeStatus.className = "strike-status";
        }
        if (metricTeam) {
          metricTeam.textContent = "—";
        }
        if (metricDelta) {
          metricDelta.textContent = "—";
        }
        appendLog("PROTOCOL", "Active buzz cleared. Buzzers re-armed.");
        break;

      case "device_role_assigned":
      case "device_connected":
      case "device_disconnected":
        appendLog("DEVICE", `${name}: ${event.device?.device_name || event.device_id || "device"} (${event.device?.role || ""})`);
        fetchTelemetry();
        break;

      case "fairness_telemetry":
        if (metricDelta && event.delta_ms !== undefined) {
          metricDelta.textContent = `+${event.delta_ms} ms`;
        }
        appendLog("TELEMETRY", `Fairness delta: ${event.delta_ms}ms (arrival: ${event.arrival_timestamp_ms})`);
        break;

      default:
        if (name.includes("buzz") || name.includes("esp32") || name.includes("lock")) {
          appendLog("EVENT", `${name}: ${JSON.stringify(event)}`);
        }
        break;
    }
  }

  // Attach button event listeners
  function initListeners() {
    if (btnSetEsp32) {
      btnSetEsp32.addEventListener("click", () => setMode("ESP32"));
    }
    if (btnSetMobile) {
      btnSetMobile.addEventListener("click", () => setMode("MOBILE"));
    }

    if (btnEsp32Test) {
      btnEsp32Test.addEventListener("click", () => {
        appendLog("ACTION", "Sending ESP32 TEST signal (LED flash)...");
        if (client) client.sendAction("hub_esp32_test", {}, "Trigger ESP32 hardware LED test");
      });
    }

    if (btnEsp32Reset) {
      btnEsp32Reset.addEventListener("click", () => {
        appendLog("ACTION", "Sending ESP32 RESET signal (lock clear)...");
        if (client) client.sendAction("hub_esp32_reset", {}, "Trigger ESP32 hardware lock reset");
      });
    }

    if (btnTestBuzzA) {
      btnTestBuzzA.addEventListener("click", () => {
        appendLog("ACTION", "Sending test pulse to Phone A...");
        if (client) client.sendAction("hub_test_buzz_a", {}, "Test pulse Team A");
      });
    }

    if (btnTestBuzzB) {
      btnTestBuzzB.addEventListener("click", () => {
        appendLog("ACTION", "Sending test pulse to Phone B...");
        if (client) client.sendAction("hub_test_buzz_b", {}, "Test pulse Team B");
      });
    }

    if (btnTestBuzzAll) {
      btnTestBuzzAll.addEventListener("click", () => {
        appendLog("ACTION", "Sending test pulse to all mobile buzzers...");
        if (client) client.sendAction("hub_test_buzz_all", {}, "Test pulse all mobile buzzers");
      });
    }

    if (btnClearBuzz) {
      btnClearBuzz.addEventListener("click", () => {
        appendLog("ACTION", "Clearing active buzz lock...");
        if (client) client.sendAction("hub_clear_buzz", {}, "Clear active buzz");
      });
    }

    if (btnClearLog) {
      btnClearLog.addEventListener("click", () => {
        logs = [];
        if (signalFeed) signalFeed.textContent = "Log cleared.";
      });
    }
  }

  // Initialize QuizClient and bootstrap page
  function init() {
    appendLog("SYSTEM", "Initializing Buzzer & Hardware Manager...");

    initListeners();
    loadQRCodes();
    fetchTelemetry();

    if (typeof QuizClient !== "undefined") {
      client = new QuizClient({
        role: "hub",
        pinOrCode: "3333",
        onState: handleState,
        onEvent: handleEvent,
        onStatusChange: (status, message) => {
          appendLog("WS", `WebSocket status: ${status} (${message || ""})`);
        },
      });
      client.init();
    } else {
      appendLog("WARN", "QuizClient library not found in page scope.");
    }

    // Refresh telemetry every 3s
    setInterval(fetchTelemetry, 3000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
