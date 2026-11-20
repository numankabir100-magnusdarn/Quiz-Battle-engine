from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional


def calculate_latency_stats(latencies: Iterable[float]) -> Dict[str, Any]:
    values = [float(value) for value in latencies]
    if not values:
        return {"count": 0, "min_ms": 0.0, "max_ms": 0.0, "average_ms": 0.0, "median_ms": 0.0}
    return {
        "count": len(values),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
        "average_ms": round(mean(values), 2),
        "median_ms": round(median(values), 2),
    }


def compare_buzzer_latency(
    team_a_latencies: Iterable[float],
    team_b_latencies: Iterable[float],
) -> Dict[str, Any]:
    a = calculate_latency_stats(team_a_latencies)
    b = calculate_latency_stats(team_b_latencies)
    return {
        "team_a": a,
        "team_b": b,
        "difference_ms": round(abs(a["average_ms"] - b["average_ms"]), 2),
        "fair": abs(a["average_ms"] - b["average_ms"]) <= 50.0,
    }
