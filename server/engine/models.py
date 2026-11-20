from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Optional, Any
import time


class Stage(str, Enum):
    QUALIFIER = "Qualifier"
    QUARTERFINAL = "Quarterfinal"
    SEMIFINAL = "Semifinal"
    FINAL = "Final"


class RoundPhase(str, Enum):
    IDLE = "IDLE"
    RAPID_FIRE = "RAPID_FIRE"
    BUZZER_BATTLE = "BUZZER_BATTLE"
    SUDDEN_DEATH = "SUDDEN_DEATH"
    RESULT = "RESULT"


class QuestionType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    TRUE_FALSE = "true_false"


@dataclass
class QuestionCard:
    number: int
    type: str  # "text" | "image" | "true_false"
    text: str
    image: Optional[str] = None  # optional filename, e.g. "transformer.png"
    answer: str = ""
    points: int = 10

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuestionCard":
        return cls(
            number=data.get("number", 1),
            type=data.get("type", "text"),
            text=data.get("text", ""),
            image=data.get("image"),
            answer=data.get("answer", ""),
            points=data.get("points", 10),
        )


@dataclass
class Team:
    id: str
    name: str
    members: List[str] = field(default_factory=list)  # 1 or 2 strings
    designated_speaker: Optional[str] = None
    accent_color: Optional[str] = None
    match_scores: Dict[str, int] = field(default_factory=dict)  # match_number (str) -> score
    win_loss: Dict[str, int] = field(default_factory=lambda: {"wins": 0, "losses": 0})
    total_points: int = 0
    matches_played: int = 0
    match_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Team":
        scores = {str(k): int(v) for k, v in data.get("match_scores", {}).items()}
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            members=list(data.get("members", [])),
            designated_speaker=data.get("designated_speaker"),
            accent_color=data.get("accent_color"),
            match_scores=scores,
            win_loss=dict(data.get("win_loss", {"wins": 0, "losses": 0})),
            total_points=int(data.get("total_points", sum(scores.values()))),
            matches_played=int(data.get("matches_played", 0)),
            match_history=list(data.get("match_history", [])),
        )


MATCH_STAT_KEYS = (
    "rapid_fire_points",
    "buzzer_points",
    "foul_penalties",
    "questions_answered",
)


def blank_match_stats() -> Dict[str, int]:
    return {key: 0 for key in MATCH_STAT_KEYS}


@dataclass
class MatchData:
    match_number: int  # 1 to 13
    stage: str         # "Qualifier", "Quarterfinal", "Semifinal", "Final"
    team_a_id: Optional[str] = None
    team_b_id: Optional[str] = None
    winner_id: Optional[str] = None
    loser_id: Optional[str] = None
    scores: Dict[str, int] = field(default_factory=dict)  # team_id -> match score
    status: str = "PENDING"  # "PENDING" | "IN_PROGRESS" | "COMPLETED"
    stats: Dict[str, Dict[str, int]] = field(default_factory=dict)  # team_id -> per-match breakdown

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def ensure_stats(self, team_ids: List[str]) -> None:
        for team_id in team_ids:
            if not team_id:
                continue
            current = self.stats.get(team_id, {})
            self.stats[team_id] = {
                key: int(current.get(key, 0)) for key in MATCH_STAT_KEYS
            }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MatchData":
        match = cls(
            match_number=int(data["match_number"]),
            stage=data.get("stage", Stage.QUALIFIER.value),
            team_a_id=data.get("team_a_id"),
            team_b_id=data.get("team_b_id"),
            winner_id=data.get("winner_id"),
            loser_id=data.get("loser_id"),
            scores={str(k): int(v) for k, v in data.get("scores", {}).items()},
            status=data.get("status", "PENDING"),
        )
        raw_stats = data.get("stats", {})
        for team_id, values in raw_stats.items():
            if not isinstance(values, dict):
                continue
            match.stats[str(team_id)] = {
                key: int(values.get(key, 0)) for key in MATCH_STAT_KEYS
            }
        match.ensure_stats([match.team_a_id, match.team_b_id])
        return match


@dataclass
class BracketData:
    matches: List[MatchData] = field(default_factory=list)
    qualifier_winners: List[str] = field(default_factory=list)
    qualifier_losers: List[str] = field(default_factory=list)
    wild_cards: List[str] = field(default_factory=list)
    wild_card_tied_teams: List[str] = field(default_factory=list)
    champion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "matches": [m.to_dict() for m in self.matches],
            "qualifier_winners": list(self.qualifier_winners),
            "qualifier_losers": list(self.qualifier_losers),
            "wild_cards": list(self.wild_cards),
            "wild_card_tied_teams": list(self.wild_card_tied_teams),
            "champion": self.champion,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BracketData":
        matches = [MatchData.from_dict(m) for m in data.get("matches", [])]
        return cls(
            matches=matches,
            qualifier_winners=list(data.get("qualifier_winners", [])),
            qualifier_losers=list(data.get("qualifier_losers", [])),
            wild_cards=list(data.get("wild_cards", [])),
            wild_card_tied_teams=list(data.get("wild_card_tied_teams", [])),
            champion=data.get("champion"),
        )


@dataclass
class RoundState:
    phase: str = RoundPhase.IDLE.value
    timer_seconds_remaining: int = 0
    timer_duration_seconds: int = 120
    timer_running: bool = False
    active_team_id: Optional[str] = None  # relevant during Rapid Fire
    routing_mode: str = "BUZZER_OPEN"
    turn_start_side: str = "A"
    team_block_size: int = 10

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoundState":
        return cls(
            phase=data.get("phase", RoundPhase.IDLE.value),
            timer_seconds_remaining=int(data.get("timer_seconds_remaining", 0)),
            timer_duration_seconds=int(data.get("timer_duration_seconds", 120)),
            timer_running=bool(data.get("timer_running", False)),
            active_team_id=data.get("active_team_id"),
            routing_mode=data.get("routing_mode", "BUZZER_OPEN"),
            turn_start_side=data.get("turn_start_side", "A"),
            team_block_size=int(data.get("team_block_size", 10)),
        )


@dataclass
class QuestionState:
    current_question: Optional[QuestionCard] = None
    revealed: bool = False
    is_open: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_question": (
                {
                    "number": self.current_question.number,
                    "type": self.current_question.type,
                    "points": self.current_question.points,
                }
                if self.current_question
                else None
            ),
            "revealed": self.revealed,
            "is_open": self.is_open,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuestionState":
        q = data.get("current_question")
        return cls(
            current_question=QuestionCard.from_dict(q) if q else None,
            revealed=bool(data.get("revealed", False)),
            is_open=bool(data.get("is_open", False)),
        )


@dataclass
class BuzzersState:
    locked: bool = True
    first_team: Optional[str] = None
    press_timestamp: Optional[float] = None
    penalised_team: Optional[str] = None
    passed_to_team: Optional[str] = None
    attempted_teams: List[str] = field(default_factory=list)
    source_mode: str = "ESP32"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BuzzersState":
        return cls(
            locked=bool(data.get("locked", True)),
            first_team=data.get("first_team"),
            press_timestamp=data.get("press_timestamp"),
            penalised_team=data.get("penalised_team"),
            passed_to_team=data.get("passed_to_team"),
            attempted_teams=list(data.get("attempted_teams", [])),
            source_mode=str(data.get("source_mode", "ESP32")),
        )


@dataclass
class QuestionMatrixState:
    total_questions: int = 15
    current_question_num: Optional[int] = None
    routing_mode: str = "BUZZER_OPEN"
    turn_start_side: str = "A"
    team_block_size: int = 10
    statuses: List[Dict[str, Any]] = field(default_factory=list)
    questions_asked: int = 0
    questions_remaining: int = 15
    team_a_correct: int = 0
    team_b_correct: int = 0
    unanswered_count: int = 0

    def __post_init__(self) -> None:
        if not self.statuses:
            self.statuses = [
                {"num": number, "status": "unasked", "winner_side": None, "phase": None}
                for number in range(1, self.total_questions + 1)
            ]
        self.recalculate()

    def recalculate(self) -> None:
        self.questions_asked = sum(item["status"] != "unasked" for item in self.statuses)
        self.questions_remaining = max(0, self.total_questions - self.questions_asked)
        self.team_a_correct = sum(item.get("winner_side") == "A" for item in self.statuses)
        self.team_b_correct = sum(item.get("winner_side") == "B" for item in self.statuses)
        self.unanswered_count = sum(item["status"] == "dead" for item in self.statuses)

    def to_dict(self) -> Dict[str, Any]:
        self.recalculate()
        return {
            "total_questions": self.total_questions,
            "current_question_num": self.current_question_num,
            "routing_mode": self.routing_mode,
            "turn_start_side": self.turn_start_side,
            "team_block_size": self.team_block_size,
            "statuses": [dict(item) for item in self.statuses],
            "questions_asked": self.questions_asked,
            "questions_remaining": self.questions_remaining,
            "team_a_correct": self.team_a_correct,
            "team_b_correct": self.team_b_correct,
            "unanswered_count": self.unanswered_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuestionMatrixState":
        total = max(1, int(data.get("total_questions", 15)))
        statuses = list(data.get("statuses", []))
        if not statuses:
            statuses = [
                {"num": number, "status": "unasked", "winner_side": None, "phase": None}
                for number in range(1, total + 1)
            ]
        matrix = cls(
            total_questions=total,
            current_question_num=data.get("current_question_num"),
            routing_mode=data.get("routing_mode", "BUZZER_OPEN"),
            turn_start_side=data.get("turn_start_side", "A"),
            team_block_size=int(data.get("team_block_size", 10)),
            statuses=statuses,
        )
        matrix.recalculate()
        return matrix


@dataclass
class LogEntry:
    timestamp: str
    action: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LogEntry":
        return cls(
            timestamp=data.get("timestamp", ""),
            action=data.get("action", ""),
            details=dict(data.get("details", {})),
        )
