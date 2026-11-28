"""
tests/test_rapid_fire_cap.py
Verifies strict deterministic Rapid Fire scoring (10 hits = 100 pts, never 110),
10-question per-team cap, undo synchronization, and turn switch preservation.
"""
import time
import pytest
from server.engine.game_engine import GameEngine
from server.engine.models import RoundPhase


def test_rapid_fire_10_hits_equals_100_and_11th_rejected():
    engine = GameEngine(auto_init_tournament=True)
    engine.set_total_questions(10)  # pin cap to 10 for these tests
    engine.start_rapid_fire("T01", duration_seconds=120)
    engine._last_score_guard_at = 0.0  # bypass 150ms spam guard in fast unit test

    last_res = None
    for i in range(10):
        engine.open_question()
        engine._last_score_guard_at = 0.0
        last_res = engine.mark_correct("T01")
        assert last_res["points_awarded"] == 10
        assert last_res["new_score"] == (i + 1) * 10

    assert engine.current_match.scores["T01"] == 100
    assert engine.current_match.stats["T01"]["rapid_fire_points"] == 100
    assert engine.current_match.stats["T01"]["questions_answered"] == 10
    assert engine.current_match.stats["T01"]["rf_attempted"] == 10
    assert last_res.get("rf_complete") is True
    assert "10/10" in last_res.get("rf_message", "")
    assert engine.round.timer_running is False

    # 11th Rapid Fire attempt must be rejected/capped. With a 10-item matrix
    # the pool is also exhausted, so assert the cap guard directly.
    with pytest.raises(ValueError, match="COMPLETE \\(10/10"):
        engine._check_rf_cap("T01")
    assert engine.current_match.scores["T01"] == 100


def test_rapid_fire_undo_after_10_hits_restores_90_and_9():
    engine = GameEngine(auto_init_tournament=True)
    engine.set_total_questions(10)  # pin cap to 10 for these tests
    engine.start_rapid_fire("T01", duration_seconds=120)

    for _ in range(10):
        engine.open_question()
        engine._last_score_guard_at = 0.0
        engine.mark_correct("T01")

    assert engine.current_match.scores["T01"] == 100
    assert engine.current_match.stats["T01"]["rf_attempted"] == 10

    engine.undo_last_action()
    assert engine.current_match.scores["T01"] == 90
    assert engine.current_match.stats["T01"]["questions_answered"] == 9
    assert engine.current_match.stats["T01"]["rf_attempted"] == 9


def test_rapid_fire_switch_turn_preserves_team_a_score_and_resets_clock():
    engine = GameEngine(auto_init_tournament=True)
    engine.set_total_questions(10)  # pin cap to 10 for these tests
    engine.start_rapid_fire("T01", duration_seconds=120)

    for _ in range(10):
        engine.open_question()
        engine._last_score_guard_at = 0.0
        engine.mark_correct("T01")

    routing = engine.switch_turn(reset_seconds=120)
    assert routing["active_team_id"] == "T02"
    assert engine.round.timer_seconds_remaining == 120
    assert engine.round.timer_running is False
    assert engine.current_match.scores["T01"] == 100
    assert engine.current_match.stats["T01"]["rf_attempted"] == 10
    assert engine.round.phase == RoundPhase.RAPID_FIRE.value


def test_rapid_fire_15_questions_equals_150_with_15_item_matrix():
    """With Items: 15 the per-team RF cap syncs to 15 -> 150 max points."""
    engine = GameEngine(auto_init_tournament=True)
    engine.set_total_questions(15)
    engine.start_rapid_fire("T01", duration_seconds=120)
    engine._last_score_guard_at = 0.0

    last_res = None
    for i in range(15):
        engine.open_question()
        engine._last_score_guard_at = 0.0
        last_res = engine.mark_correct("T01")
        assert last_res["points_awarded"] == 10
        assert last_res["new_score"] == (i + 1) * 10

    assert engine.current_match.scores["T01"] == 150
    assert engine.current_match.stats["T01"]["rf_attempted"] == 15
    assert last_res.get("rf_complete") is True
    assert "15/15" in last_res.get("rf_message", "")

    # 16th attempt is rejected by the configured cap
    with pytest.raises(ValueError, match="COMPLETE \(15/15"):
        engine._check_rf_cap("T01")
