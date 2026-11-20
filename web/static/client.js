class QuizClient {
  constructor(options = {}) {
    this.role = options.role || "display";
    this.pinOrCode = options.pinOrCode || options.pin || options.pairing || "";
    this.pairingCodes = {buzzer_a: "BUZZ_A", buzzer_b: "BUZZ_B"};
    this.deviceId = options.deviceId || this.loadDeviceId();
    this.deviceName = options.deviceName || this.defaultDeviceName();
    this.onState = options.onState || (() => {});
    this.onEvent = options.onEvent || (() => {});
    this.onAck = options.onAck || (() => {});
    this.onError = options.onError || (() => {});
    this.onRoleChange = options.onRoleChange || (() => {});
    this.onStatusChange = options.onStatusChange || (() => {});
    this.onLatency = options.onLatency || (() => {});
    this.ws = null;
    this.retryTimer = null;
    this.retryAttempt = 0;
    this.pingTimer = null;
    this.stopped = false;
  }

  loadDeviceId() {
    const key = "eee-brain-battle-device-id";
    try {
      let value = window.localStorage.getItem(key);
      if (!value) {
        value = `web_${Math.random().toString(36).slice(2, 10)}`;
        window.localStorage.setItem(key, value);
      }
      return value;
    } catch (error) {
      return `web_${Math.random().toString(36).slice(2, 10)}`;
    }
  }

  defaultDeviceName() {
    const platform = navigator.userAgentData?.platform || navigator.platform || "Browser";
    return `${platform} browser`;
  }

  init() {
    this.stopped = false;
    this.connect();
  }

  stop() {
    this.stopped = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.retryTimer = null;
    this.pingTimer = null;
    if (this.ws) this.ws.close();
  }

  connect() {
    if (this.stopped || (this.ws && [WebSocket.OPEN, WebSocket.CONNECTING].includes(this.ws.readyState))) return;
    this.onStatusChange("reconnecting", "Connecting...");
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    try {
      this.ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    } catch (error) {
      this.scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      this.retryAttempt = 0;
      this.ws.send(JSON.stringify({
        type: "hello",
        role: this.role,
        device_id: this.deviceId,
        device_name: this.deviceName,
        user_agent: navigator.userAgent,
        pin: this.pinOrCode,
        pairing: this.pinOrCode,
        pin_or_code: this.pinOrCode
      }));
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.pingTimer = setInterval(() => {
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({type: "ping", client_time: Date.now()}));
        }
      }, 3000);
    };
    this.ws.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch (error) { return; }
      if (message.type === "welcome") {
        this.deviceId = message.device_id || this.deviceId;
        this.onStatusChange("online", "CONNECTED");
      } else if (message.type === "state") {
        this.onState(message.data);
      } else if (message.type === "event") {
        if (message.name === "device_role_assigned" && message.device &&
            message.device.device_id === this.deviceId) {
          this.role = message.device.role || this.role;
          if (this.pairingCodes[this.role]) this.pinOrCode = this.pairingCodes[this.role];
          this.onRoleChange(this.role, message.device);
        }
        if (message.name === "hub_test_pulse" || message.name === "hub_ping_request") {
          if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
              type: message.name === "hub_test_pulse" ? "hub_test_ack" : "device_event_ack",
              event: message.name
            }));
          }
        }
        this.onEvent(message);
      } else if (message.type === "pong") {
        const sent = Number(message.client_time);
        if (Number.isFinite(sent)) {
          const latency = Math.max(0, Date.now() - sent);
          this.onLatency(latency);
          if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({type: "latency_report", latency_ms: latency}));
          }
        }
      } else if (message.type === "action_ack") {
        this.onAck(message);
      } else if (message.type === "auth_error") {
        this.onStatusChange("auth_error", message.message || "Authentication failed");
      } else if (message.type === "error") {
        this.onError(message);
      }
    };
    this.ws.onclose = () => {
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.pingTimer = null;
      this.onStatusChange("offline", "Disconnected - reconnecting...");
      this.scheduleReconnect();
    };
    this.ws.onerror = () => this.onStatusChange("offline", "Connection error");
  }

  scheduleReconnect() {
    if (this.stopped || this.retryTimer) return;
    const delay = Math.min(500 * (2 ** this.retryAttempt), 5000);
    this.retryAttempt += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  sendAction(action, payload = {}, reason = "") {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify({type: "action", action, payload, reason}));
    return true;
  }

  sendBuzz(teamId = null) {
    return this.sendAction("buzz", teamId ? {team: teamId} : {}, "Buzzer pressed");
  }
}

window.QuizClient = QuizClient;
