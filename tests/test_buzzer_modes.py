import asyncio
from starlette.testclient import TestClient
from server.main import app, engine, esp32_on_buzz


def _hello(websocket, role, pin, device_id=None):
    payload = {"type": "hello", "role": role, "pin_or_code": pin}
    if device_id:
        payload.update({
            "device_id": device_id,
            "device_name": f"{role} test device",
            "user_agent": "BuzzerMode-Test-Agent",
        })
    websocket.send_json(payload)
    assert websocket.receive_json()["type"] == "welcome"
    assert websocket.receive_json()["type"] == "state"


def _wait_for_ack_and_events(websocket, action):
    events = []
    ack = None
    for _ in range(15):
        message = websocket.receive_json()
        if message.get("type") == "event":
            events.append(message)
        elif message.get("type") == "action_ack" and message.get("action") == action:
            ack = message
            break
    if not ack:
        raise AssertionError(f"No acknowledgement received for {action}")
    return ack, events


def _wait_for_ack(websocket, action):
    ack, _ = _wait_for_ack_and_events(websocket, action)
    return ack


def test_buzzers_page_served():
    client = TestClient(app)
    res = client.get("/buzzers")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "BUZZER &amp; HARDWARE MANAGER" in res.text
    assert "cardEsp32" in res.text
    assert "cardMobile" in res.text
    assert "signalFeed" in res.text


def test_buzzer_mode_endpoints():
    client = TestClient(app)

    # Initial GET
    res = client.get("/api/buzzers/mode")
    assert res.status_code == 200
    data = res.json()
    assert "buzzer_source_mode" in data
    assert "esp32_detected" in data
    assert "mobile_a_connected" in data
    assert "mobile_b_connected" in data

    # Invalid mode
    bad_res = client.post("/api/buzzers/mode", json={"mode": "BLUETOOTH"})
    assert bad_res.status_code == 400

    # Switch to MOBILE
    mob_res = client.post("/api/buzzers/mode", json={"mode": "MOBILE"})
    assert mob_res.status_code == 200
    assert mob_res.json()["buzzer_source_mode"] == "MOBILE"
    assert engine.buzzer_source_mode == "MOBILE"

    # Switch back to ESP32
    esp_res = client.post("/api/buzzers/mode", json={"mode": "ESP32"})
    assert esp_res.status_code == 200
    assert esp_res.json()["buzzer_source_mode"] == "ESP32"
    assert engine.buzzer_source_mode == "ESP32"

    # Cleanup
    engine.strict_esp32 = False


def test_buzzers_qr_endpoint():
    client = TestClient(app)
    res = client.get("/api/buzzers/qr")
    assert res.status_code == 200
    data = res.json()
    assert "primary_ip" in data
    assert "urls" in data
    assert "qr" in data
    assert "buzzer_a" in data["qr"]
    assert "buzzer_b" in data["qr"]
    assert "<svg" in data["qr"]["buzzer_a"]
    assert "<svg" in data["qr"]["buzzer_b"]


def test_mobile_lockout_when_strict_esp32_active():
    client = TestClient(app)

    # Ensure ESP32 mode with strict enforcement
    client.post("/api/buzzers/mode", json={"mode": "ESP32"})
    engine.strict_esp32 = True

    try:
        with client.websocket_connect("/ws") as ws:
            _hello(ws, "buzzer_a", "BUZZ_A", "strict_esp_phone_a")

            # Try to buzz while in strict ESP32 mode
            ws.send_json({"type": "action", "action": "buzz", "payload": {}})
            ack = _wait_for_ack(ws, "buzz")
            assert ack.get("result", {}).get("status") == "ignored"
            assert "ESP32 Primary Active" in ack.get("result", {}).get("reason", "")
    finally:
        engine.strict_esp32 = False


def test_esp32_ignored_when_mobile_mode_active():
    client = TestClient(app)

    # Set mode to MOBILE
    client.post("/api/buzzers/mode", json={"mode": "MOBILE"})
    assert engine.buzzer_source_mode == "MOBILE"

    # In MOBILE mode, esp32_on_buzz must return False
    handled = asyncio.run(esp32_on_buzz("TEAM_A"))
    assert handled is False

    # Switch back to ESP32
    client.post("/api/buzzers/mode", json={"mode": "ESP32"})
    engine.strict_esp32 = False


def test_websocket_set_buzzer_source_mode():
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        _hello(ws, "hub", "3333", "hub_mode_test")

        # Send set_buzzer_source_mode to MOBILE
        ws.send_json({
            "type": "action",
            "action": "set_buzzer_source_mode",
            "payload": {"mode": "MOBILE"},
            "reason": "Test failover switch",
        })
        ack, events = _wait_for_ack_and_events(ws, "set_buzzer_source_mode")
        assert ack.get("success") is True
        assert engine.buzzer_source_mode == "MOBILE"
        mode_events = [e for e in events if e.get("name") == "buzzer_source_mode_changed"]
        assert len(mode_events) >= 1
        assert mode_events[0].get("mode") == "MOBILE"

        # Switch back to ESP32
        ws.send_json({
            "type": "action",
            "action": "set_buzzer_source_mode",
            "payload": {"mode": "ESP32"},
            "reason": "Test return to ESP32",
        })
        ack2, events2 = _wait_for_ack_and_events(ws, "set_buzzer_source_mode")
        assert ack2.get("success") is True
        assert engine.buzzer_source_mode == "ESP32"

    engine.strict_esp32 = False
