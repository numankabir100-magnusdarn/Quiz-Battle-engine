import json
from pathlib import Path

from server.engine.game_engine import GameEngine
from server.engine.models import Stage


EXACT_QUARTERFINALS = (
    (8, "T01", "T04", "EE Royals", "Mastermind A"),
    (9, "T09", "T10", "Two Braincells", "Tech Pro"),
    (10, "T08", "T06", "Roti Shoti", "Mastermind B"),
    (11, "T12", "T07", "Lumina", "Overthinkers"),
)


def _bracket_match(engine: GameEngine, match_number: int):
    return next(m for m in engine.bracket.matches if m.match_number == match_number)


def test_exact_quarterfinal_pairings_are_seeded(clean_engine: GameEngine):
    for m_num, t_a, t_b, name_a, name_b in EXACT_QUARTERFINALS:
        match = _bracket_match(clean_engine, m_num)
        assert match.stage == Stage.QUARTERFINAL.value
        assert (match.team_a_id, match.team_b_id) == (t_a, t_b)
        assert (clean_engine.teams[t_a].name, clean_engine.teams[t_b].name) == (name_a, name_b)
        assert match.status == "PENDING"


def test_exact_quarterfinal_pairings_survive_qualifier_progression(clean_engine: GameEngine):
    for m_num in range(1, 8):
        match = _bracket_match(clean_engine, m_num)
        clean_engine.setup_match(Stage.QUALIFIER.value, m_num, match.team_a_id, match.team_b_id)
        clean_engine.admin_adjust_score(match.team_a_id, 40, "regression qualifier")
        clean_engine.end_match()

    for m_num, t_a, t_b, _, _ in EXACT_QUARTERFINALS:
        match = _bracket_match(clean_engine, m_num)
        assert (match.team_a_id, match.team_b_id) == (t_a, t_b)


def test_exact_quarterfinal_winners_advance_to_semifinals_and_final(clean_engine: GameEngine):
    winners = {}
    for m_num, t_a, t_b, _, _ in EXACT_QUARTERFINALS:
        clean_engine.setup_match(Stage.QUARTERFINAL.value, m_num, t_a, t_b)
        clean_engine.admin_adjust_score(t_a, 30, "regression quarterfinal")
        result = clean_engine.end_match()
        assert result["winner_id"] == t_a
        winners[m_num] = t_a

    m12 = _bracket_match(clean_engine, 12)
    m13 = _bracket_match(clean_engine, 13)
    assert (m12.team_a_id, m12.team_b_id) == (winners[8], winners[9])
    assert (m13.team_a_id, m13.team_b_id) == (winners[10], winners[11])

    clean_engine.setup_match(Stage.SEMIFINAL.value, 12, m12.team_a_id, m12.team_b_id)
    clean_engine.admin_adjust_score(m12.team_a_id, 20, "regression semifinal")
    sf12_winner = clean_engine.end_match()["winner_id"]

    clean_engine.setup_match(Stage.SEMIFINAL.value, 13, m13.team_a_id, m13.team_b_id)
    clean_engine.admin_adjust_score(m13.team_a_id, 25, "regression semifinal")
    sf13_winner = clean_engine.end_match()["winner_id"]

    m14 = _bracket_match(clean_engine, 14)
    assert (m14.team_a_id, m14.team_b_id) == (sf12_winner, sf13_winner)

    clean_engine.setup_match(Stage.FINAL.value, 14, m14.team_a_id, m14.team_b_id)
    clean_engine.admin_adjust_score(m14.team_a_id, 35, "regression final")
    assert clean_engine.end_match()["winner_id"] == m14.team_a_id
    assert clean_engine.bracket.champion == m14.team_a_id


def test_tournament_progress_uses_exact_quarterfinal_names(clean_engine: GameEngine):
    for m_num in range(1, 8):
        match = _bracket_match(clean_engine, m_num)
        clean_engine.setup_match(Stage.QUALIFIER.value, m_num, match.team_a_id, match.team_b_id)
        clean_engine.admin_adjust_score(match.team_a_id, 40, "regression qualifier")
        clean_engine.end_match()

    progress = clean_engine.get_tournament_progress()
    next_match = progress["next_ready_match"]
    assert next_match["match_number"] == 8
    assert (next_match["team_a_name"], next_match["team_b_name"]) == ("EE Royals", "Mastermind A")
    names = {row["name"] for row in progress["standings"]}
    for _, _, _, name_a, name_b in EXACT_QUARTERFINALS:
        assert name_a in names
        assert name_b in names


def test_persisted_state_has_exact_quarterfinal_pairings():
    state_path = Path(__file__).resolve().parent.parent / "data" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    matches = {m["match_number"]: m for m in state["event"]["bracket"]["matches"]}
    names = {team["id"]: team["name"] for team in state["teams"].values()}

    for m_num, t_a, t_b, name_a, name_b in EXACT_QUARTERFINALS:
        match = matches[m_num]
        assert match["stage"] == Stage.QUARTERFINAL.value
        assert (match["team_a_id"], match["team_b_id"]) == (t_a, t_b)
        assert (names[t_a], names[t_b]) == (name_a, name_b)

    next_match = state["tournament_progress"]["next_ready_match"]
    assert (next_match["team_a_name"], next_match["team_b_name"]) == ("EE Royals", "Mastermind A")


def test_restored_pairings_survive_quarterfinal_result():
    state_path = Path(__file__).resolve().parent.parent / "data" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    engine = GameEngine(auto_init_tournament=False)
    engine.restore_state(state)

    engine.setup_match(Stage.QUARTERFINAL.value, 8, "T01", "T04")
    engine.admin_adjust_score("T01", 20, "regression restored quarterfinal")
    assert engine.advance_winner(8)["winner_id"] == "T01"

    for m_num, t_a, t_b, _, _ in EXACT_QUARTERFINALS:
        if m_num == 8:
            continue
        match = _bracket_match(engine, m_num)
        assert (match.team_a_id, match.team_b_id) == (t_a, t_b)
