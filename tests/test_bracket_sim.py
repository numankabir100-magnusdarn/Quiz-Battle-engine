import pytest
from server.engine.game_engine import GameEngine
from server.engine.models import Stage


def test_full_13_match_bracket_simulation(clean_engine: GameEngine):
    """Simulates a complete tournament through all 13 matches:
    - 6 Qualifier matches: 12 teams -> 6 winners + 2 highest-scoring losers as wildcards (8 teams)
    - 4 Quarterfinals: 8 teams -> 4 winners
    - 2 Semifinals: 4 teams -> 2 winners
    - 1 Final: 2 teams -> 1 champion!
    """
    engine = clean_engine

    # -------------------------------------------------------------------------
    # Stage 1: Qualifiers (Matches 1 to 6)
    # -------------------------------------------------------------------------
    # We will configure deliberate scores for losers to verify wildcard ranking:
    # Match 1: Team 1 (50) vs Team 2 (40) -> Winner: Team 1, Loser: Team 2 (40 pts)  <-- WC Candidate
    # Match 2: Team 3 (30) vs Team 4 (25) -> Winner: Team 3, Loser: Team 4 (25 pts)
    # Match 3: Team 5 (45) vs Team 6 (35) -> Winner: Team 5, Loser: Team 6 (35 pts)  <-- WC Candidate
    # Match 4: Team 7 (60) vs Team 8 (10) -> Winner: Team 7, Loser: Team 8 (10 pts)
    # Match 5: Team 9 (40) vs Team 10 (20)-> Winner: Team 9, Loser: Team 10 (20 pts)
    # Match 6: Team 11 (55) vs Team 12 (5)-> Winner: Team 11, Loser: Team 12 (5 pts)
    #
    # Losers ranked by score:
    # 1. Team 2: 40 pts  --> Wild Card 1!
    # 2. Team 6: 35 pts  --> Wild Card 2!
    # 3. Team 4: 25 pts
    # 4. Team 10: 20 pts
    # 5. Team 8: 10 pts
    # 6. Team 12: 5 pts

    qual_plan = [
        (1, "team_1", 50, "team_2", 40),
        (2, "team_3", 30, "team_4", 25),
        (3, "team_5", 45, "team_6", 35),
        (4, "team_7", 60, "team_8", 10),
        (5, "team_9", 40, "team_10", 20),
        (6, "team_11", 55, "team_12", 5),
    ]

    for m_num, t_a, score_a, t_b, score_b in qual_plan:
        engine.setup_match(Stage.QUALIFIER.value, m_num, t_a, t_b)
        engine.admin_adjust_score(t_a, score_a, "Simulated score A")
        engine.admin_adjust_score(t_b, score_b, "Simulated score B")
        res = engine.end_match()
        assert res["status"] == "COMPLETED"
        assert res["winner_id"] == t_a

    # Check Qualifiers results: 6 winners and 2 wild cards
    expected_winners = ["team_1", "team_3", "team_5", "team_7", "team_9", "team_11"]
    assert engine.bracket.qualifier_winners == expected_winners
    assert engine.bracket.wild_cards == ["team_2", "team_6"]

    # -------------------------------------------------------------------------
    # Stage 2: Quarterfinals (Matches 7 to 10)
    # -------------------------------------------------------------------------
    # Pairings:
    # Match 7:  W1 (team_1)  vs WC2 (team_6)
    # Match 8:  W2 (team_3)  vs W5  (team_9)
    # Match 9:  W3 (team_5)  vs WC1 (team_2)
    # Match 10: W4 (team_7)  vs W6  (team_11)

    m7 = next(m for m in engine.bracket.matches if m.match_number == 7)
    assert m7.team_a_id == "team_1"
    assert m7.team_b_id == "team_6"

    m8 = next(m for m in engine.bracket.matches if m.match_number == 8)
    assert m8.team_a_id == "team_3"
    assert m8.team_b_id == "team_9"

    m9 = next(m for m in engine.bracket.matches if m.match_number == 9)
    assert m9.team_a_id == "team_5"
    assert m9.team_b_id == "team_2"

    m10 = next(m for m in engine.bracket.matches if m.match_number == 10)
    assert m10.team_a_id == "team_7"
    assert m10.team_b_id == "team_11"

    # Play Quarterfinals:
    # M7: team_1 (40) vs team_6 (20) -> Winner: team_1
    # M8: team_3 (15) vs team_9 (30) -> Winner: team_9
    # M9: team_5 (35) vs team_2 (15) -> Winner: team_5
    # M10: team_7 (50) vs team_11 (45) -> Winner: team_7
    qf_plan = [
        (7, "team_1", 40, "team_6", 20, "team_1"),
        (8, "team_3", 15, "team_9", 30, "team_9"),
        (9, "team_5", 35, "team_2", 15, "team_5"),
        (10, "team_7", 50, "team_11", 45, "team_7"),
    ]

    for m_num, t_a, score_a, t_b, score_b, expected_w in qf_plan:
        engine.setup_match(Stage.QUARTERFINAL.value, m_num, t_a, t_b)
        engine.admin_adjust_score(t_a, score_a, "QF score A")
        engine.admin_adjust_score(t_b, score_b, "QF score B")
        res = engine.end_match()
        assert res["status"] == "COMPLETED"
        assert res["winner_id"] == expected_w

    # -------------------------------------------------------------------------
    # Stage 3: Semifinals (Matches 11 and 12)
    # -------------------------------------------------------------------------
    # M11: Winner M7 (team_1) vs Winner M8 (team_9)
    # M12: Winner M9 (team_5) vs Winner M10 (team_7)
    m11 = next(m for m in engine.bracket.matches if m.match_number == 11)
    assert m11.team_a_id == "team_1"
    assert m11.team_b_id == "team_9"

    m12 = next(m for m in engine.bracket.matches if m.match_number == 12)
    assert m12.team_a_id == "team_5"
    assert m12.team_b_id == "team_7"

    # Play Semifinals:
    # M11: team_1 (60) vs team_9 (40) -> Winner: team_1
    # M12: team_5 (30) vs team_7 (45) -> Winner: team_7
    engine.setup_match(Stage.SEMIFINAL.value, 11, "team_1", "team_9")
    engine.admin_adjust_score("team_1", 60)
    engine.admin_adjust_score("team_9", 40)
    assert engine.end_match()["winner_id"] == "team_1"

    engine.setup_match(Stage.SEMIFINAL.value, 12, "team_5", "team_7")
    engine.admin_adjust_score("team_5", 30)
    engine.admin_adjust_score("team_7", 45)
    assert engine.end_match()["winner_id"] == "team_7"

    # -------------------------------------------------------------------------
    # Stage 4: Final (Match 13)
    # -------------------------------------------------------------------------
    # M13: Winner M11 (team_1) vs Winner M12 (team_7)
    m13 = next(m for m in engine.bracket.matches if m.match_number == 13)
    assert m13.team_a_id == "team_1"
    assert m13.team_b_id == "team_7"

    engine.setup_match(Stage.FINAL.value, 13, "team_1", "team_7")
    engine.admin_adjust_score("team_1", 75, "Final score")
    engine.admin_adjust_score("team_7", 60, "Final score")
    final_res = engine.end_match()

    assert final_res["status"] == "COMPLETED"
    assert final_res["winner_id"] == "team_1"
    assert engine.bracket.champion == "team_1"


def test_wild_card_tie_resolution(clean_engine: GameEngine):
    """Tests wild card tie scenario where 2nd and 3rd losers tie in scores.
    Rule: "a wild-card tie is resolved by a sudden-death question."
    """
    engine = clean_engine

    # Matches 1-6 setup where Loser 2 and Loser 3 tie at 30 pts:
    # M1: team_1 (50) vs team_2 (40)  -> Loser team_2: 40 pts (clear WC 1)
    # M2: team_3 (40) vs team_4 (30)  -> Loser team_4: 30 pts (tied!)
    # M3: team_5 (40) vs team_6 (30)  -> Loser team_6: 30 pts (tied!)
    # M4: team_7 (50) vs team_8 (10)  -> Loser team_8: 10 pts
    # M5: team_9 (50) vs team_10 (15) -> Loser team_10: 15 pts
    # M6: team_11 (50) vs team_12 (5) -> Loser team_12: 5 pts

    qual_plan = [
        (1, "team_1", 50, "team_2", 40),
        (2, "team_3", 40, "team_4", 30),
        (3, "team_5", 40, "team_6", 30),
        (4, "team_7", 50, "team_8", 10),
        (5, "team_9", 50, "team_10", 15),
        (6, "team_11", 50, "team_12", 5),
    ]

    for m_num, t_a, score_a, t_b, score_b in qual_plan:
        engine.setup_match(Stage.QUALIFIER.value, m_num, t_a, t_b)
        engine.admin_adjust_score(t_a, score_a)
        engine.admin_adjust_score(t_b, score_b)
        engine.end_match()

    # Wild card 1 is team_2 (40 pts)
    assert engine.bracket.wild_cards == ["team_2"]
    # Tied teams for wild card 2: team_4 and team_6 (30 pts each)
    assert set(engine.bracket.wild_card_tied_teams) == {"team_4", "team_6"}

    # Sudden death question played between team_4 and team_6; team_4 wins!
    engine.resolve_wild_card_tie(winning_team_id="team_4")

    # Now both wild cards are set and tie is cleared!
    assert engine.bracket.wild_cards == ["team_2", "team_4"]
    assert engine.bracket.wild_card_tied_teams == []

    # Quarterfinals are now populated
    m7 = next(m for m in engine.bracket.matches if m.match_number == 7)
    assert m7.team_a_id is not None and m7.team_b_id is not None


def test_override_quarterfinal_pairings(clean_engine: GameEngine):
    """Verifies that an admin can manually set or override quarterfinal pairings."""
    engine = clean_engine

    custom_pairings = [
        {"match_number": 7, "team_a_id": "team_1", "team_b_id": "team_12"},
        {"match_number": 8, "team_a_id": "team_3", "team_b_id": "team_10"},
        {"match_number": 9, "team_a_id": "team_5", "team_b_id": "team_8"},
        {"match_number": 10, "team_a_id": "team_7", "team_b_id": "team_2"},
    ]

    res = engine.override_quarterfinal_pairings(custom_pairings)
    assert res["status"] == "SUCCESS"

    m7 = next(m for m in engine.bracket.matches if m.match_number == 7)
    assert m7.team_a_id == "team_1"
    assert m7.team_b_id == "team_12"
    assert m7.status == "PENDING"
    assert m7.scores == {"team_1": 0, "team_12": 0}

    m10 = next(m for m in engine.bracket.matches if m.match_number == 10)
    assert m10.team_a_id == "team_7"
    assert m10.team_b_id == "team_2"

    # Validation: duplicate team across matches
    with pytest.raises(ValueError, match="appears in multiple quarterfinal matches"):
        engine.override_quarterfinal_pairings([
            {"match_number": 7, "team_a_id": "team_1", "team_b_id": "team_2"},
            {"match_number": 8, "team_a_id": "team_1", "team_b_id": "team_4"},
        ])

    # Validation: invalid match number
    with pytest.raises(ValueError, match="not a quarterfinal match"):
        engine.override_quarterfinal_pairings([
            {"match_number": 6, "team_a_id": "team_1", "team_b_id": "team_2"},
        ])

    # Validation: invalid team
    with pytest.raises(ValueError, match="Invalid or missing team"):
        engine.override_quarterfinal_pairings([
            {"match_number": 7, "team_a_id": "ghost_team", "team_b_id": "team_2"},
        ])


def test_regression_qualifier_reevaluation_does_not_reset_later_stages(clean_engine: GameEngine):
    """Regression test for bracket bug:
    Qualifier re-evaluation in _check_bracket_progression must NOT re-populate
    or reset later-stage matches (quarterfinals/semifinals) back to PENDING.
    """
    engine = clean_engine

    # Step 1: Complete all 6 qualifier matches
    for m in range(1, 7):
        t_a = f"team_{2*m - 1}"
        t_b = f"team_{2*m}"
        engine.setup_match(Stage.QUALIFIER.value, m, t_a, t_b)
        engine.admin_adjust_score(t_a, 40)
        engine.admin_adjust_score(t_b, 10 + m)
        engine.end_match()

    # Qualifiers completed and QF matches populated
    assert len(engine.bracket.qualifier_winners) == 6
    assert len(engine.bracket.wild_cards) == 2

    m7 = next(m for m in engine.bracket.matches if m.match_number == 7)
    qf7_ta, qf7_tb = m7.team_a_id, m7.team_b_id
    assert qf7_ta is not None and qf7_tb is not None

    # Step 2: Play and complete QF Match 7
    engine.setup_match(Stage.QUARTERFINAL.value, 7, qf7_ta, qf7_tb)
    engine.admin_adjust_score(qf7_ta, 35)
    engine.admin_adjust_score(qf7_tb, 15)
    res_m7 = engine.end_match()
    assert res_m7["status"] == "COMPLETED"
    assert res_m7["winner_id"] == qf7_ta

    # Verify Match 7 is COMPLETED
    assert m7.status == "COMPLETED"
    assert m7.winner_id == qf7_ta

    # Step 3: Trigger bracket progression check multiple times
    engine._check_bracket_progression()
    engine._check_bracket_progression()

    # CRITICAL ASSERTION: Match 7 MUST NOT be reset to PENDING by qualifier re-evaluation!
    assert m7.status == "COMPLETED"
    assert m7.winner_id == qf7_ta
    assert m7.scores[qf7_ta] == 35

    # Step 4: Complete remaining QF matches 8, 9, 10
    for m_num in (8, 9, 10):
        m_data = next(m for m in engine.bracket.matches if m.match_number == m_num)
        engine.setup_match(Stage.QUARTERFINAL.value, m_num, m_data.team_a_id, m_data.team_b_id)
        engine.admin_adjust_score(m_data.team_a_id, 30)
        engine.admin_adjust_score(m_data.team_b_id, 10)
        engine.end_match()

    # Verify all 4 QF matches are COMPLETED and Semifinals are populated
    for m_num in (7, 8, 9, 10):
        m = next(m for m in engine.bracket.matches if m.match_number == m_num)
        assert m.status == "COMPLETED"

    m11 = next(m for m in engine.bracket.matches if m.match_number == 11)
    m12 = next(m for m in engine.bracket.matches if m.match_number == 12)
    assert m11.team_a_id is not None and m11.team_b_id is not None
    assert m12.team_a_id is not None and m12.team_b_id is not None
