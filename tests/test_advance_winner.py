"""
tests/test_advance_winner.py
Verifies advance_winner progression across Qualifiers, Quarterfinals, Semifinals, and Grand Final,
both with auto-detected leading score and explicit winner_id, plus tie validation.
"""
import pytest
from server.engine.game_engine import GameEngine
from server.engine.models import Stage


def test_advance_winner_tie_raises_descriptive_error():
    engine = GameEngine(auto_init_tournament=True)
    m1 = next(m for m in engine.bracket.matches if m.match_number == 1)
    engine.setup_match(Stage.QUALIFIER.value, 1, m1.team_a_id, m1.team_b_id)
    with pytest.raises(ValueError, match="tied"):
        engine.advance_winner(1)


def test_advance_winner_full_tournament_auto_and_explicit():
    engine = GameEngine(auto_init_tournament=True)

    # 1. Qualifiers M1-M6: advance M1-M3 via auto-detected leading score, M4-M6 via explicit winner_id
    for m_num in range(1, 7):
        m = next(x for x in engine.bracket.matches if x.match_number == m_num)
        engine.setup_match(Stage.QUALIFIER.value, m_num, m.team_a_id, m.team_b_id)
        if m_num <= 3:
            # Auto-detect from score: team_a leads
            engine.admin_adjust_score(m.team_a_id, 20 + m_num, "test score")
            engine.admin_adjust_score(m.team_b_id, 10, "test score")
            res = engine.advance_winner(str(m_num))  # test numeric string support
            assert res["winner_id"] == m.team_a_id
        else:
            # Explicit winner_id (even with tied score or distinct loser scores for wild cards)
            engine.admin_adjust_score(m.team_a_id, 10 + m_num, "loser score")
            engine.admin_adjust_score(m.team_b_id, 10 + m_num, "tied score")
            res = engine.advance_winner(m_num, winner_id=m.team_b_id)
            assert res["winner_id"] == m.team_b_id
        assert res["status"] == "COMPLETED"

    # Quarterfinals M7-M10 should now be populated (6 winners + 2 wild cards)
    qf_matches = [m for m in engine.bracket.matches if m.stage == Stage.QUARTERFINAL.value]
    assert len(qf_matches) == 4
    for qf in qf_matches:
        assert qf.team_a_id and qf.team_b_id

    # 2. Quarterfinals M7-M10
    qf_winners = []
    for m_num in range(7, 11):
        qf = next(x for x in engine.bracket.matches if x.match_number == m_num)
        engine.setup_match(Stage.QUARTERFINAL.value, m_num, qf.team_a_id, qf.team_b_id)
        engine.admin_adjust_score(qf.team_a_id, 30, "qf win")
        res = engine.advance_winner(m_num)
        assert res["winner_id"] == qf.team_a_id
        qf_winners.append(res["winner_id"])

    # Semifinals M11-M12 should now be populated
    m11 = next(m for m in engine.bracket.matches if m.match_number == 11)
    m12 = next(m for m in engine.bracket.matches if m.match_number == 12)
    assert m11.team_a_id == qf_winners[0] and m11.team_b_id == qf_winners[1]
    assert m12.team_a_id == qf_winners[2] and m12.team_b_id == qf_winners[3]

    # 3. Semifinals M11-M12
    engine.setup_match(Stage.SEMIFINAL.value, 11, m11.team_a_id, m11.team_b_id)
    res11 = engine.advance_winner(11, winner_id=m11.team_a_id)
    engine.setup_match(Stage.SEMIFINAL.value, 12, m12.team_a_id, m12.team_b_id)
    engine.admin_adjust_score(m12.team_b_id, 25, "sf win")
    res12 = engine.advance_winner(12)

    # Final M13 should now be populated
    m13 = next(m for m in engine.bracket.matches if m.match_number == 13)
    assert m13.team_a_id == res11["winner_id"]
    assert m13.team_b_id == res12["winner_id"]

    # 4. Grand Final M13 -> Champion
    engine.setup_match(Stage.FINAL.value, 13, m13.team_a_id, m13.team_b_id)
    engine.admin_adjust_score(m13.team_a_id, 50, "final win")
    res13 = engine.advance_winner(13)
    assert res13["winner_id"] == m13.team_a_id
    assert res13["champion"] == m13.team_a_id
    assert engine.bracket.champion == m13.team_a_id
