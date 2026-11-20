(() => {
  const $ = (id) => document.getElementById(id);
  const roleLabels = {unassigned:"Unassigned", display:"Projector", moderator:"Moderator", admin:"Admin", buzzer_a:"Buzzer A", buzzer_b:"Buzzer B", hub:"Control Hub"};
  const readinessItems = [
    ["hotspot", "Windows Hotspot ON (192.168.137.1)"],
    ["firewall", "Firewall TCP 8000 Open"],
    ["mobile", "Phones Mobile Data OFF"],
    ["battery", "Phones Battery Saver OFF"],
    ["nearby", "Chrome Nearby Devices Permission ON"],
    ["projector", "Projector HDMI Extended & Fullscreen (F)"]
  ];
  let client;
  let hubPin = "";
  let selectedIp = "";
  let devices = [];
  let stateSnapshots = [];
  let eventLog = [];
  let activeFilter = "all";
  let soundAlerts = false;
  let stageLockSync = false;

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[char]));
  const appendAudit = (message) => {
    eventLog.unshift({time: new Date().toLocaleTimeString(), message, category: eventCategory(message)});
    renderAudit();
  };
  const eventCategory = (message) => {
    if (/disconnect|connect|role|ping|device/i.test(message)) return "connections";
    if (/buzz|pulse|fairness|buzzer/i.test(message)) return "buzzers";
    if (/score|admin|ack/i.test(message)) return "scores";
    return "all";
  };
  const renderAudit = () => {
    const rows = eventLog.filter((entry) => activeFilter === "all" || entry.category === activeFilter);
    $("auditStream").textContent = rows.map((entry) => `${entry.time}  ${entry.message}`).join("\n").slice(0, 12000) || "No matching events.";
  };
  const chime = (frequency) => {
    if (!soundAlerts) return;
    const context = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.06, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.18);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.2);
  };
  const confirmAction = (message) => window.confirm(message);

  function setStatus(status, message) {
    const element = $("hubStatus");
    element.textContent = (message || status).toUpperCase();
    element.className = `status-pill ${status === "online" ? "" : "offline"}`;
  }

  function renderState(state) {
    const match = state?.current_match || {};
    const teams = state?.teams || {};
    const scores = match.scores || {};
    const stage = state?.event?.stage || match.stage || "Stage";
    const number = state?.event?.match_number || match.match_number || "?";
    $("activeMatch").textContent = `${stage} • Match ${number}/13 • ${teams[match.team_a_id]?.name || "Team A"} ${scores[match.team_a_id] ?? 0} vs ${teams[match.team_b_id]?.name || "Team B"} ${scores[match.team_b_id] ?? 0}`;
    $("roundPhase").textContent = state?.round?.phase || "--";
    $("buzzerLock").textContent = state?.buzzers?.locked ? "LOCKED" : "OPEN";
    if (state && typeof state.stage_locked === "boolean") {
      syncStageLock(state.stage_locked);
    }
    const snapshot = typeof structuredClone === "function" ? structuredClone(state) : JSON.parse(JSON.stringify(state));
    stateSnapshots.unshift({at: Date.now(), state: snapshot});
    stateSnapshots = stateSnapshots.slice(0, 3);
    updateReadiness();
  }

  function syncStageLock(locked) {
    const toggle = $("stageLockToggle");
    const label = $("stageLockState");
    if (!toggle) return;
    stageLockSync = true;
    toggle.checked = Boolean(locked);
    stageLockSync = false;
    if (label) {
      label.textContent = locked ? "LOCKED" : "OPEN";
      label.style.color = locked ? "var(--orange, #f97316)" : "";
    }
  }

  async function refreshEsp32Status() {
    try {
      const response = await fetch("/api/hub/esp32");
      if (!response.ok) return;
      const data = await response.json();
      renderEsp32Status(data);
    } catch (e) {}
  }

  function renderEsp32Status(data) {
    const el = $("esp32Status");
    if (!el) return;
    if (data && data.online && data.locked_ip) {
      el.className = "esp-status online device-online";
      el.textContent = `ONLINE • ${data.locked_ip}`;
    } else if (data && data.listening) {
      el.className = "esp-status offline device-stale";
      el.textContent = "OFFLINE • WAITING FOR HELLO";
    } else {
      el.className = "esp-status offline";
      el.textContent = "OFFLINE • 192.168.137.x";
    }
  }

  function renderReadiness() {
    $("readiness").innerHTML = readinessItems.map(([id, label]) =>
      `<label><input type="checkbox" data-ready="${id}"><span>${label}</span></label>`).join("");
    const saved = JSON.parse(localStorage.getItem("hub-readiness") || "{}");
    document.querySelectorAll("[data-ready]").forEach((input) => {
      input.checked = Boolean(saved[input.dataset.ready]);
      input.addEventListener("change", () => {
        const values = {};
        document.querySelectorAll("[data-ready]").forEach((item) => { values[item.dataset.ready] = item.checked; });
        localStorage.setItem("hub-readiness", JSON.stringify(values));
      });
    });
  }

  function latencyClass(value) {
    if (value < 30) return "latency-good";
    if (value <= 80) return "latency-warn";
    return "latency-bad";
  }

  function renderDevices(nextDevices) {
    devices = nextDevices || [];
    $("deviceCount").textContent = devices.length;
    $("devices").innerHTML = devices.map((device) => {
      const roleOptions = Object.keys(roleLabels).filter((role) => role !== "hub").map((role) =>
        `<option value="${role}" ${role === device.role ? "selected" : ""}>${roleLabels[role]}</option>`).join("");
      const lastSeen = Date.parse(device.last_seen_at || device.connected_at || "");
        const online = Number.isFinite(lastSeen) ? Date.now() - lastSeen < 10000 : true;
      const latency = Number(device.latency_ms || 0);
      return `<tr>
        <td><div class="device-name">${escapeHtml(device.device_id)}</div><div class="device-agent">${escapeHtml(device.device_name)} • ${escapeHtml(device.user_agent)}</div></td>
        <td>${escapeHtml(device.ip)}</td><td><span class="badge badge-accent">${escapeHtml(roleLabels[device.role] || device.role)}</span></td>
        <td class="${online ? "device-online" : "device-stale"}">${online ? "ONLINE" : "RECONNECTING / STALE"}<small class="device-agent">${escapeHtml(device.last_seen_at || "")}</small></td>
        <td class="${latencyClass(latency)}">${Math.round(latency)} ms</td>
        <td><select data-role-for="${escapeHtml(device.device_id)}">${roleOptions}</select>
        <button class="btn btn-outline" data-assign="${escapeHtml(device.device_id)}">Assign</button>
        <button class="btn btn-outline" data-ping="${escapeHtml(device.device_id)}">Ping</button>
        <button class="btn btn-danger" data-kick="${escapeHtml(device.device_id)}">Kick</button></td>
      </tr>`;
    }).join("") || `<tr><td colspan="6" class="muted">No authenticated devices connected.</td></tr>`;
    document.querySelectorAll("[data-assign]").forEach((button) => button.onclick = () => {
      const id = button.dataset.assign;
      const select = document.querySelector(`[data-role-for="${CSS.escape(id)}"]`);
      client.sendAction("hub_assign_role", {device_id: id, role: select.value}, "Control Hub role assignment");
    });
    document.querySelectorAll("[data-ping]").forEach((button) => button.onclick = () =>
      client.sendAction("hub_ping_device", {device_id: button.dataset.ping}, "Control Hub device ping"));
    document.querySelectorAll("[data-kick]").forEach((button) => button.onclick = () => {
      if (confirmAction("Disconnect this device?")) client.sendAction("hub_kick_device", {device_id: button.dataset.kick}, "Control Hub disconnect");
    });
  }

  function updateReadiness() {
    const roles = new Set(devices.map((device) => device.role));
    const warnings = [];
    if (!roles.has("buzzer_a")) warnings.push("MISSING: Buzzer A Phone");
    if (!roles.has("buzzer_b")) warnings.push("MISSING: Buzzer B Phone");
    if (!roles.has("display")) warnings.push("MISSING: Projector Display");
    if (!roles.has("moderator")) warnings.push("MISSING: Moderator Laptop");
    if (!roles.has("admin")) warnings.push("MISSING: Admin Laptop");
    devices.filter((device) => ["buzzer_a", "buzzer_b"].includes(device.role) && Number(device.latency_ms) > 80)
      .forEach((device) => warnings.push(`WARNING: High Latency > 80ms on ${roleLabels[device.role]}`));
    const banner = $("readinessBanner");
    banner.textContent = warnings.length ? warnings.join(" • ") : "STAGE READY: ALL 5 ROLES ONLINE";
    banner.className = `readiness-banner ${warnings.length ? "warning" : "ready"}`;
  }

  async function loadNetwork() {
    const response = await fetch("/api/network-info");
    if (!response.ok) throw new Error("Network information unavailable");
    const data = await response.json();
    const ips = data.all_ips || [data.primary_ip];
    selectedIp = selectedIp || data.primary_ip;
    $("ipSelector").innerHTML = ips.map((ip) => `<option value="${escapeHtml(ip)}">${escapeHtml(ip)}${ip === data.hotspot_ip ? " • RECOMMENDED HOTSPOT" : ""}</option>`).join("");
    $("ipSelector").value = selectedIp;
    $("networkSummary").textContent = data.hotspot_detected ? `Hotspot detected at ${data.hotspot_ip}` : "No mobile hotspot detected";
    await loadQr();
  }

  async function loadQr() {
    const response = await fetch(`/api/hub/qr?ip=${encodeURIComponent(selectedIp)}`);
    if (!response.ok) throw new Error("Unable to load role links");
    const data = await response.json();
    const badges = {display:"NO PIN", moderator:"PIN 1111", admin:"PIN 2222", buzzer_a:"PAIRING BUZZ_A", buzzer_b:"PAIRING BUZZ_B"};
    $("qrCards").innerHTML = Object.entries(data.urls).map(([role, item]) =>
      `<article class="qr-card"><img alt="${escapeHtml(item.label)} QR" src="data:image/svg+xml,${encodeURIComponent(data.qr[role])}">
      <h3>${escapeHtml(item.label)}</h3><span class="badge badge-accent">${badges[role]}</span><p>${escapeHtml(item.url)}</p><button class="btn btn-outline" data-copy="${escapeHtml(item.url)}">Copy URL</button></article>`).join("");
    document.querySelectorAll("[data-copy]").forEach((button) => button.onclick = async () => {
      try { await navigator.clipboard.writeText(button.dataset.copy); } catch (error) {
        const area = document.createElement("textarea"); area.value = button.dataset.copy; document.body.appendChild(area); area.select(); document.execCommand("copy"); area.remove();
      }
      button.textContent = "Copied!";
      setTimeout(() => { button.textContent = "Copy URL"; }, 1200);
    });
  }

  async function refreshDevices() {
    const response = await fetch("/api/devices");
    if (response.ok) renderDevices((await response.json()).devices);
  }

  async function refreshHubStatus() {
    const response = await fetch("/api/hub/status");
    if (!response.ok) return;
    const data = await response.json();
    $("serverAddress").textContent = data.bind;
    $("persistenceStatus").textContent = data.saved_at ? "SAVED" : "UNSAVED";
    $("persistenceTime").textContent = data.saved_at || "";
    $("testMode").checked = Boolean(data.test_mode);
  }

  async function launch(path) {
    const url = `${window.location.origin}${path}`;
    window.open(url, "_blank", "noopener");
  }

  function bindControls() {
    document.querySelectorAll("[data-launch]").forEach((link) => link.onclick = () => launch(link.dataset.launch));
    $("ipSelector").onchange = async () => { selectedIp = $("ipSelector").value; await loadQr(); };
    $("testBuzz").onclick = () => client.sendAction("hub_test_buzz_all", {}, "Control Hub test pulse");
    $("testBuzzA").onclick = () => client.sendAction("hub_test_buzz_a", {}, "Control Hub Buzzer A test");
    $("testBuzzB").onclick = () => client.sendAction("hub_test_buzz_b", {}, "Control Hub Buzzer B test");
    const espTestBtn = $("esp32Test");
    if (espTestBtn) {
      espTestBtn.onclick = () => {
        client.sendAction("hub_esp32_test", {}, "Trigger ESP32 hardware test pulse");
        appendAudit("ESP32 • Sending hardware TEST pulse...");
        espTestBtn.textContent = "Sending TEST...";
        setTimeout(() => { espTestBtn.textContent = "Test ESP32 Hardware"; }, 1000);
      };
    }
    const espResetBtn = $("esp32Reset");
    if (espResetBtn) {
      espResetBtn.onclick = () => {
        if (confirmAction("Send RESET signal to ESP32 hardware buzzer?")) {
          client.sendAction("hub_esp32_reset", {}, "Trigger ESP32 hardware reset");
          appendAudit("ESP32 • Sending hardware RESET signal...");
          espResetBtn.textContent = "Resetting...";
          setTimeout(() => { espResetBtn.textContent = "Send ESP32 RESET"; }, 1000);
        }
      };
    }
    const stageToggle = $("stageLockToggle");
    if (stageToggle) {
      stageToggle.onchange = () => {
        if (stageLockSync) return;
        const locked = stageToggle.checked;
        client.sendAction("toggle_stage_lock", { stage_locked: locked }, `Stage lock set to ${locked}`);
        const label = $("stageLockState");
        if (label) {
          label.textContent = locked ? "LOCKED" : "OPEN";
          label.style.color = locked ? "var(--orange, #f97316)" : "";
        }
        appendAudit(`STAGE ${locked ? "LOCKED • AUTHORIZED DEVICES ONLY" : "UNLOCKED"}`);
      };
    }
    $("runDiagnostic").onclick = () => {
      $("diagnosticStatus").textContent = "Running full stage diagnostic...";
      client.sendAction("hub_run_diagnostic", {}, "Full stage diagnostic");
    };
    $("swapBuzzers").onclick = () => { if (confirmAction("Swap the live Buzzer A and B roles?")) client.sendAction("hub_swap_buzzers", {}, "Control Hub buzzer swap"); };
    $("lockBuzzers").onclick = () => { if (confirmAction("Force lock all buzzers?")) client.sendAction("hub_lock_buzzers", {}, "Emergency buzzer lock"); };
    $("unlockBuzzers").onclick = () => { if (confirmAction("Force unlock all buzzers?")) client.sendAction("hub_unlock_buzzers", {}, "Emergency buzzer unlock"); };
    $("clearBuzz").onclick = () => client.sendAction("hub_clear_buzz", {}, "Clear active buzz");
    $("resetRound").onclick = () => { if (confirmAction("Emergency reset the current round?")) client.sendAction("hub_reset_round", {}, "Emergency round reset"); };
    $("testMode").onchange = () => client.sendAction("hub_set_test_mode", {enabled: $("testMode").checked}, "Buzzer test mode changed");
    $("soundAlerts").onchange = () => { soundAlerts = $("soundAlerts").checked; localStorage.setItem("hub-sound-alerts", String(soundAlerts)); };
    soundAlerts = localStorage.getItem("hub-sound-alerts") === "true";
    $("soundAlerts").checked = soundAlerts;
    $("rollback").onclick = () => {
      const snapshot = stateSnapshots.find((item) => Date.now() - item.at >= 45000) || stateSnapshots[1];
      if (!snapshot || !confirmAction("Restore the nearest recent in-browser snapshot?")) return;
      fetch("/api/hub/restore", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(snapshot.state)})
        .then((response) => { $("restoreStatus").textContent = response.ok ? "Rollback snapshot restored." : "Rollback rejected."; });
    };
    $("backup").onclick = () => { window.location.href = "/api/hub/backup"; };
    $("restore").onclick = async () => {
      const file = $("restoreFile").files[0];
      if (!file || !confirmAction("Restore this state.json and replace the live state?")) return;
      const response = await fetch("/api/hub/restore", {method: "POST", headers: {"Content-Type": "application/json"}, body: await file.text()});
      $("restoreStatus").textContent = response.ok ? "State restored and broadcast to all clients." : "Restore rejected: invalid state backup.";
    };
    $("clearAudit").onclick = () => { eventLog = []; renderAudit(); };
    document.querySelectorAll(".log-filter").forEach((button) => button.onclick = () => {
      activeFilter = button.dataset.filter;
      document.querySelectorAll(".log-filter").forEach((item) => item.classList.toggle("active", item === button));
      renderAudit();
    });
    $("logout").onclick = async () => { await fetch("/api/hub/logout", {method: "POST"}); window.location.reload(); };
  }

  function startHub() {
    $("hubGate").classList.add("hidden");
    $("hubApp").classList.remove("hidden");
    renderReadiness();
    bindControls();
    client = new QuizClient({
      role: "hub", pinOrCode: hubPin, deviceName: "Control Hub",
      onState: renderState,
      onStatusChange: setStatus,
      onLatency: (value) => { $("hubLatency").textContent = `${Math.round(value)} ms`; },
      onEvent: (event) => {
        appendAudit(`${event.name}${event.device ? ` • ${event.device.device_name || event.device.device_id}` : ""}`);
        if (event.name === "device_event_ack" && event.event === "hub_test_pulse") $("diagnosticStatus").textContent = "ACK RECEIVED from a buzzer.";
        if (event.name === "diagnostic_complete") $("diagnosticStatus").textContent = event.checks.passed ? "PASS: all diagnostic checks completed." : "FAIL: one or more diagnostic checks failed.";
        if (event.name === "hub_test_mode_changed") $("overrideStatus").textContent = `Buzzer test mode ${event.enabled ? "ON" : "OFF"}.`;
        if (event.name === "device_disconnected") refreshDevices();
        if (event.name === "device_disconnected") chime(220);
        if (event.name === "buzz_first" || event.name === "buzzers_locked") chime(660);
        if (event.name === "fairness_telemetry") $("fairness").textContent = `Latest: ${event.team} arrived ${event.arrival_timestamp_ms} ms${event.delta_ms == null ? "" : ` • Δ ${event.delta_ms} ms`}`;
        if (event.name.startsWith("esp32_") || event.name === "stage_lock_changed") {
          refreshEsp32Status().catch(() => {});
          if (event.name === "stage_lock_changed") {
            syncStageLock(Boolean(event.stage_locked));
            appendAudit(`STAGE ${event.stage_locked ? "LOCKED • AUTHORIZED DEVICES ONLY" : "UNLOCKED"}`);
          }
          if (event.name === "esp32_test") appendAudit("ESP32 • Test signal dispatched");
          if (event.name === "esp32_reset") appendAudit("ESP32 • Hardware reset signal dispatched");
        }
      },
      onAck: (message) => {
        if (message.success) appendAudit(`ACK • ${message.action}`);
        if (message.action === "hub_reset_round") $("overrideStatus").textContent = "Round reset complete.";
        if (message.action === "hub_run_diagnostic" && message.result) $("diagnosticStatus").textContent = message.result.passed ? "PASS: state writable and both buzzer diagnostics sent." : "FAIL: check missing devices or state write access.";
      },
      onError: (message) => { appendAudit(`ERROR • ${message.message || "Unknown error"}`); }
    });
    client.init();
    loadNetwork().catch((error) => { $("networkSummary").textContent = error.message; });
    refreshHubStatus().catch(() => {});
    refreshDevices().catch(() => {});
    refreshEsp32Status().catch(() => {});
    setInterval(() => refreshDevices().catch(() => {}), 3000);
    setInterval(() => refreshHubStatus().catch(() => {}), 3000);
    setInterval(() => refreshEsp32Status().catch(() => {}), 3000);
    setInterval(() => fetch("/api/health").then((response) => response.json()).then((data) => {
      $("uptime").textContent = `${Math.floor(data.uptime_seconds / 60)}m ${Math.floor(data.uptime_seconds % 60)}s`;
    }).catch(() => { $("serverStatus").textContent = "OFFLINE"; }), 3000);
  }

  async function checkSession() {
    const response = await fetch("/api/hub/session");
    if (response.ok && (await response.json()).authenticated) startHub();
  }

  $("hubPinForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    hubPin = $("hubPin").value.trim();
    const response = await fetch("/api/hub/auth", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({pin: hubPin})});
    if (response.ok) { $("hubPinError").textContent = ""; startHub(); }
    else $("hubPinError").textContent = "Invalid Hub PIN.";
  });
  checkSession().catch(() => {});
})();
