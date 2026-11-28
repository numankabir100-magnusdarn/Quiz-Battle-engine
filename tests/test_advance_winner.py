"""
tests/test_advance_winner.py
Verifies 14-team seeding (T01-T14) and advance_winner progression across
Qualifiers (M1-M7 + Top-1 Wild-Card), Quarterfinals (M8-M11), Semifinals (M12-M13), and Grand Final (M14).
"""
import pytest
from server.engine.game_engine import GameEngine
from server.engine.models import Stage


def test_seed_official_14_teams():
    engine = GameEngine(auto_init_tournament=False)
    res = engine.seed_official_14_teams()
    assert res["seeded"] is True
    assert res["team_count"] == 14
    assert res["match_count"] == 14
    assert len(engine.teams) == 14
    assert engine.teams["T01"].name == "EE Royals"
    assert engine.teams["T10"].name == "Tech Pro"
    assert engine.teams["T10"].members == ["Muhammad Umair Saeed"]
    assert engine.teams["T14"].name == "Brain Box"
    assert len(engine.bracket.matches) == 14
    qual_matches = [m for m in engine.bracket.matches if m.stage == Stage.QUALIFIER.value]
    assert len(qual_matches) == 7
    assert qual_matches[0].team_a_id == "T01" and qual_matches[0].team_b_id == "T02"
    assert qual_matches[6].team_a_id == "T13" and qual_matches[6].team_b_id == "T14"


def test_advance_winner_tie_raises_descriptive_error():
    engine = GameEngine(auto_init_tournament=True)
    m1 = next(m for m in engine.bracket.matches if m.match_number == 1)
    engine.setup_match(Stage.QUALIFIER.value, 1, m1.team_a_id, m1.team_b_id)
    with pytest.raises(ValueError, match="tied"):
        engine.advance_winner(1)


def test_advance_winner_full_14_match_tournament_auto_and_explicit():
    engine = GameEngine(auto_init_tournament=True)

    # 1. Qualifiers M1-M7: advance M1-M4 via auto-detected leading score, M5-M7 via explicit winner_id
    for m_num in range(1, 8):
        m = next(x for x in engine.bracket.matches if x.match_number == m_num)
        engine.setup_match(Stage.QUALIFIER.value, m_num, m.team_a_id, m.team_b_id)
        if m_num <= 4:
            engine.admin_adjust_score(m.team_a_id, 30 + m_num, "test score")
            engine.admin_adjust_score(m.team_b_id, 10 + m_num, "test score")
            res = engine.advance_winner(str(m_num))
            assert res["winner_id"] == m.team_a_id
        else:
            engine.admin_adjust_score(m.team_a_id, 20 + m_num, "loser score")
            engine.admin_adjust_score(m.team_b_id, 20 + m_num, "tied score")
            res = engine.advance_winner(m_num, winner_id=m.team_b_id)
            assert res["winner_id"] == m.team_b_id
        assert res["status"] == "COMPLETED"

    # Top-1 Wild-Card should be T13 (loser of M7 with 27 pts)
    assert engine.bracket.wild_cards == ["T13"]

    # Quarterfinals M8-M11 should now be populated (7 winners + 1 wild card)
    qf_matches = [m for m in engine.bracket.matches if m.stage == Stage.QUARTERFINAL.value]
    assert len(qf_matches) == 4
    for qf in qf_matches:
        assert qf.team_a_id and qf.team_b_id

    # 2. Quarterfinals M8-M11
    qf_winners = []
    for m_num in range(8, 12):
        qf = next(x for x in engine.bracket.matches if x.match_number == m_num)
        engine.setup_match(Stage.QUARTERFINAL.value, m_num, qf.team_a_id, qf.team_b_id)
        engine.admin_adjust_score(qf.team_a_id, 30, "qf win")
        res = engine.advance_winner(m_num)
        assert res["winner_id"] == qf.team_a_id
        qf_winners.append(res["winner_id"])

    # Semifinals M12-M13 should now be populated
    m12 = next(m for m in engine.bracket.matches if m.match_number == 12)
    m13 = next(m for m in engine.bracket.matches if m.match_number == 13)
    assert m12.team_a_id == qf_winners[0] and m12.team_b_id == qf_winners[1]
    assert m13.team_a_id == qf_winners[2] and m13.team_b_id == qf_winners[3]

    # 3. Semifinals M12-M13
    engine.setup_match(Stage.SEMIFINAL.value, 12, m12.team_a_id, m12.team_b_id)
    res12 = engine.advance_winner(12, winner_id=m12.team_a_id)
    engine.setup_match(Stage.SEMIFINAL.value, 13, m13.team_a_id, m13.team_b_id)
    engine.admin_adjust_score(m13.team_b_id, 25, "sf win")
    res13 = engine.advance_winner(13)

    # Final M14 should now be populated
    m14 = next(m for m in engine.bracket.matches if m.match_number == 14)
    assert m14.team_a_id == res12["winner_id"]
    assert m14.team_b_id == res13["winner_id"]

    # 4. Grand Final M14 -> Champion
    engine.setup_match(Stage.FINAL.value, 14, m14.team_a_id, m14.team_b_id)
    engine.admin_adjust_score(m14.team_a_id, 50, "final win")
    res14 = engine.advance_winner(14)
    assert res14["winner_id"] == m14.team_a_id
    assert res14["champion"] == m14.team_a_id
    assert engine.bracket.champion == m14.team_a_id
