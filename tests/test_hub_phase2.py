from starlette.testclient import TestClient

from server.main import app


def _hello(websocket, role, pin, device_id=None):
    payload = {"type": "hello", "role": role, "pin_or_code": pin}
    if device_id:
        payload.update({
            "device_id": device_id,
            "device_name": f"{role} test device",
            "user_agent": "Phase2-Test-Agent",
        })
    websocket.send_json(payload)
    assert websocket.receive_json()["type"] == "welcome"
    assert websocket.receive_json()["type"] == "state"


def _wait_for_ack(websocket, action):
    for _ in range(10):
        message = websocket.receive_json()
        if message.get("type") == "action_ack" and message.get("action") == action:
            return message
    raise AssertionError(f"No acknowledgement received for {action}")


def _wait_for_type(websocket, message_type):
    for _ in range(10):
        message = websocket.receive_json()
        if message.get("type") == message_type:
            return message
    raise AssertionError(f"No {message_type} message received")


def _wait_for_event(websocket, name):
    for _ in range(20):
        message = websocket.receive_json()
        if message.get("type") == "event" and message.get("name") == name:
            return message
    raise AssertionError(f"No event named {name} received")


def test_hub_pin_gate_and_session_cookie():
    client = TestClient(app)
    assert client.get("/api/hub/qr").status_code == 401
    assert client.post("/api/hub/auth", json={"pin": "wrong"}).status_code == 401
    assert client.post("/api/hub/auth", json={"pin": "3333"}).status_code == 200
    assert client.get("/api/hub/session").json()["authenticated"] is True
    assert client.post("/api/hub/logout").status_code == 200
    assert client.get("/api/hub/session").json()["authenticated"] is False


def test_hub_qr_switches_selected_ip():
    client = TestClient(app)
    assert client.post("/api/hub/auth", json={"pin": "3333"}).status_code == 200
    first = client.get("/api/hub/qr?ip=192.168.1.8").json()
    second = client.get("/api/hub/qr?ip=192.168.137.1").json()
    assert first["ip"] == "192.168.1.8"
    assert second["ip"] == "192.168.137.1"
    assert "192.168.1.8" in first["urls"]["display"]["url"]
    assert "192.168.137.1" in second["qr"]["buzzer_a"]


def test_hub_tracks_latency_and_swaps_buzzer_roles():
    client = TestClient(app)
    with client.websocket_connect("/ws") as hub, client.websocket_connect("/ws") as buzzer_a, client.websocket_connect("/ws") as buzzer_b:
        _hello(hub, "hub", "3333", "hub-stable")
        _hello(buzzer_a, "buzzer_a", "BUZZ_A", "phone-a-stable")
        _hello(buzzer_b, "buzzer_b", "BUZZ_B", "phone-b-stable")
        buzzer_a.send_json({"type": "ping", "client_time": 1})
        assert _wait_for_type(buzzer_a, "pong")["type"] == "pong"
        buzzer_a.send_json({"type": "latency_report", "latency_ms": 24})
        devices = client.get("/api/devices").json()["devices"]
        phone_a = next(device for device in devices if device["device_id"] == "phone-a-stable")
        assert phone_a["latency_ms"] == 24
        hub.send_json({"type": "action", "action": "hub_swap_buzzers", "payload": {}, "reason": "Phase 2 test"})
        ack = _wait_for_ack(hub, "hub_swap_buzzers")
        assert ack["success"] is True
        devices = {device["device_id"]: device for device in client.get("/api/devices").json()["devices"]}
        assert devices["phone-a-stable"]["role"] == "buzzer_b"
        assert devices["phone-b-stable"]["role"] == "buzzer_a"


def test_hub_test_pulse_and_backup_restore():
    client = TestClient(app)
    assert client.post("/api/hub/auth", json={"pin": "3333"}).status_code == 200
    backup = client.get("/api/hub/backup")
    assert backup.status_code == 200
    original = backup.json()
    with client.websocket_connect("/ws") as hub, client.websocket_connect("/ws") as buzzer:
        _hello(hub, "hub", "3333", "hub-pulse")
        _hello(buzzer, "buzzer_a", "BUZZ_A", "phone-pulse")
        hub.send_json({"type": "action", "action": "hub_test_buzz_all", "payload": {}, "reason": "Phase 2 test"})
        _wait_for_event(buzzer, "hub_test_pulse")
        _wait_for_ack(hub, "hub_test_buzz_all")
    assert client.post("/api/hub/restore", json=original).status_code == 200


def test_hub_status_targeted_pulse_and_full_diagnostic():
    client = TestClient(app)
    assert client.post("/api/hub/auth", json={"pin": "3333"}).status_code == 200
    status = client.get("/api/hub/status")
    assert status.status_code == 200
    net = client.get("/api/network").json()
    assert status.json()["bind"].endswith(":" + str(net["port"]))
    with client.websocket_connect("/ws") as hub, client.websocket_connect("/ws") as buzzer_a, client.websocket_connect("/ws") as buzzer_b:
        _hello(hub, "hub", "3333", "hub-diagnostic")
        _hello(buzzer_a, "buzzer_a", "BUZZ_A", "diag-a")
        _hello(buzzer_b, "buzzer_b", "BUZZ_B", "diag-b")
        hub.send_json({"type": "action", "action": "hub_test_buzz_a", "payload": {}, "reason": "Targeted test"})
        pulse = _wait_for_event(buzzer_a, "hub_test_pulse")
        buzzer_a.send_json({"type": "device_event_ack", "event": "hub_test_pulse"})
        _wait_for_type(hub, "event")
        _wait_for_ack(hub, "hub_test_buzz_a")
        hub.send_json({"type": "action", "action": "hub_run_diagnostic", "payload": {}, "reason": "Full diagnostic"})
        diagnostic = _wait_for_ack(hub, "hub_run_diagnostic")
        assert diagnostic["result"]["state_writable"] is True
        assert diagnostic["result"]["buzzer_a_pulse"] is True
        assert diagnostic["result"]["buzzer_b_pulse"] is True


def test_hub_kicks_device():
    client = TestClient(app)
    with client.websocket_connect("/ws") as hub, client.websocket_connect("/ws") as buzzer:
        _hello(hub, "hub", "3333", "hub-kick")
        _hello(buzzer, "buzzer_a", "BUZZ_A", "kick-target")
        hub.send_json({
            "type": "action",
            "action": "hub_kick_device",
            "payload": {"device_id": "kick-target"},
            "reason": "Remove test device",
        })
        ack = _wait_for_ack(hub, "hub_kick_device")
        assert ack["result"]["kicked"] is True
