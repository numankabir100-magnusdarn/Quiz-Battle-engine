from pathlib import Path

from starlette.testclient import TestClient

from server.main import app


def test_moderator_cookie_session_authenticates_and_logs_out():
    client = TestClient(app)
    assert client.get("/api/moderator/session").json()["authenticated"] is False
    assert client.post("/api/moderator/auth", json={"pin": "0000"}).status_code == 401
    response = client.post("/api/moderator/auth", json={"pin": "1111"})
    assert response.status_code == 200
    assert "moderator_session" in response.cookies
    assert client.get("/api/moderator/session").json()["authenticated"] is True
    assert client.post("/api/moderator/logout").status_code == 200
    assert client.get("/api/moderator/session").json()["authenticated"] is False


def test_moderator_console_is_spoken_only_and_offline():
    root = Path(__file__).parents[1]
    html = (root / "web" / "moderator.html").read_text(encoding="utf-8")
    css = (root / "web" / "static" / "moderator.css").read_text(encoding="utf-8")
    javascript = (root / "web" / "static" / "moderator.js").read_text(encoding="utf-8")
    assert "Question text" not in html
    assert "Answer" not in html
    assert "http://" not in html + css + javascript
    assert 'data-action="undo_last_action"' in html
    assert 'data-action="configure_routing"' in html
