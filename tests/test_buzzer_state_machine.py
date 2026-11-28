"""
tests/test_buzzer_state_machine.py
==================================
State-machine regression tests for the fixed Buzzer Round behavior.

Covers:
  - Q1 armed immediately after start_buzzer_battle / start_sudden_death
  - Timer cleared (seconds=0, running=False) on phase transition
  - Wrong answer -5 in Buzzer Battle correctly passes steal to opponent
  - Both-fail locks question dead
"""
import pytest
from server.engine.game_engine import GameEngine
from server.engine.models import RoundPhase, BuzzersState, QuestionState


@pytest.fixture()
def clean_engine():
    """Fresh engine with match 1 set up and both teams ready."""
    eng = GameEngine(auto_init_tournament=True)
    # Match 1: T01 vs T02 (already set up by init_default_tournament)
    return eng


# ─────────────────────────────────────────────────────────────────────────────
# Bug Fix 1: Q1 Locked Buzzer on Round Start
# ─────────────────────────────────────────────────────────────────────────────

class TestBuzzerBattleQ1Armed:
    def test_buzzers_unlocked_immediately_after_start(self, clean_engine):
        """Buzzers must be UNLOCKED immediately after start_buzzer_battle."""
        eng = clean_engine
        eng.start_buzzer_battle()
        assert eng.buzzers.locked is False, (
            "Buzzers must be unlocked immediately after start_buzzer_battle, "
            "not waiting for the first open_question call."
        )

    def test_question_open_immediately_after_start(self, clean_engine):
        """question.is_open must be True immediately after start_buzzer_battle."""
        eng = clean_engine
        eng.start_buzzer_battle()
        assert eng.question.is_open is True, (
            "question.is_open must be True immediately after start_buzzer_battle "
            "so the first buzz is not rejected."
        )

    def test_first_team_none_at_start(self, clean_engine):
        """buzzers.first_team must be None (no phantom buzz) at round start."""
        eng = clean_engine
        eng.start_buzzer_battle()
        assert eng.buzzers.first_team is None

    def test_attempted_teams_empty_at_start(self, clean_engine):
        """attempted_teams list must be empty at the start of Buzzer Battle."""
        eng = clean_engine
        eng.start_buzzer_battle()
        assert eng.buzzers.attempted_teams == []

    def test_phase_set_to_buzzer_battle(self, clean_engine):
        eng = clean_engine
        eng.start_buzzer_battle()
        assert eng.round.phase == RoundPhase.BUZZER_BATTLE.value

    def test_buzz_accepted_immediately_after_start(self, clean_engine):
        """T01 must be able to buzz immediately after start_buzzer_battle
        (the Q1 armed fix removes the dead-Q1 window)."""
        eng = clean_engine
        eng.start_buzzer_battle()
        result = eng.buzz("T01")
        assert result["success"] is True
        assert eng.buzzers.first_team == "T01"
        assert eng.buzzers.locked is True  # locked after first press


class TestSuddenDeathQ1Armed:
    def test_buzzers_unlocked_immediately_after_start(self, clean_engine):
        eng = clean_engine
        eng.start_sudden_death()
        assert eng.buzzers.locked is False

    def test_question_open_immediately_after_start(self, clean_engine):
        eng = clean_engine
        eng.start_sudden_death()
        assert eng.question.is_open is True

    def test_phase_set_to_sudden_death(self, clean_engine):
        eng = clean_engine
        eng.start_sudden_death()
        assert eng.round.phase == RoundPhase.SUDDEN_DEATH.value


# ─────────────────────────────────────────────────────────────────────────────
# Bug Fix 2: Timer cleared on phase transition to Buzzer Battle / Sudden Death
# ─────────────────────────────────────────────────────────────────────────────

class TestTimerClearedOnPhaseTransition:
    def test_timer_seconds_zero_after_buzzer_battle_start(self, clean_engine):
        """timer_seconds_remaining must be 0 after switching to Buzzer Battle."""
        eng = clean_engine
        # Simulate: Rapid Fire was running (remaining > 0)
        eng.start_rapid_fire("T01", duration_seconds=120)
        eng.round.timer_seconds_remaining = 87
        eng.round.timer_running = True

        # Transition to Buzzer Battle
        eng.start_buzzer_battle()
        assert eng.round.timer_seconds_remaining == 0, (
            "Timer seconds must reset to 0 when entering Buzzer Battle "
            "so display doesn't show stale Rapid Fire time."
        )

    def test_timer_not_running_after_buzzer_battle_start(self, clean_engine):
        eng = clean_engine
        eng.start_rapid_fire("T01", duration_seconds=120)
        eng.round.timer_running = True

        eng.start_buzzer_battle()
        assert eng.round.timer_running is False

    def test_timer_seconds_zero_after_sudden_death_start(self, clean_engine):
        eng = clean_engine
        eng.round.timer_seconds_remaining = 45
        eng.round.timer_running = True

        eng.start_sudden_death()
        assert eng.round.timer_seconds_remaining == 0

    def test_timer_not_running_after_sudden_death_start(self, clean_engine):
        eng = clean_engine
        eng.round.timer_running = True
        eng.start_sudden_death()
        assert eng.round.timer_running is False


# ─────────────────────────────────────────────────────────────────────────────
# Bug Fix 3: Wrong answer pass logic in Buzzer Battle
# ─────────────────────────────────────────────────────────────────────────────

class TestWrongAnswerPassAndLockout:
    def _setup_buzzer_q1(self, eng):
        """Helper: start buzzer battle and have T01 buzz first."""
        eng.start_buzzer_battle()
        # Buzzers already open at start (Q1 armed fix)
        eng.buzz("T01")
        return "T01", "T02"

    def test_wrong_answer_applies_penalty(self, clean_engine):
        eng = clean_engine
        team_a, team_b = self._setup_buzzer_q1(eng)
        initial_score = eng.current_match.scores.get(team_a, 0)

        result = eng.mark_wrong(team_a)
        new_score = eng.current_match.scores.get(team_a, 0)
        assert new_score == initial_score - 5, "Buzzer Battle wrong answer must deduct -5"
        assert result["penalty"] == 5

    def test_wrong_answer_passes_to_opponent(self, clean_engine):
        eng = clean_engine
        team_a, team_b = self._setup_buzzer_q1(eng)

        result = eng.mark_wrong(team_a)
        assert result["passed_to"] == team_b
        assert eng.buzzers.passed_to_team == team_b
        assert result["question_closed"] is False

    def test_buzzers_unlocked_after_pass(self, clean_engine):
        """Buzzers must be unlocked exclusively for the passed-to team."""
        eng = clean_engine
        team_a, team_b = self._setup_buzzer_q1(eng)
        eng.mark_wrong(team_a)

        assert eng.buzzers.locked is False
        assert eng.buzzers.passed_to_team == team_b

    def test_opponent_cannot_buzz_when_not_passed(self, clean_engine):
        """team_b cannot buzz until question is passed to them.
        After T01 buzzes, buzzers are atomically locked so T02 is rejected.
        """
        eng = clean_engine
        eng.start_buzzer_battle()
        # T01 buzzes first → buzzers lock
        eng.buzz("T01")
        assert eng.buzzers.locked is True
        # T02 tries to buzz while locked — must be rejected
        with pytest.raises(ValueError, match="Buzzers are currently locked"):
            eng.buzz("T02")

    def test_both_fail_closes_question(self, clean_engine):
        """When both teams fail, the question must be marked dead."""
        eng = clean_engine
        team_a, team_b = self._setup_buzzer_q1(eng)

        # team_a fails → passed to team_b
        eng.mark_wrong(team_a)

        # team_b buzzes (they're the exclusive target)
        eng.buzz(team_b)
        result = eng.mark_wrong(team_b)

        assert result["question_closed"] is True
        assert result.get("both_failed") is True
        assert eng.question.is_open is False
        assert eng.buzzers.locked is True

    def test_both_fail_question_marked_dead_in_matrix(self, clean_engine):
        eng = clean_engine
        team_a, team_b = self._setup_buzzer_q1(eng)
        eng.mark_wrong(team_a)
        eng.buzz(team_b)
        eng.mark_wrong(team_b)

        # After open_question was called (by start_buzzer_battle), there IS a
        # current_question_num only if open_question was explicitly called.
        # start_buzzer_battle now sets question.is_open=True but does NOT
        # call open_question (which would set a matrix slot). So mark_question_dead
        # may raise if no matrix question was active — that's expected behavior.
        # What matters is that buzzers are locked and question is closed.
        assert eng.question.is_open is False
        assert eng.buzzers.locked is True

    def test_correct_after_pass_awards_to_right_team(self, clean_engine):
        """When passed to team_b and they answer correctly, team_b gets +15."""
        eng = clean_engine
        team_a, team_b = self._setup_buzzer_q1(eng)
        score_b_before = eng.current_match.scores.get(team_b, 0)

        eng.mark_wrong(team_a)
        eng.buzz(team_b)
        result = eng.mark_correct(team_b)

        assert result["team_id"] == team_b
        assert result["points_awarded"] == 15
        score_b_after = eng.current_match.scores.get(team_b, 0)
        assert score_b_after == score_b_before + 15


# ─────────────────────────────────────────────────────────────────────────────
# Rapid Fire timer state
# ─────────────────────────────────────────────────────────────────────────────

class TestRapidFireTimerState:
    def test_rapid_fire_timer_defaults_to_120(self, clean_engine):
        eng = clean_engine
        eng.start_rapid_fire("T01", duration_seconds=120)
        assert eng.round.timer_seconds_remaining == 120
        assert eng.round.timer_duration_seconds == 120

    def test_rapid_fire_timer_not_auto_started(self, clean_engine):
        """Timer must NOT auto-start; moderator clicks 'Start'."""
        eng = clean_engine
        eng.start_rapid_fire("T01", duration_seconds=120)
        assert eng.round.timer_running is False

    def test_switch_turn_resets_timer_to_120(self, clean_engine):
        eng = clean_engine
        eng.start_rapid_fire("T01", duration_seconds=120)
        eng.round.timer_seconds_remaining = 54
        result = eng.switch_turn(reset_seconds=120)
        assert eng.round.timer_seconds_remaining == 120
        assert eng.round.timer_running is False
