import pytest
from starlette.testclient import TestClient
from server.main import app
from server.config import Config
from server.ws_manager import WebSocketManager


def test_config_auth_validation(test_config: Config):
    """Verifies PIN / Pairing code validation across all roles."""
    cfg = test_config

    # Display (open or empty pin)
    assert cfg.validate_auth("display", "") is True

    # Moderator (default 1111)
    assert cfg.validate_auth("moderator", "1111") is True
    assert cfg.validate_auth("moderator", "wrong") is False

    # Admin (default 2222)
    assert cfg.validate_auth("admin", "2222") is True
    assert cfg.validate_auth("admin", "1111") is False

    # Hub (default 3333)
    assert cfg.validate_auth("hub", "3333") is True
    assert cfg.validate_auth("hub", "2222") is False

    # Buzzers (pairing codes)
    assert cfg.validate_auth("buzzer_a", "BUZZ_A") is True
    assert cfg.validate_auth("buzzer_a", "wrong") is False
    assert cfg.validate_auth("buzzer_b", "BUZZ_B") is True
    assert cfg.validate_auth("buzzer_b", "BUZZ_A") is False

    # Unknown role
    assert cfg.validate_auth("hacker", "1234") is False


def test_role_action_permissions(test_config: Config):
    """Verifies matrix of allowed actions per role."""
    manager = WebSocketManager(config=test_config)

    # 1. Display: Read only (all actions rejected)
    assert manager.is_action_allowed("display", "open_question") is False
    assert manager.is_action_allowed("display", "buzz") is False
    assert manager.is_action_allowed("display", "mark_correct") is False
    assert manager.is_action_allowed("display", "admin_adjust_score") is False

    # 2. Hub: Read all / monitor (all actions rejected)
    assert manager.is_action_allowed("hub", "open_question") is False
    assert manager.is_action_allowed("hub", "buzz") is False

    # 3. Buzzer: only buzz()
    assert manager.is_action_allowed("buzzer_a", "buzz") is True
    assert manager.is_action_allowed("buzzer_a", "mark_correct") is False
    assert manager.is_action_allowed("buzzer_a", "open_question") is False
    assert manager.is_action_allowed("buzzer_b", "buzz") is True
    assert manager.is_action_allowed("buzzer_b", "admin_adjust_score") is False

    # 4. Moderator: match flow actions allowed; admin actions rejected
    assert manager.is_action_allowed("moderator", "open_question") is True
    assert manager.is_action_allowed("moderator", "mark_correct") is True
    assert manager.is_action_allowed("moderator", "mark_wrong") is True
    assert manager.is_action_allowed("moderator", "confirm_first_buzz") is True
    assert manager.is_action_allowed("moderator", "start_rapid_fire") is True
    assert manager.is_action_allowed("moderator", "next_question") is True
    # Admin-only actions disallowed for moderator:
    assert manager.is_action_allowed("moderator", "admin_adjust_score") is False
    assert manager.is_action_allowed("moderator", "setup_match") is False
    assert manager.is_action_allowed("moderator", "reset_match") is False
    assert manager.is_action_allowed("moderator", "override_quarterfinal_pairings") is False

    # 5. Admin: ALL actions allowed
    assert manager.is_action_allowed("admin", "setup_match") is True
    assert manager.is_action_allowed("admin", "admin_adjust_score") is True
    assert manager.is_action_allowed("admin", "reset_match") is True
    assert manager.is_action_allowed("admin", "override_quarterfinal_pairings") is True
    assert manager.is_action_allowed("admin", "open_question") is True
    assert manager.is_action_allowed("admin", "mark_correct") is True


def test_websocket_auth_and_permission_enforcement():
    """Integration test connecting WebSocket clients with different roles
    and testing permission enforcement live.
    """
    client = TestClient(app)

    # 1. Invalid auth rejected
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "role": "admin", "pin_or_code": "wrong_pin"})
        resp = ws.receive_json()
        assert resp["type"] == "auth_error"

    # 2. Display connection: read-only
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "role": "display", "pin_or_code": ""})
        welcome = ws.receive_json()
        assert welcome["type"] == "welcome"
        assert welcome["role"] == "display"

        # Initial state is immediately broadcasted
        state_msg = ws.receive_json()
        assert state_msg["type"] == "state"

        # Attempting an action must be rejected
        ws.send_json({"type": "action", "action": "open_question", "payload": {}})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "Permission denied" in err["message"]

    # 3. Moderator: match flow permitted, admin actions rejected
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "role": "moderator", "pin_or_code": "1111"})
        welcome = ws.receive_json()
        assert welcome["type"] == "welcome"
        ws.receive_json()  # consume initial state

        # Moderator attempts admin_adjust_score -> rejected
        ws.send_json({
            "type": "action",
            "action": "admin_adjust_score",
            "payload": {"team_id": "T01", "delta": 10}
        })
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "Permission denied" in err["message"]

        # Moderator opens question -> permitted!
        ws.send_json({"type": "action", "action": "open_question", "payload": {}})
        # State broadcast received
        state = ws.receive_json()
        assert state["type"] == "state"
        ack = ws.receive_json()
        assert ack["type"] == "action_ack"
        assert ack["success"] is True
