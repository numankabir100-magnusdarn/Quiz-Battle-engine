import json
import pytest
from server.engine.game_engine import GameEngine
from server.engine.models import RoundPhase, Stage
from server.persistence import PersistenceManager


def test_atomic_state_save_and_restore(temp_data_dir):
    """Simulates a mid-match crash and engine restart:
    1. Plays match moves (scores, phases, questions).
    2. Atomically persists state to state.json.
    3. Simulates crash by discarding engine instance.
    4. Restores new engine instance from state.json.
    5. Confirms state is 100% identical.
    """
    pm = PersistenceManager(data_dir=temp_data_dir)

    # 1. Initialize and play moves
    engine1 = GameEngine(auto_init_tournament=True)
    engine1.setup_match(Stage.QUALIFIER.value, 3, "team_5", "team_6")
    engine1.start_buzzer_battle()
    engine1.open_question()
    engine1.buzz("team_5")
    engine1.mark_correct()
    engine1.admin_adjust_score("team_6", 5, reason="Bonus point")

    # 2. Persist state
    state1 = engine1.get_state()
    pm.save_state(state1)

    # Confirm state.json exists and is valid JSON
    state_file = temp_data_dir / "state.json"
    assert state_file.exists()
    with open(state_file, "r", encoding="utf-8") as f:
        loaded_json = json.load(f)
    assert loaded_json["event"]["match_number"] == 3
    assert loaded_json["current_match"]["scores"]["team_5"] == 15
    assert loaded_json["current_match"]["scores"]["team_6"] == 5

    # 3. Discard engine1 ("crash") and create fresh engine2
    engine2 = GameEngine(auto_init_tournament=False)
    loaded_state = pm.load_state()
    assert loaded_state is not None
    engine2.restore_state(loaded_state)

    state2 = engine2.get_state()

    # Compare key state structures
    assert state2["event"]["stage"] == state1["event"]["stage"]
    assert state2["event"]["match_number"] == state1["event"]["match_number"]
    assert state2["current_match"]["team_a_id"] == "team_5"
    assert state2["current_match"]["team_b_id"] == "team_6"
    assert state2["current_match"]["scores"]["team_5"] == 15
    assert state2["current_match"]["scores"]["team_6"] == 5
    assert state2["round"]["phase"] == RoundPhase.BUZZER_BATTLE.value
    assert len(state2["log"]) == len(state1["log"]) + 1  # includes restore_state log


def test_audit_log_append(temp_data_dir):
    """Verifies that every action and score change is cleanly appended to audit.log."""
    pm = PersistenceManager(data_dir=temp_data_dir)

    pm.log_audit(
        role="moderator",
        device="laptop_mod",
        action="mark_correct",
        details={"team": "team_1", "points": 15},
        reason="buzzer answer confirmed",
    )
    pm.log_audit(
        role="admin",
        device="laptop_adm",
        action="admin_adjust_score",
        details={"team": "team_2", "delta": -5},
        reason="penalty for behavior",
    )

    audit_file = temp_data_dir / "audit.log"
    assert audit_file.exists()

    with open(audit_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 2
    assert "role=moderator" in lines[0]
    assert "device=laptop_mod" in lines[0]
    assert "action=mark_correct" in lines[0]
    assert 'reason="buzzer answer confirmed"' in lines[0]

    assert "role=admin" in lines[1]
    assert "action=admin_adjust_score" in lines[1]
    assert 'reason="penalty for behavior"' in lines[1]


def test_state_restore_always_pauses_timer(temp_data_dir):
    """Verifies requirement: On state restore, always restore the timer as paused.
    Even if the system crashed while the timer was running, the restored timer must be paused.
    """
    pm = PersistenceManager(data_dir=temp_data_dir)

    engine1 = GameEngine(auto_init_tournament=True)
    engine1.setup_match(Stage.QUALIFIER.value, 1, "team_1", "team_2")
    engine1.start_rapid_fire("team_1", 120)
    # Simulate timer actively running mid-match
    engine1.round.timer_running = True
    engine1.round.timer_seconds_remaining = 87

    # Save running state to disk
    pm.save_state(engine1.get_state())

    # Simulate restart & restore
    engine2 = GameEngine(auto_init_tournament=False)
    loaded_state = pm.load_state()
    assert loaded_state is not None
    engine2.restore_state(loaded_state)

    # Timer seconds preserved, but timer_running MUST be False
    assert engine2.round.timer_seconds_remaining == 87
    assert engine2.round.timer_running is False
