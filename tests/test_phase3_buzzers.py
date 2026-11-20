from starlette.testclient import TestClient

from server.main import app


def hello(websocket, role, code):
    websocket.send_json({
        "type": "hello",
        "role": role,
        "pairing": code,
        "pin_or_code": code,
        "device_id": f"phase3-{role}",
    })
    assert websocket.receive_json()["type"] == "welcome"
    assert websocket.receive_json()["type"] == "state"


def wait_for(websocket, message_type, name=None):
    for _ in range(20):
        message = websocket.receive_json()
        if message.get("type") == message_type and (name is None or message.get("name") == name):
            return message
    raise AssertionError(f"Expected {message_type} {name or ''}")


def action(websocket, name, payload=None):
    websocket.send_json({"type": "action", "action": name, "payload": payload or {}, "reason": "Phase 3 test"})
    return wait_for(websocket, "action_ack") if name != "buzz" else wait_for(websocket, "action_ack")


def test_server_arrival_order_and_fairness_delta():
    client = TestClient(app)
    with client.websocket_connect("/ws") as moderator:
        hello(moderator, "moderator", "1111")
        action(moderator, "start_buzzer_battle")
        action(moderator, "open_question")
    with client.websocket_connect("/ws") as buzzer_a, client.websocket_connect("/ws") as buzzer_b:
        hello(buzzer_a, "buzzer_a", "BUZZ_A")
        hello(buzzer_b, "buzzer_b", "BUZZ_B")
        buzzer_a.send_json({"type": "buzz", "client_time": 1000})
        first = wait_for(buzzer_a, "action_ack")
        assert first["success"] is True
        assert first["result"]["team_id"] == "team_1"
        assert first["result"]["arrival_timestamp_ms"] is not None
        buzzer_b.send_json({"type": "action", "action": "buzz", "payload": {}, "reason": "Phase 3 test"})
        rejected = wait_for(buzzer_b, "error")
        assert "already buzzed first" in rejected["message"] or "locked" in rejected["message"]
    state = client.get("/api/state").json()
    assert state["buzzers"]["first_team"] == "team_1"


def test_wrong_answer_passes_only_to_opponent():
    client = TestClient(app)
    with client.websocket_connect("/ws") as moderator:
        hello(moderator, "moderator", "1111")
        action(moderator, "start_buzzer_battle")
        action(moderator, "open_question")
    with client.websocket_connect("/ws") as buzzer_a:
        hello(buzzer_a, "buzzer_a", "BUZZ_A")
        action(buzzer_a, "buzz")
    with client.websocket_connect("/ws") as moderator:
        hello(moderator, "moderator", "1111")
        result = action(moderator, "mark_wrong", {"team_id": "team_1"})
        assert result["result"]["passed_to"] == "team_2"
    state = client.get("/api/state").json()
    assert state["buzzers"]["passed_to_team"] == "team_2"
    assert state["buzzers"]["locked"] is False


def test_test_mode_buzz_does_not_change_score_or_matrix():
    client = TestClient(app)
    with client.websocket_connect("/ws") as hub:
        hello(hub, "hub", "3333")
        action(hub, "hub_set_test_mode", {"enabled": True})
    before = client.get("/api/state").json()
    with client.websocket_connect("/ws") as buzzer:
        hello(buzzer, "buzzer_a", "BUZZ_A")
        result = action(buzzer, "buzz")
        assert result["result"]["test_mode"] is True
    after = client.get("/api/state").json()
    assert after["current_match"]["scores"] == before["current_match"]["scores"]
    assert after["question_matrix"] == before["question_matrix"]
    with client.websocket_connect("/ws") as hub:
        hello(hub, "hub", "3333")
        action(hub, "hub_set_test_mode", {"enabled": False})


def test_hub_test_pulse_round_trip_uses_hub_test_ack():
    client = TestClient(app)
    with client.websocket_connect("/ws") as hub, client.websocket_connect("/ws") as buzzer:
        hello(hub, "hub", "3333")
        hello(buzzer, "buzzer_a", "BUZZ_A")
        hub.send_json({"type": "action", "action": "hub_test_buzz_a", "payload": {}, "reason": "Phase 3 test"})
        wait_for(buzzer, "event", "hub_test_pulse")
        buzzer.send_json({"type": "hub_test_ack", "event": "hub_test_pulse"})
        acknowledgment = wait_for(hub, "event", "device_event_ack")
        assert acknowledgment["acknowledgment"] == "hub_test_ack"
