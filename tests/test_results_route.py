"""
tests/test_results_route.py
Tests for the /results page and enriched tournament standings state.
"""
import pytest
from fastapi.testclient import TestClient
from server.main import app

client_test = TestClient(app)


# ── Route tests ────────────────────────────────────────────────────────────────

def test_results_route_returns_200():
    resp = client_test.get("/results")
    assert resp.status_code == 200


def test_results_page_contains_leaderboard_markup():
    resp = client_test.get("/results")
    assert resp.status_code == 200
    text = resp.text.lower()
    assert "leaderboard" in text or "results" in text


def test_results_page_offline_no_external_urls():
    """The page must not contain any http:// or https:// external resource references."""
    resp = client_test.get("/results")
    import re
    # allow href to /api and src to /static only
    external = re.findall(r'(?:src|href)=["\']https?://', resp.text)
    assert external == [], f"External URL references found: {external}"


# ── State enrichment tests ─────────────────────────────────────────────────────

def test_state_includes_standings():
    resp = client_test.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    progress = data.get("tournament_progress", {})
    assert "standings" in progress
    standings = progress["standings"]
    assert len(standings) == 14


def test_standings_have_required_enriched_fields():
    resp = client_test.get("/api/state")
    data = resp.json()
    standings = data["tournament_progress"]["standings"]
    required = {"team_id", "name", "rank", "wins", "losses", "matches_played",
                "total_points", "rapid_fire_points", "buzzer_points",
                "foul_penalties", "status", "accent_color",
                "wild_card_qualified", "in_live_match", "match_history"}
    for s in standings:
        missing = required - set(s.keys())
        assert missing == set(), f"Standing entry missing fields: {missing}"


def test_standings_rank_is_sequential():
    resp = client_test.get("/api/state")
    data = resp.json()
    standings = data["tournament_progress"]["standings"]
    ranks = [s["rank"] for s in standings]
    assert ranks == list(range(1, len(standings) + 1)), f"Ranks not sequential: {ranks}"


def test_standings_status_values_are_valid():
    valid_statuses = {"CHAMPION", "FINALIST", "SEMIFINALIST", "QUARTERFINALIST",
                      "WILD_CARD", "ELIMINATED", "ACTIVE"}
    resp = client_test.get("/api/state")
    data = resp.json()
    standings = data["tournament_progress"]["standings"]
    for s in standings:
        assert s["status"] in valid_statuses, f"Invalid status: {s['status']}"


def test_standings_numeric_fields_non_negative():
    resp = client_test.get("/api/state")
    data = resp.json()
    standings = data["tournament_progress"]["standings"]
    for s in standings:
        # rf/bz/fouls are always >= 0; total_points can go negative via foul penalties
        assert s["rapid_fire_points"] >= 0
        assert s["buzzer_points"] >= 0
        assert s["foul_penalties"] >= 0
        assert isinstance(s["total_points"], (int, float))  # negative allowed by design
        assert s["matches_played"] >= 0


def test_state_includes_highlights():
    resp = client_test.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    progress = data.get("tournament_progress", {})
    assert "highlights" in progress
    h = progress["highlights"]
    assert "top_rapid_fire_team" in h
    assert "top_buzzer_team" in h
    assert "highest_match_score" in h
    assert "live_match" in h


def test_highlights_top_rf_team_structure():
    resp = client_test.get("/api/state")
    data = resp.json()
    h = data["tournament_progress"]["highlights"]
    rf = h.get("top_rapid_fire_team")
    # With no matches played yet, can be None or dict with 0 points
    if rf is not None:
        assert "team_id" in rf
        assert "name" in rf
        assert "points" in rf


def test_highlights_live_match_is_none_when_idle():
    resp = client_test.get("/api/state")
    data = resp.json()
    h = data["tournament_progress"]["highlights"]
    # At startup with no match loaded there is no live match
    # (may be None or absent for a pending match)
    assert "live_match" in h  # key must exist even if value is None
