"""A-to-Z spec coverage: RF cap+undo, matrix isolation, buzz clear, pool reset, M14 CSV."""
from fastapi.testclient import TestClient
from server.main import app, engine


def fresh():
    engine.seed_official_14_teams()
    return engine


def test_rf_cap_and_undo_rollback():
    e = fresh()
    e.set_total_questions(10)  # pin cap to 10
    e.setup_match("Qualifier", 1, "T01", "T02")
    e.start_rapid_fire("T01", 120)
    for _ in range(10):
        e.open_question()
        e.mark_correct("T01")
    assert e.current_match.stats["T01"]["rf_attempted"] == 10
    assert e.current_match.scores["T01"] == 100
    try:
        e.open_question()
        e.mark_correct("T01")
        raise AssertionError("11th attempt should be rejected")
    except ValueError:
        pass
    e.undo_last_action()
    assert e.current_match.scores["T01"] == 90
    assert e.current_match.stats["T01"]["rf_attempted"] == 9
    assert e.current_match.stats["T01"]["questions_answered"] == 9


def test_matrix_isolation_and_q1_autopen():
    e = fresh()
    e.setup_match("Qualifier", 1, "T01", "T02")
    e.start_rapid_fire("T01", 120)
    assert e.team_a_matrix.current_question_num == 1
    assert e.team_b_matrix.current_question_num is None
    e.switch_turn(120)
    assert e.round.active_team_id == "T02"
    assert e.team_b_matrix.current_question_num == 1
    assert e.team_b_matrix.slot(1)["status"] == "active"


def test_buzz_clear_resets_state():
    e = fresh()
    e.setup_match("Qualifier", 1, "T01", "T02")
    e.start_buzzer_battle()
    e.buzz("T01", timestamp=1.0)
    assert e.buzzers.first_team == "T01" and e.buzzers.locked
    e.confirm_first_buzz("clear")
    assert e.buzzers.first_team is None
    assert e.buzzers.press_timestamp is None
    assert e.buzzers.locked is False
    assert e.buzzers.passed_to_team is None
    assert e.buzzers.attempted_teams == []


def test_set_total_questions_resets_pool():
    e = fresh()
    e.set_total_questions(20)
    assert e.used_question_numbers == []
    assert e.question_matrix.total_questions == 20


def test_section_score_separation_and_streak_reset():
    from server.engine.models import QuestionMatrixState
    e = fresh()
    e.setup_match("Qualifier", 1, "T01", "T02")
    e.start_rapid_fire("T01", 120)
    for _ in range(3):
        e.open_question(); e.mark_correct("T01")
    assert e.current_match.stats["T01"]["rapid_fire_points"] == 30
    assert e.current_match.scores["T01"] == 30
    e.start_buzzer_battle()
    # RF streak must not leak into Buzzer Battle telemetry
    assert e.telemetry()["current_streak"] == 0
    e.buzz("T01", timestamp=1.0)
    e.confirm_first_buzz("T01")
    e.mark_correct("T01")
    assert e.current_match.stats["T01"]["buzzer_points"] == 15
    assert e.current_match.stats["T01"]["rapid_fire_points"] == 30  # untouched
    assert e.current_match.scores["T01"] == 45  # match total = RF + BZ


def test_matrix_normalizes_to_configured_count():
    from server.engine.models import QuestionMatrixState
    bad_statuses = [
        {"num": n, "status": "won" if n in (4, 20) else "unasked", "winner_side": "A" if n == 4 else None}
        for n in range(1, 21)
    ]
    m = QuestionMatrixState.from_dict({"total_questions": 15, "statuses": bad_statuses})
    assert len(m.statuses) == 15
    assert [s["num"] for s in m.statuses] == list(range(1, 16))
    assert m.questions_remaining == 14  # only Q4 resolved
    assert m.team_a_correct == 1


def test_csv_export_includes_m14():
    client = TestClient(app)
    r = client.post("/api/admin/auth", json={"pin": "2222"})
    assert r.status_code == 200
    resp = client.get("/api/admin/report?format=csv", cookies=r.cookies)
    assert resp.status_code == 200
    assert "M14" in resp.text
    assert "SECTION 2" in resp.text


def test_rf_score_hit_matrix_consistency_15q():
    """15/15 RF: score, hits, ASKED/LEFT and per-team matrices stay consistent;
    no premature completion while slots remain unasked."""
    e = fresh()
    e.set_total_questions(15)
    e.setup_match("Qualifier", 1, "T01", "T02")
    e.start_rapid_fire("T01", 120)
    e._last_score_guard_at = 0.0
    for i in range(15):
        e.open_question()
        e._last_score_guard_at = 0.0
        res = e.mark_correct("T01")
        if i < 14:
            assert res.get("rf_complete") is not True, f"premature complete at {i+1}/15"
    st = e.get_state()
    qm = st["question_matrix"]
    sub = qm.get("team_a_matrix") or {}
    assert sub.get("team_a_correct") == 15
    assert qm.get("questions_remaining", 1) == 0
    assert e.current_match.stats["T01"]["rapid_fire_points"] == 150
    assert e.current_match.stats["T01"]["questions_answered"] == 15
