import pytest
from starlette.testclient import TestClient
from server.main import app, engine


def test_tournament_progress_payload():
    client = TestClient(app)
    res = client.get("/api/tournament/progress")
    assert res.status_code == 200
    data = res.json()
    assert data["total_matches"] == 14
    assert "completed_matches" in data
    assert "percent_complete" in data
    assert "stages" in data
    assert data["stages"]["qualifiers"]["total"] == 7
    assert data["stages"]["quarterfinals"]["total"] == 4
    assert data["stages"]["semifinals"]["total"] == 2
    assert data["stages"]["final"]["total"] == 1
    assert "standings" in data
    assert len(data["standings"]) == 14
    assert "completed_results" in data


def test_advance_and_load_next_flow():
    client = TestClient(app)

    # Start clean
    engine.init_default_tournament()
    engine.setup_match("Qualifier", 1, "T01", "T02")
    engine.current_match.scores["T01"] = 30
    engine.current_match.scores["T02"] = 15

    # 1. Advance Match 1 -> Match 2
    adv_res = client.post("/api/tournament/advance-and-load-next")
    assert adv_res.status_code == 200
    res_data = adv_res.json()
    assert res_data["status"] == "NEXT_MATCH_LOADED"
    assert res_data["completed_match"] == 1
    assert res_data["winner_id"] == "T01"
    assert res_data["next_match"] == 2
    assert res_data["team_a_id"] == "T03"
    assert res_data["team_b_id"] == "T04"
    assert engine.match_number == 2
    assert engine.current_match.team_a_id == "T03"


def test_advance_and_load_next_tied_launches_sudden_death():
    client = TestClient(app)

    engine.setup_match("Qualifier", 2, "T03", "T04")
    engine.current_match.scores["T03"] = 20
    engine.current_match.scores["T04"] = 20

    adv_res = client.post("/api/tournament/advance-and-load-next")
    assert adv_res.status_code == 200
    res_data = adv_res.json()
    assert res_data["status"] == "TIED"
    assert engine.round.phase == "SUDDEN_DEATH"


def test_reset_scores_keep_roster_preserves_custom_teams():
    client = TestClient(app)

    # Customize team
    engine.teams["T01"].name = "Power Engineers"
    engine.teams["T01"].accent_color = "#e11d48"
    engine.teams["T01"].designated_speaker = "Dr. Spark"
    engine.teams["T01"].total_points = 150
    engine.teams["T01"].win_loss = {"wins": 3, "losses": 0}

    # Reset scores keep roster
    reset_res = client.post("/api/tournament/reset-scores-keep-roster")
    assert reset_res.status_code == 200
    data = reset_res.json()
    assert data["reset"] is True
    assert data["teams_kept"] == 14

    # Verification: customization preserved, scores zeroed
    t1 = engine.teams["T01"]
    assert t1.name == "Power Engineers"
    assert t1.accent_color == "#e11d48"
    assert t1.designated_speaker == "Dr. Spark"
    assert t1.total_points == 0
    assert t1.win_loss == {"wins": 0, "losses": 0}
    assert t1.matches_played == 0
    assert engine.match_number == 1
    assert engine.current_match.team_a_id == "T01"
    assert engine.current_match.team_b_id == "T02"
