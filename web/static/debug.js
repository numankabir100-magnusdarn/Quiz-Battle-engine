/**
 * EEE Brain Battle - Phase 1 Debug Client
 * Manages WebSocket connection, role auth, heartbeat ping/pong,
 * latency measurement, and event stream.
 */

let ws = null;
let pingInterval = null;
let currentRole = "admin";

const defaultPins = {
  admin: "2222",
  moderator: "1111",
  hub: "3333",
  buzzer_a: "BUZZ_A",
  buzzer_b: "BUZZ_B",
  display: "",
};

function onRoleChange() {
  const roleSelect = document.getElementById("roleSelect");
  const pinInput = document.getElementById("pinInput");
  const role = roleSelect.value;
  pinInput.value = defaultPins[role] ?? "";
}

function connectWS() {
  if (ws) {
    clearInterval(pingInterval);
    ws.close();
  }

  const roleSelect = document.getElementById("roleSelect");
  const pinInput = document.getElementById("pinInput");
  const connBadge = document.getElementById("connBadge");
  const stateBox = document.getElementById("stateBox");

  const role = roleSelect.value;
  const pin = pinInput.value;
  currentRole = role;

  connBadge.textContent = "Connecting...";
  connBadge.className = "badge";

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    logEvent("WebSocket connected. Sending handshake...");
    ws.send(JSON.stringify({
      type: "hello",
      role: role,
      pin_or_code: pin
    }));
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleMessage(msg);
    } catch (err) {
      console.error("Failed to parse message:", err);
    }
  };

  ws.onclose = () => {
    connBadge.textContent = "Disconnected";
    connBadge.className = "badge badge-danger";
    clearInterval(pingInterval);
    logEvent("WebSocket disconnected");
  };

  ws.onerror = (err) => {
    connBadge.textContent = "Error";
    connBadge.className = "badge badge-danger";
    logEvent("WebSocket encountered an error");
  };
}

function handleMessage(msg) {
  const connBadge = document.getElementById("connBadge");
  const stateBox = document.getElementById("stateBox");
  const stateUpdated = document.getElementById("stateUpdated");
  const currentRoleLabel = document.getElementById("currentRoleLabel");

  if (msg.type === "welcome") {
    connBadge.textContent = `Connected (${msg.role})`;
    connBadge.className = "badge badge-success";
    currentRoleLabel.textContent = `Role: ${msg.role}`;
    logEvent(`Authenticated successfully as '${msg.role}' [Device: ${msg.device_id}]`, true);

    // Start periodic ping for latency measurement
    startPing();
    fetchDevices();
  } else if (msg.type === "state") {
    stateBox.textContent = JSON.stringify(msg.data, null, 2);
    stateUpdated.textContent = new Date().toLocaleTimeString();
    updateSummary(msg.data);
  } else if (msg.type === "event") {
    logEvent(`EVENT: ${msg.name} -> ${JSON.stringify(msg)}`, true);
    if (msg.name === "timer_tick") {
      document.getElementById("timerDisplay").textContent = `${msg.seconds}s`;
    }
  } else if (msg.type === "pong") {
    if (msg.client_time) {
      const latency = Math.round(performance.now() - msg.client_time);
      document.getElementById("latencyBadge").textContent = `${latency} ms`;
      // Report latency to server for device registry
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "latency_report", latency_ms: latency }));
      }
    }
  } else if (msg.type === "auth_error") {
    connBadge.textContent = "Auth Failed";
    connBadge.className = "badge badge-danger";
    logEvent(`AUTH ERROR: ${msg.message}`);
    alert(`Authentication Error: ${msg.message}`);
  } else if (msg.type === "error") {
    logEvent(`ERROR: ${msg.message}`);
    alert(`Server Error: ${msg.message}`);
  } else if (msg.type === "action_ack") {
    logEvent(`ACK: Action '${msg.action}' succeeded`);
  }
}

function startPing() {
  if (pingInterval) clearInterval(pingInterval);
  pingInterval = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "ping",
        client_time: performance.now()
      }));
    }
  }, 2500);
}

function sendAction(action, payload = {}) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    alert("WebSocket is not connected. Click Connect first.");
    return;
  }
  logEvent(`Sending action: ${action}`);
  ws.send(JSON.stringify({
    type: "action",
    action: action,
    payload: payload,
    reason: `Debug UI action '${action}' triggered`
  }));
}

function updateSummary(state) {
  if (!state) return;
  const ev = state.event || {};
  const curr = state.current_match || {};
  const round = state.round || {};
  const scores = curr.scores || {};

  document.getElementById("stageDisplay").textContent = ev.stage || "-";
  document.getElementById("matchDisplay").textContent = `Match ${ev.match_number || "-"}`;
  document.getElementById("phaseDisplay").textContent = round.phase || "-";
  document.getElementById("timerDisplay").textContent = `${round.timer_seconds_remaining || 0}s`;

  const teamAId = curr.team_a_id || "Team A";
  const teamBId = curr.team_b_id || "Team B";

  const teamAName = state.teams && state.teams[teamAId] ? state.teams[teamAId].name : teamAId;
  const teamBName = state.teams && state.teams[teamBId] ? state.teams[teamBId].name : teamBId;

  document.getElementById("teamAName").textContent = teamAName;
  document.getElementById("teamBName").textContent = teamBName;
  document.getElementById("teamAScore").textContent = scores[teamAId] ?? 0;
  document.getElementById("teamBScore").textContent = scores[teamBId] ?? 0;
}

function logEvent(text, important = false) {
  const box = document.getElementById("eventLog");
  const item = document.createElement("div");
  item.className = "event-item" + (important ? " important" : "");
  const time = new Date().toLocaleTimeString();
  item.textContent = `[${time}] ${text}`;
  box.prepend(item);
}

function clearEvents() {
  document.getElementById("eventLog").innerHTML = "";
}

async function fetchDevices() {
  try {
    const res = await fetch("/api/devices");
    const data = await res.json();
    const tbody = document.getElementById("devicesTableBody");
    tbody.innerHTML = "";
    if (data.devices && data.devices.length > 0) {
      data.devices.forEach((dev) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><span class="badge ${dev.role === 'admin' ? 'badge-accent' : 'badge-outline'}">${dev.role}</span></td>
          <td>${dev.ip}</td>
          <td class="text-mono" style="font-size: 0.75rem;">${dev.last_ping ? dev.last_ping.split('T')[1]?.slice(0,8) : '-'}</td>
          <td>${dev.latency_ms} ms</td>
        `;
        tbody.appendChild(tr);
      });
    } else {
      tbody.innerHTML = `<tr><td colspan="4" class="text-muted">No devices connected</td></tr>`;
    }
  } catch (err) {
    console.error("Failed to fetch devices:", err);
  }
}

async function loadServerInfo() {
  const badge = document.getElementById("serverInfo");
  if (!badge) return;
  try {
    const [networkResponse, healthResponse] = await Promise.all([
      fetch("/api/network-info", {cache: "no-store"}),
      fetch("/api/health", {cache: "no-store"}),
    ]);
    if (!networkResponse.ok || !healthResponse.ok) throw new Error("Server status request failed");
    const network = await networkResponse.json();
    const health = await healthResponse.json();
    const ips = (network.all_ips || []).filter((ip) => !ip.startsWith("127.") && !ip.startsWith("169.254."));
    badge.textContent = `Server: ONLINE • ${(ips.join(", ") || "localhost")}:${network.port} • Uptime ${Math.floor(health.uptime_seconds || 0)}s`;
    badge.className = "badge badge-success";
    badge.title = `${network.base_url || window.location.origin}/debug`;
  } catch (error) {
    badge.textContent = "Server: status unavailable";
    badge.className = "badge badge-danger";
  }
}

// Auto-connect on load
window.addEventListener("DOMContentLoaded", () => {
  loadServerInfo();
  connectWS();
  setInterval(fetchDevices, 5000);
  setInterval(loadServerInfo, 10000);
});
