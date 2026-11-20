import pytest
import concurrent.futures
from server.engine.game_engine import GameEngine


def test_first_buzz_race_condition():
    """Simulates concurrent/simultaneous buzz calls across threads.
    Verifies that:
    1. Exactly one team is registered as first_team.
    2. Buzzers lock immediately.
    3. The losing buzz is rejected cleanly.
    4. Repeats multiple trials to ensure zero race window.
    """
    trials = 50

    for trial in range(trials):
        engine = GameEngine(auto_init_tournament=True)
        engine.setup_match("Qualifier", 1, "team_1", "team_2")
        engine.start_buzzer_battle()
        engine.open_question()

        results = []
        errors = []

        def attempt_buzz(team_id: str):
            try:
                res = engine.buzz(team_id)
                results.append((team_id, res))
            except ValueError as e:
                errors.append((team_id, str(e)))

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(attempt_buzz, "team_1")
            fut2 = executor.submit(attempt_buzz, "team_2")
            fut1.result()
            fut2.result()

        # Exactly ONE call must succeed
        assert len(results) == 1, f"Trial {trial}: Expected 1 success, got {len(results)}"
        # Exactly ONE call must fail with buzzer locked
        assert len(errors) == 1, f"Trial {trial}: Expected 1 error, got {len(errors)}"

        winning_team = results[0][0]
        losing_team = errors[0][0]
        assert winning_team in ("team_1", "team_2")
        assert losing_team in ("team_1", "team_2")
        assert winning_team != losing_team

        # Engine buzzers state integrity
        assert engine.buzzers.first_team == winning_team
        assert engine.buzzers.locked is True
