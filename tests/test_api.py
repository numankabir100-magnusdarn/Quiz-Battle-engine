from starlette.testclient import TestClient
from server.main import app


def test_rest_api_endpoints():
    """Tests all required REST endpoints: /api/state, /api/devices, /api/health, /api/network-info, /debug."""
    client = TestClient(app)

    # 1. GET /api/health
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    data_health = res_health.json()
    assert data_health["status"] == "ok"
    assert "uptime_seconds" in data_health
    assert data_health["version"] == "1.0.0"

    # 2. GET /api/state
    res_state = client.get("/api/state")
    assert res_state.status_code == 200
    data_state = res_state.json()
    assert "event" in data_state
    assert "teams" in data_state
    assert "round" in data_state
    assert "buzzers" in data_state
    assert "question" in data_state

    # 3. GET /api/devices
    res_dev = client.get("/api/devices")
    assert res_dev.status_code == 200
    data_dev = res_dev.json()
    assert "devices" in data_dev
    assert isinstance(data_dev["devices"], list)

    # 4. GET /api/network-info
    res_net = client.get("/api/network-info")
    assert res_net.status_code == 200
    data_net = res_net.json()
    assert "primary_ip" in data_net
    assert "all_ips" in data_net
    assert "base_url" in data_net
    assert "debug_url" in data_net
    assert "port" in data_net

    # 5. GET /debug
    res_debug = client.get("/debug")
    assert res_debug.status_code == 200
    assert "EEE Brain Battle" in res_debug.text
    assert "theme.css" in res_debug.text


def test_admin_and_display_pages_are_served_with_local_controller_assets():
    client = TestClient(app)
    admin = client.get("/admin")
    display = client.get("/display")
    assert admin.status_code == 200
    assert "Display Controller" in admin.text
    assert "/static/admin.js" in admin.text
    assert display.status_code == 200
    assert "/static/display.js" in display.text


def test_admin_display_controller_broadcasts_shared_view():
    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "hello", "role": "admin", "pin_or_code": "2222"})
        assert websocket.receive_json()["type"] == "welcome"
        assert websocket.receive_json()["type"] == "state"
        websocket.send_json({
            "type": "action",
            "action": "set_display_view",
            "payload": {"view": "bracket"},
            "reason": "Test projector control",
        })
        messages = [websocket.receive_json(), websocket.receive_json(), websocket.receive_json()]
        state_messages = [message for message in messages if message["type"] == "state"]
        assert state_messages
        assert state_messages[0]["data"]["display_view"] == "bracket"
        assert any(message["type"] == "action_ack" for message in messages)
    engine_state = client.get("/api/state").json()
    assert engine_state["display_view"] == "bracket"
