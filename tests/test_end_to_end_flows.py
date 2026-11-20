from starlette.testclient import TestClient

from server.main import app


def _hello(websocket, role, pin):
    websocket.send_json({"type": "hello", "role": role, "pin_or_code": pin})
    assert websocket.receive_json()["type"] == "welcome"
    assert websocket.receive_json()["type"] == "state"


def _action_messages(websocket, action, payload=None, reason="test"):
    websocket.send_json({
        "type": "action",
        "action": action,
        "payload": payload or {},
        "reason": reason,
    })
    messages = [websocket.receive_json(), websocket.receive_json()]
    if messages[-1]["type"] != "action_ack":
        messages.append(websocket.receive_json())
    return messages


def test_hub_session_and_restore_endpoints_are_authenticated():
    client = TestClient(app)
    assert client.get("/api/hub/qr").status_code == 401
    assert client.post("/api/hub/auth", json={"pin": "3333"}).status_code == 200
    assert client.get("/api/hub/qr").status_code == 200
    backup = client.get("/api/hub/backup")
    assert backup.status_code == 200
    assert client.post("/api/hub/restore", json=backup.json()).status_code == 200


def test_moderator_actions_persist_and_broadcast_state():
    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        _hello(websocket, "moderator", "1111")
        messages = _action_messages(websocket, "configure_routing", {
            "mode": "AUTO_ALTERNATE",
            "start_side": "A",
            "block_size": 10,
        })
        assert any(message["type"] == "action_ack" for message in messages)
        messages = _action_messages(websocket, "start_rapid_fire", {
            "team_id": "team_1",
            "duration_seconds": 120,
        })
        assert any(message["type"] == "action_ack" for message in messages)
        messages = _action_messages(websocket, "open_question")
        assert any(message["type"] == "action_ack" for message in messages)
    state = client.get("/api/state").json()
    assert state["round"]["phase"] == "RAPID_FIRE"
    assert state["question"]["current_question"]["number"] == 1
    assert "text" not in state["question"]["current_question"]


def test_buzzer_battle_pass_over_is_restricted_to_opponent():
    client = TestClient(app)
    with client.websocket_connect("/ws") as moderator:
        _hello(moderator, "moderator", "1111")
        _action_messages(moderator, "start_buzzer_battle")
        _action_messages(moderator, "open_question")
    with client.websocket_connect("/ws") as buzzer_a:
        _hello(buzzer_a, "buzzer_a", "BUZZ_A")
        messages = _action_messages(buzzer_a, "buzz")
        assert any(message["type"] == "action_ack" for message in messages)
    with client.websocket_connect("/ws") as moderator:
        _hello(moderator, "moderator", "1111")
        messages = _action_messages(moderator, "mark_wrong", {"team_id": "team_1"})
        assert any(message["type"] == "action_ack" for message in messages)
    state = client.get("/api/state").json()
    assert state["buzzers"]["passed_to_team"] == "team_2"
    assert state["buzzers"]["locked"] is False


def test_admin_display_controller_and_report_export():
    client = TestClient(app)
    assert client.post("/api/admin/auth", json={"pin": "2222"}).status_code == 200
    assert client.get("/api/admin/report?format=json").status_code == 200
    assert client.get("/api/admin/report?format=csv").status_code == 200
    with client.websocket_connect("/ws") as admin:
        _hello(admin, "admin", "2222")
        messages = _action_messages(admin, "set_display_view", {"view": "bracket"})
        assert any(message["type"] == "action_ack" for message in messages)
    assert client.get("/api/state").json()["display_view"] == "bracket"
