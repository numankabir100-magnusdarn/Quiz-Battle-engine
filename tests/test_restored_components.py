from starlette.testclient import TestClient

from server.fairness import calculate_latency_stats, compare_buzzer_latency
from server.main import app
from server.qr_service import get_role_urls, generate_qr_svg


def test_fairness_stats_are_descriptive_only():
    assert calculate_latency_stats([10, 20, 30])["average_ms"] == 20.0
    result = compare_buzzer_latency([10], [80])
    assert result["difference_ms"] == 70.0
    assert result["fair"] is False


def test_offline_role_urls_and_svg():
    urls = get_role_urls("192.168.1.8")
    assert urls["buzzer_a"]["url"].endswith("pairing=BUZZ_A")
    assert urls["buzzer_b"]["url"].endswith("pairing=BUZZ_B")
    svg = generate_qr_svg(urls["display"]["url"])
    assert svg.startswith("<svg ")
    assert "192.168.1.8" in svg


def test_buzzer_pages_are_separate_and_spoken_only():
    client = TestClient(app)
    buzzer_a = client.get("/buzzer/a")
    buzzer_b = client.get("/buzzer/b")
    assert buzzer_a.status_code == buzzer_b.status_code == 200
    assert 'data-role="buzzer_a"' in buzzer_a.text
    assert 'data-role="buzzer_b"' in buzzer_b.text
    assert "questionText" not in buzzer_a.text
    assert "questionText" not in buzzer_b.text


def test_hub_auth_qr_backup_and_restore_contract():
    client = TestClient(app)
    auth = client.post("/api/hub/auth", json={"pin": "3333"})
    assert auth.status_code == 200
    qr = client.get("/api/hub/qr")
    assert qr.status_code == 200
    assert "buzzer_a" in qr.json()["urls"]
    backup = client.get("/api/hub/backup")
    assert backup.status_code == 200
    assert "event" in backup.json()
    restored = client.post("/api/hub/restore", json={"state": backup.json()})
    assert restored.status_code == 200
