import pytest
from server.engine.game_engine import GameEngine
from server.engine.models import RoundPhase, Stage


def test_initial_state(clean_engine: GameEngine):
    """Engine initializes with 12 teams, Qualifier stage, Match 1."""
    state = clean_engine.get_state()
    assert state["event"]["stage"] == Stage.QUALIFIER.value
    assert state["event"]["match_number"] == 1
    assert len(state["teams"]) == 14
    assert len(state["event"]["bracket"]["matches"]) == 14
    assert state["current_match"]["team_a_id"] == "T01"
    assert state["current_match"]["team_b_id"] == "T02"
    assert state["round"]["phase"] == RoundPhase.IDLE.value
    assert state["buzzers"]["locked"] is True


def test_display_view_controller_is_validated_and_serialized(clean_engine: GameEngine):
    engine = clean_engine
    assert engine.get_state()["display_view"] == "auto"
    assert engine.set_display_view("bracket") == {"view": "bracket"}
    assert engine.get_state()["display_view"] == "bracket"
    with pytest.raises(ValueError):
        engine.set_display_view("invalid")


def test_rapid_fire_scoring_rules(clean_engine: GameEngine):
    """Rapid Fire:
    - 120 seconds per team
    - +10 per correct answer
    - 0 for wrong or unanswered (no negative marking)
    - One designated speaker
    """
    engine = clean_engine
    team_a = "T01"
    team_b = "T02"

    engine.start_rapid_fire(team_id=team_a, duration_seconds=120)
    assert engine.round.phase == RoundPhase.RAPID_FIRE.value
    assert engine.round.active_team_id == team_a
    assert engine.round.timer_seconds_remaining == 120
    assert engine.buzzers.locked is True

    # Designated speaker is registered
    assert engine.teams[team_a].designated_speaker == "Syed Wajhee Ul Hassan"

    # Question 1: Correct (+10)
    engine.open_question()
    assert engine.question.is_open is True
    res_correct = engine.mark_correct()
    assert res_correct["points_awarded"] == 10
    assert res_correct["new_score"] == 10
    assert engine.current_match.scores[team_a] == 10
    assert engine.question.is_open is False

    # Question 2: Wrong (0 points, no negative marking)
    engine.open_question()
    res_wrong = engine.mark_wrong()
    assert res_wrong["penalty"] == 0
    assert engine.current_match.scores[team_a] == 10  # Score remains unchanged!

    # Rapid Fire for Team B
    engine.start_rapid_fire(team_id=team_b, duration_seconds=120)
    assert engine.round.active_team_id == team_b
    engine.open_question()
    engine.mark_correct()
    assert engine.current_match.scores[team_b] == 10


def test_buzzer_battle_scoring_and_pass_over(clean_engine: GameEngine):
    """Buzzer Battle:
    - +15 correct, -5 wrong
    - After wrong answer, passes to the OTHER team only, without being reread
    - If both fail, question closes
    """
    engine = clean_engine
    team_a = "T01"
    team_b = "T02"

    engine.start_buzzer_battle()
    assert engine.round.phase == RoundPhase.BUZZER_BATTLE.value

    # --- Scenario 1: Direct Correct (+15) ---
    engine.open_question()
    assert engine.buzzers.locked is False

    buzz_res = engine.buzz(team_a)
    assert buzz_res["success"] is True
    assert engine.buzzers.first_team == team_a
    assert engine.buzzers.locked is True  # Locks out all others!

    conf = engine.confirm_first_buzz()
    assert conf["confirmed_team"] == team_a

    mark_res = engine.mark_correct()
    assert mark_res["points_awarded"] == 15
    assert engine.current_match.scores[team_a] == 15
    assert engine.question.is_open is False


    # --- Scenario 2: Team A answers wrong (-5), passes to Team B who answers correctly (+15) ---
    engine.open_question()
    engine.buzz(team_a)
    wrong_res = engine.mark_wrong()

    assert wrong_res["penalty"] == 5
    assert wrong_res["passed_to"] == team_b
    assert wrong_res["question_closed"] is False
    assert engine.current_match.scores[team_a] == 10  # 15 - 5 = 10
    assert engine.buzzers.penalised_team == team_a
    assert engine.buzzers.passed_to_team == team_b
    assert engine.buzzers.locked is False  # Unlocked for Team B

    # Team A cannot buzz when question is passed to Team B!
    with pytest.raises(ValueError, match="passed exclusively to"):
        engine.buzz(team_a)

    # Team B answers correctly (+15)
    engine.buzz(team_b)
    pass_correct = engine.mark_correct()
    assert pass_correct["team_id"] == team_b
    assert pass_correct["points_awarded"] == 15
    assert engine.current_match.scores[team_b] == 15
    assert engine.question.is_open is False

    # --- Scenario 3: Both teams answer wrong, question closes ---
    engine.open_question()
    engine.buzz(team_a)
    w1 = engine.mark_wrong()
    assert w1["passed_to"] == team_b

    engine.buzz(team_b)
    w2 = engine.mark_wrong()
    assert w2["both_failed"] is True
    assert w2["question_closed"] is True
    assert engine.question.is_open is False
    assert engine.buzzers.locked is True


def test_server_arrival_order_locks_out_near_simultaneous_buzz(clean_engine: GameEngine):
    """The first valid server-handled buzz wins regardless of client timestamps."""
    engine = clean_engine
    engine.start_buzzer_battle()
    engine.open_question()

    first = engine.buzz("T02", timestamp=200.0)
    assert first["team_id"] == "T02"
    assert engine.buzzers.first_team == "T02"

    with pytest.raises(ValueError, match="Buzzers are currently locked"):
        engine.buzz("T01", timestamp=100.0)


def test_question_reveal_skip_and_previous_transitions(clean_engine: GameEngine):
    engine = clean_engine
    engine.start_buzzer_battle()

    engine.open_question()
    first_number = engine.question.current_question.number
    engine.reveal_answer()
    assert engine.question.revealed is True

    next_result = engine.next_question()
    assert next_result["question_number"] != first_number
    assert engine.question.revealed is False

    previous_result = engine.previous_question()
    assert previous_result["question_number"] == first_number
    assert engine.question.is_open is True


def test_moderator_can_override_first_buzz_team(clean_engine: GameEngine):
    engine = clean_engine
    engine.start_buzzer_battle()
    engine.open_question()
    engine.buzz("T01")

    result = engine.confirm_first_buzz("T02")
    assert result["confirmed_team"] == "T02"
    assert engine.buzzers.first_team == "T02"


def test_spoken_question_matrix_counters_and_team_colors(clean_engine: GameEngine):
    engine = clean_engine
    engine.set_total_questions(3)
    engine.start_buzzer_battle()
    engine.open_question()
    assert engine.question_matrix.to_dict()["statuses"][0]["status"] == "active"

    engine.buzz("T01")
    engine.mark_correct()
    matrix = engine.question_matrix.to_dict()
    assert matrix["questions_asked"] == 1
    assert matrix["questions_remaining"] == 2
    assert matrix["team_a_correct"] == 1
    assert matrix["statuses"][0]["winner_side"] == "A"
    assert engine.teams["T01"].accent_color == "#0ea5e9"
    assert engine.teams["T02"].accent_color == "#f97316"
    public_question = engine.get_state()["question"]["current_question"]
    assert "text" not in public_question
    assert "answer" not in public_question


def test_rapid_fire_keeps_explicit_turn_across_questions(clean_engine: GameEngine):
    """Block/auto-alternate routing removed: the active Rapid Fire team stays
    fixed until an explicit switch_turn — no per-question flipping."""
    engine = clean_engine
    engine.start_rapid_fire("T01")
    engine.set_total_questions(3)

    engine.open_question()
    assert engine.round.active_team_id == "T01"
    engine.mark_wrong()
    engine.open_question()
    assert engine.round.active_team_id == "T01"
    engine.mark_wrong()
    engine.open_question()
    assert engine.round.active_team_id == "T01"


def test_rapid_fire_switch_turn_moves_to_other_team(clean_engine: GameEngine):
    engine = clean_engine
    engine.start_rapid_fire("T01")
    engine.open_question()
    engine.mark_correct()
    engine.switch_turn(120)
    assert engine.round.active_team_id == "T02"
    engine.open_question()
    result = engine.mark_correct()
    assert result["team_id"] == "T02"
    assert engine.current_match.scores["T02"] == 10


def test_switch_turn_resets_timer(clean_engine: GameEngine):
    engine = clean_engine
    engine.start_rapid_fire("T01")
    engine.set_total_questions(20)

    engine.select_question(1)
    assert engine.round.active_team_id == "T01"
    engine.select_question(10)
    assert engine.round.active_team_id == "T01"
    engine.switch_turn(120)
    assert engine.round.active_team_id == "T02"
    engine.switch_turn(90)
    assert engine.round.active_team_id == "T01"
    assert engine.round.timer_seconds_remaining == 90


def test_undo_restores_score_matrix_and_counters(clean_engine: GameEngine):
    engine = clean_engine
    engine.start_rapid_fire("T01")
    engine.set_total_questions(3)
    engine.open_question()
    engine.mark_correct()
    assert engine.current_match.scores["T01"] == 10
    assert engine.question_matrix.questions_asked == 1

    result = engine.undo_last_action()
    assert result["undone"] == "mark_correct"
    assert engine.current_match.scores["T01"] == 0
    assert engine.question_matrix.questions_asked == 1
    assert engine.question_matrix.statuses[0]["status"] == "active"


def test_violation_warning_and_foul_penalty(clean_engine: GameEngine):
    engine = clean_engine
    warning = engine.apply_violation("T01", "No Mic")
    assert warning["penalty"] == 0
    engine.apply_violation("T01", "Audience Coaching", penalty=5)
    assert engine.current_match.scores["T01"] == -5
    assert engine.log[-1].action == "foul_penalty"


def test_first_buzz_locks_and_arrival_order(clean_engine: GameEngine):
    """First buzz locks buzzers; second buzz is rejected."""
    engine = clean_engine
    engine.start_buzzer_battle()
    engine.open_question()

    res1 = engine.buzz("T01", timestamp=100.0)
    assert res1["success"] is True
    assert engine.buzzers.first_team == "T01"
    assert engine.buzzers.locked is True

    # Second buzz should be rejected because buzzers are locked
    with pytest.raises(ValueError, match="locked"):
        engine.buzz("T02", timestamp=100.1)


def test_sudden_death_on_tie(clean_engine: GameEngine):
    """Tie at match end triggers SUDDEN_DEATH with buzzer questions;
    first correct answer wins immediately.
    """
    engine = clean_engine
    team_a = "T01"
    team_b = "T02"

    # Both teams tied at 0
    end_res = engine.end_match()
    assert end_res["status"] == "TIED"
    assert engine.round.phase == RoundPhase.SUDDEN_DEATH.value

    # Open Sudden Death buzzer question
    engine.open_question()
    assert engine.buzzers.locked is False

    # Team B buzzes and answers correctly
    engine.buzz(team_b)
    correct_res = engine.mark_correct()

    # Team B wins immediately!
    assert correct_res["sudden_death_winner"] == team_b
    assert engine.current_match.winner_id == team_b
    assert engine.current_match.loser_id == team_a
    assert engine.current_match.status == "COMPLETED"
    assert engine.round.phase == RoundPhase.RESULT.value
    assert engine.teams[team_b].win_loss["wins"] == 1
    assert engine.teams[team_a].win_loss["losses"] == 1


def test_admin_adjust_score(clean_engine: GameEngine):
    """Admin score adjustment can add or deduct points with audit reason."""
    engine = clean_engine
    adj_pos = engine.admin_adjust_score("T01", delta=10, reason="Technical glitch compensation")
    assert adj_pos["new_score"] == 10
    assert engine.current_match.scores["T01"] == 10

    adj_neg = engine.admin_adjust_score("T01", delta=-5, reason="Rule violation penalty")
    assert adj_neg["new_score"] == 5
    assert engine.current_match.scores["T01"] == 5


def test_invalid_action_rejections(clean_engine: GameEngine):
    """Engine cleanly rejects invalid actions with descriptive errors."""
    engine = clean_engine

    # Marking answer when no question is open
    with pytest.raises(ValueError, match="No open question"):
        engine.mark_correct()

    with pytest.raises(ValueError, match="No open question"):
        engine.mark_wrong()

    # Buzzing when in IDLE phase
    with pytest.raises(ValueError, match="No question is currently open"):
        engine.buzz("T01")

    # Buzzing during Rapid Fire
    engine.start_rapid_fire("T01", 120)
    engine.open_question()
    with pytest.raises(ValueError, match="not allowed during phase 'RAPID_FIRE'"):
        engine.buzz("T01")

    # Buzzing team not in current match
    engine.start_buzzer_battle()
    engine.open_question()
    with pytest.raises(ValueError, match="not in current match"):
        engine.buzz("T12")

    # Revealing answer when no question active
    engine.question.current_question = None
    with pytest.raises(ValueError, match="No question currently active"):
        engine.reveal_answer()

    # Confirming first buzz when no buzz occurred
    with pytest.raises(ValueError, match="No team has buzzed"):
        engine.confirm_first_buzz()


def test_question_tracking_no_repeats_and_warning(clean_engine: GameEngine):
    """Verifies that:
    1. Questions are tracked and never repeated across the event.
    2. When the bank is nearly empty (<= 2 left), a warning is issued to the moderator.
    3. When the bank is exhausted, ValueError is raised instead of wrapping around.
    """
    engine = clean_engine
    opened_numbers = []

    # Total questions in SampleQuestionProvider is 5
    total = engine.question_provider.count()
    assert total == 5

    # Question 1 (4 remaining, no warning)
    res1 = engine.open_question()
    opened_numbers.append(engine.question.current_question.number)
    assert engine.question_bank_warning is None
    engine.mark_correct("T01")

    # Question 2 (3 remaining, no warning)
    res2 = engine.open_question()
    opened_numbers.append(engine.question.current_question.number)
    assert engine.question_bank_warning is None
    engine.mark_correct("T01")

    # Question 3 (2 remaining -> warning triggered!)
    res3 = engine.open_question()
    opened_numbers.append(engine.question.current_question.number)
    assert engine.question_bank_warning is not None
    assert "nearly empty" in engine.question_bank_warning
    assert "2 question(s) remaining" in engine.question_bank_warning
    engine.mark_correct("T01")

    # Question 4 (1 remaining -> warning continues)
    res4 = engine.open_question()
    opened_numbers.append(engine.question.current_question.number)
    assert engine.question_bank_warning is not None
    assert "1 question(s) remaining" in engine.question_bank_warning
    engine.mark_correct("T01")

    # Question 5 (0 remaining -> warning continues)
    res5 = engine.open_question()
    opened_numbers.append(engine.question.current_question.number)
    assert engine.question_bank_warning is not None
    assert "0 question(s) remaining" in engine.question_bank_warning
    engine.mark_correct("T01")

    # All 5 opened numbers must be unique
    assert len(set(opened_numbers)) == 5
    assert set(opened_numbers) == {1, 2, 3, 4, 5}

    # Attempting to open 6th question must raise ValueError (NEVER wraps around!)
    with pytest.raises(ValueError, match="Question bank exhausted"):
        engine.open_question()


def test_rapid_fire_five_hits_each_exact_fifty(clean_engine: GameEngine):
    engine = clean_engine
    team_a = "T01"
    team_b = "T02"

    engine.start_rapid_fire(team_a, duration_seconds=120)
    for _ in range(5):
        engine.open_question()
        result = engine.mark_correct(team_a)
        assert result["points_awarded"] == 10

    engine.start_rapid_fire(team_b, duration_seconds=120)
    for _ in range(5):
        engine.open_question()
        result = engine.mark_correct(team_b)
        assert result["points_awarded"] == 10

    assert engine.current_match.scores[team_a] == 50
    assert engine.current_match.scores[team_b] == 50
    assert engine.question_matrix.team_a_correct == 5
    assert engine.question_matrix.team_b_correct == 5


def test_score_action_duplicate_within_150ms_is_ignored(clean_engine: GameEngine):
    engine = clean_engine
    engine.start_rapid_fire("T01", duration_seconds=120)
    engine.open_question()

    first = engine.mark_correct("T01")
    duplicate = engine.mark_correct("T01")

    assert first["points_awarded"] == 10
    assert duplicate["duplicate"] is True
    assert engine.current_match.scores["T01"] == 10


def test_setup_match_zeroes_stale_scores_hits_and_streak(clean_engine: GameEngine):
    engine = clean_engine
    engine.admin_adjust_score("T01", 70, "stale score")
    engine.start_rapid_fire("T01", duration_seconds=120)
    engine.open_question()
    engine.mark_correct("T01")
    assert engine.current_match.scores["T01"] == 80
    assert engine.question_matrix.team_a_correct == 1

    engine.setup_match(Stage.QUALIFIER.value, 1, "T01", "T02")

    assert engine.current_match.scores == {"T01": 0, "T02": 0}
    assert engine.question_matrix.team_a_correct == 0
    assert engine.question_matrix.team_b_correct == 0
    assert engine.telemetry()["current_streak"] == 0


def test_mark_correct_then_next_question_advances_exactly_one(clean_engine: GameEngine):
    engine = clean_engine
    engine.set_total_questions(5)
    engine.start_buzzer_battle()
    matrix = engine._cur_matrix()
    assert matrix.current_question_num == 1

    engine.buzz("T01")
    result = engine.mark_correct("T01")

    assert result["status"] == "CORRECT"
    assert matrix.current_question_num == 1
    assert matrix.slot(1)["status"] == "won"

    advanced = engine.next_question()
    assert advanced["question_number"] == 2
    assert matrix.current_question_num == 2
    assert engine.question.current_question.number == 2
    assert matrix.slot(1)["status"] == "won"
    assert matrix.slot(2)["status"] == "active"
    assert matrix.slot(3)["status"] == "unasked"

    duplicate = engine.next_question()
    assert duplicate["duplicate"] is True
    assert matrix.current_question_num == 2
    assert matrix.slot(3)["status"] == "unasked"


def test_rapid_fire_scoring_and_next_advances_one_slot_per_cycle(clean_engine: GameEngine, monkeypatch):
    engine = clean_engine
    engine.set_total_questions(5)
    engine.start_rapid_fire("T01")
    engine.open_question()
    matrix = engine._cur_matrix()
    assert matrix.current_question_num == 1

    for expected in (2, 3):
        engine.mark_correct("T01")
        assert matrix.current_question_num == expected - 1
        monkeypatch.setattr(engine, "_last_next_question_at", 0.0)
        assert engine.next_question()["question_number"] == expected
        assert matrix.current_question_num == expected
        assert matrix.slot(expected)["status"] == "active"
        assert matrix.slot(expected + 1)["status"] == "unasked"


def test_rapid_fire_telemetry_does_not_bleed_into_buzzer_battle(clean_engine: GameEngine):
    engine = clean_engine
    engine.set_total_questions(5)
    engine.start_rapid_fire("T01")
    engine.open_question()
    engine.mark_correct("T01")

    assert engine.telemetry()["current_streak"] == 1

    engine.start_buzzer_battle()
    telemetry = engine.telemetry()
    assert telemetry["average_seconds_per_question"] == 0.0
    assert telemetry["current_streak"] == 0


def test_rapid_fire_display_matrix_counts_distinct_slots(clean_engine: GameEngine, monkeypatch):
    engine = clean_engine
    engine.set_total_questions(5)
    engine.start_rapid_fire("T01")
    engine.mark_correct("T01")

    monkeypatch.setattr(engine, "_last_next_question_at", 0.0)
    engine.next_question()
    engine.mark_wrong("T01")

    engine.switch_turn(120)
    engine.start_rapid_fire("T02", 120)

    displayed = engine.question_matrix
    assert displayed.total_questions == 5
    assert len(displayed.statuses) == 5
    assert displayed.questions_asked == 2
    assert displayed.questions_remaining == 3
    assert displayed.team_a_correct == 1
    assert displayed.team_b_correct == 0


def test_skip_question_closes_current_slot_and_advances_one(clean_engine: GameEngine):
    engine = clean_engine
    engine.set_total_questions(5)
    engine.start_buzzer_battle()

    result = engine.skip_question()
    matrix = engine._cur_matrix()

    assert result["question_number"] == 2
    assert matrix.current_question_num == 2
    assert matrix.slot(1)["status"] == "dead"
    assert matrix.slot(2)["status"] == "active"
    assert matrix.slot(3)["status"] == "unasked"
    assert matrix.questions_asked == 2
    assert matrix.questions_remaining == 3


def test_redo_question_rolls_back_rapid_fire_wrong_attempt(clean_engine: GameEngine):
    engine = clean_engine
    engine.set_total_questions(5)
    engine.start_rapid_fire("T01")
    engine.mark_wrong("T01")

    stats = engine.current_match.stats["T01"]
    assert stats["rf_attempted"] == 1
    assert stats["questions_answered"] == 1
    assert stats["rapid_fire_points"] == 0
    assert len(engine._rapid_fire_durations) == 1

    result = engine.redo_question()
    stats = engine.current_match.stats["T01"]

    assert result["redone"] is True
    assert stats["rf_attempted"] == 0
    assert stats["questions_answered"] == 0
    assert engine.current_match.scores["T01"] == 0
    assert engine._rapid_fire_durations == []
    assert engine._cur_matrix().slot(1)["status"] == "active"
    assert engine.buzzers.locked is True


def test_restore_normalizes_stale_independent_matrix(clean_engine: GameEngine):
    import copy

    engine = clean_engine
    engine.set_total_questions(5)
    state = copy.deepcopy(engine.get_state())
    state["question_matrices"]["team_a"]["total_questions"] = 3
    state["question_matrices"]["team_a"]["statuses"] = state["question_matrices"]["team_a"]["statuses"][:3]

    engine.restore_state(state)

    assert engine.question_matrix.total_questions == 5
    assert engine.team_a_matrix.total_questions == 5
    assert len(engine.team_a_matrix.statuses) == 5
    assert engine.team_b_matrix.total_questions == 5
    assert engine.buzzer_matrix.total_questions == 5


def test_server_runtime_uses_isolated_paths():
    import os
    from pathlib import Path

    from server import main as server_main

    assert server_main.persistence.data_dir.resolve() == Path(os.environ["DATA_DIR"]).resolve()
    assert server_main.persistence.logs_dir.resolve() == Path(os.environ["LOGS_DIR"]).resolve()
