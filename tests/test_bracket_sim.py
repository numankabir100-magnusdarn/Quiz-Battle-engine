import pytest
from server.engine.game_engine import GameEngine
from server.engine.models import Stage


def test_full_14_match_bracket_simulation(clean_engine: GameEngine):
    """Simulates a complete 14-team tournament through all 14 matches:
    - 7 Qualifier matches (M1-M7): 14 teams -> 7 winners + Top-1 highest-scoring loser as Wild-Card (8 teams)
    - 4 Quarterfinals (M8-M11): 8 teams -> 4 winners
    - 2 Semifinals (M12-M13): 4 teams -> 2 winners
    - 1 Grand Final (M14): 2 teams -> 1 champion!
    """
    engine = clean_engine

    qual_plan = [
        (1, "T01", 50, "T02", 40),  # Loser T02 = 40 pts <-- Top-1 Wild-Card!
        (2, "T03", 30, "T04", 25),
        (3, "T05", 45, "T06", 35),
        (4, "T07", 60, "T08", 10),
        (5, "T09", 40, "T10", 20),
        (6, "T11", 55, "T12", 5),
        (7, "T13", 35, "T14", 15),
    ]

    for m_num, t_a, score_a, t_b, score_b in qual_plan:
        engine.setup_match(Stage.QUALIFIER.value, m_num, t_a, t_b)
        engine.admin_adjust_score(t_a, score_a, "Simulated score A")
        engine.admin_adjust_score(t_b, score_b, "Simulated score B")
        res = engine.end_match()
        assert res["status"] == "COMPLETED"
        assert res["winner_id"] == t_a

    # 7 winners + Top-1 wild card (T02)
    expected_winners = ["T01", "T03", "T05", "T07", "T09", "T11", "T13"]
    assert engine.bracket.qualifier_winners == expected_winners
    assert engine.bracket.wild_cards == ["T02"]

    # Quarterfinals M8-M11 are the official seeded matchups:
    # M8:  EE Royals (T01) vs Mastermind A (T04)
    # M9:  Two Braincells (T09) vs Tech Pro (T10)
    # M10: Roti Shoti (T08) vs Mastermind B (T06)
    # M11: Lumina (T12) vs Overthinkers (T07)
    expected_qfs = {
        8: ("T01", "T04"),
        9: ("T09", "T10"),
        10: ("T08", "T06"),
        11: ("T12", "T07"),
    }
    for m_num, (t_a, t_b) in expected_qfs.items():
        m = next(m for m in engine.bracket.matches if m.match_number == m_num)
        assert (m.team_a_id, m.team_b_id) == (t_a, t_b)

    qf_plan = [
        (8, "T01", 40, "T04", 20, "T01"),
        (9, "T09", 15, "T10", 30, "T10"),
        (10, "T08", 35, "T06", 15, "T08"),
        (11, "T12", 50, "T07", 45, "T12"),
    ]
    for m_num, t_a, score_a, t_b, score_b, expected_w in qf_plan:
        engine.setup_match(Stage.QUARTERFINAL.value, m_num, t_a, t_b)
        engine.admin_adjust_score(t_a, score_a, "QF score A")
        engine.admin_adjust_score(t_b, score_b, "QF score B")
        res = engine.end_match()
        assert res["status"] == "COMPLETED"
        assert res["winner_id"] == expected_w

    # Semifinals M12-M13:
    # M12: W(M8)=T01 vs W(M9)=T10
    # M13: W(M10)=T08 vs W(M11)=T12
    m12 = next(m for m in engine.bracket.matches if m.match_number == 12)
    m13 = next(m for m in engine.bracket.matches if m.match_number == 13)
    assert (m12.team_a_id, m12.team_b_id) == ("T01", "T10")
    assert (m13.team_a_id, m13.team_b_id) == ("T08", "T12")

    engine.setup_match(Stage.SEMIFINAL.value, 12, "T01", "T10")
    engine.admin_adjust_score("T01", 60)
    engine.admin_adjust_score("T10", 40)
    assert engine.end_match()["winner_id"] == "T01"

    engine.setup_match(Stage.SEMIFINAL.value, 13, "T08", "T12")
    engine.admin_adjust_score("T08", 30)
    engine.admin_adjust_score("T12", 45)
    assert engine.end_match()["winner_id"] == "T12"

    # Grand Final M14: T01 vs T12
    m14 = next(m for m in engine.bracket.matches if m.match_number == 14)
    assert (m14.team_a_id, m14.team_b_id) == ("T01", "T12")

    engine.setup_match(Stage.FINAL.value, 14, "T01", "T12")
    engine.admin_adjust_score("T01", 75, "Final score")
    engine.admin_adjust_score("T12", 60, "Final score")
    final_res = engine.end_match()

    assert final_res["status"] == "COMPLETED"
    assert final_res["winner_id"] == "T01"
    assert engine.bracket.champion == "T01"


def test_wild_card_tie_detection_and_resolution(clean_engine: GameEngine):
    """Tests that when multiple qualifier losers tie on score and buzzer points for Top-1,
    the engine flags wild_card_tied_teams and resolves via resolve_wild_card_tie."""
    engine = clean_engine
    qual_plan = [
        (1, "T01", 50, "T02", 30),  # Loser T02: 30 (tied)
        (2, "T03", 50, "T04", 30),  # Loser T04: 30 (tied)
        (3, "T05", 50, "T06", 20),
        (4, "T07", 50, "T08", 10),
        (5, "T09", 50, "T10", 5),
        (6, "T11", 50, "T12", 0),
        (7, "T13", 50, "T14", 0),
    ]
    for m_num, t_a, sa, t_b, sb in qual_plan:
        engine.setup_match(Stage.QUALIFIER.value, m_num, t_a, t_b)
        engine.admin_adjust_score(t_a, sa)
        engine.admin_adjust_score(t_b, sb)
        engine.end_match()

    assert set(engine.bracket.wild_card_tied_teams) == {"T02", "T04"}
    assert engine.bracket.wild_cards == []

    engine.resolve_wild_card_tie("T04")
    assert engine.bracket.wild_cards == ["T04"]
    assert engine.bracket.wild_card_tied_teams == []
    m8 = next(m for m in engine.bracket.matches if m.match_number == 8)
    assert m8.team_a_id == "T01" and m8.team_b_id == "T04"


def test_override_quarterfinal_pairings(clean_engine: GameEngine):
    """Verifies that an admin can manually override quarterfinal pairings (Matches 8-11)."""
    engine = clean_engine

    custom_pairings = [
        {"match_number": 8, "team_a_id": "T01", "team_b_id": "T14"},
        {"match_number": 9, "team_a_id": "T03", "team_b_id": "T12"},
        {"match_number": 10, "team_a_id": "T05", "team_b_id": "T10"},
        {"match_number": 11, "team_a_id": "T07", "team_b_id": "T09"},
    ]
    res = engine.override_quarterfinal_pairings(custom_pairings)
    assert res["status"] == "SUCCESS"

    m8 = next(m for m in engine.bracket.matches if m.match_number == 8)
    assert m8.team_a_id == "T01" and m8.team_b_id == "T14"

    with pytest.raises(ValueError, match="not a quarterfinal match"):
        engine.override_quarterfinal_pairings([{"match_number": 7, "team_a_id": "T01", "team_b_id": "T02"}])
