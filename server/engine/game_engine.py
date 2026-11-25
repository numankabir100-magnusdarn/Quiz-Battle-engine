import copy
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple

from server.engine.models import (
    Stage,
    RoundPhase,
    QuestionCard,
    QuestionState,
    Team,
    MatchData,
    BracketData,
    RoundState,
    BuzzersState,
    QuestionMatrixState,
    LogEntry,
    MATCH_STAT_KEYS,
)
from server.engine.questions import QuestionProvider, SampleQuestionProvider


RAPID_FIRE_CORRECT_POINTS = 10
BUZZER_CORRECT_POINTS = 15
BUZZER_WRONG_PENALTY = 5
SCORE_ACTION_GUARD_SECONDS = 0.150


class GameEngine:
    """Pure Python game engine for EEE Brain Battle.
    Contains zero web/FastAPI code. Entirely unit-testable.
    Enforces all rules from the official EEECi FA'26 Module 06 rulebook.
    """

    def __init__(
        self,
        question_provider: Optional[QuestionProvider] = None,
        auto_init_tournament: bool = True,
    ):
        self.question_provider: QuestionProvider = question_provider or SampleQuestionProvider()
        self.stage: str = Stage.QUALIFIER.value
        self.match_number: int = 1
        self.teams: Dict[str, Team] = {}
        self.bracket: BracketData = BracketData()
        self.current_match: Optional[MatchData] = None
        self.round: RoundState = RoundState()
        self.question: QuestionState = QuestionState()
        self.buzzers: BuzzersState = BuzzersState()
        self.question_matrix: QuestionMatrixState = QuestionMatrixState()
        self._undo_stack: List[Dict[str, Any]] = []
        self._rapid_fire_started_at: Optional[float] = None
        self._rapid_fire_durations: List[float] = []
        self._rapid_fire_streak: int = 0
        self.log: List[LogEntry] = []
        self._question_index: int = 0
        self.used_question_numbers: List[int] = []
        self.question_bank_warning: Optional[str] = None
        self.display_view: str = "auto"
        self._spoken_matrix_mode = False
        self.snapshot_saver: Optional[Any] = None
        self.buzzer_source_mode: str = "ESP32"
        self.strict_esp32: bool = False
        self._last_score_guard_key: str = ""
        self._last_score_guard_at: float = 0.0

        if auto_init_tournament:
            self.init_default_tournament()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # -------------------------------------------------------------------------
    # Cumulative ledger helpers
    # -------------------------------------------------------------------------

    def _set_team_score(self, team_id: str, new_score: int) -> None:
        """Writes a match score while keeping the team's cumulative total in sync."""
        team = self.teams.get(team_id)
        if not team:
            return
        key = str(self.match_number)
        old_score = int(team.match_scores.get(key, 0))
        team.match_scores[key] = int(new_score)
        team.total_points += int(new_score) - old_score

    def _bump_match_stat(self, team_id: str, key: str, delta: int = 1) -> None:
        if not self.current_match or key not in MATCH_STAT_KEYS:
            return
        self.current_match.ensure_stats([team_id])
        self.current_match.stats[team_id][key] += int(delta)

    def _zero_match_counters(self) -> None:
        match = self.current_match
        if match:
            team_ids = [team_id for team_id in (match.team_a_id, match.team_b_id) if team_id]
            match.ensure_stats(team_ids)
            for team_id in team_ids:
                match.scores[team_id] = 0
                match.stats[team_id] = {key: 0 for key in MATCH_STAT_KEYS}
                self._set_team_score(team_id, 0)
            match.winner_id = None
            match.loser_id = None
        self.question_matrix = QuestionMatrixState(
            total_questions=self.question_matrix.total_questions,
            routing_mode=self.round.routing_mode,
            turn_start_side=self.round.turn_start_side,
            team_block_size=self.round.team_block_size,
        )
        self._rapid_fire_started_at = None
        self._rapid_fire_durations = []
        self._rapid_fire_streak = 0
        self._last_score_guard_key = ""
        self._last_score_guard_at = 0.0

    def _score_guard_team(self, team_id: Optional[str]) -> Optional[str]:
        if team_id:
            return team_id
        phase = self.round.phase
        if phase == RoundPhase.RAPID_FIRE.value:
            return self.round.active_team_id
        if phase in (RoundPhase.BUZZER_BATTLE.value, RoundPhase.SUDDEN_DEATH.value):
            return self.buzzers.passed_to_team or self.buzzers.first_team
        return self.current_match.team_a_id if self.current_match else None

    def _score_action_allowed(self, action: str, team_id: Optional[str]) -> bool:
        question_number = self.question.current_question.number if self.question.current_question else None
        effective_team = self._score_guard_team(team_id)
        key = f"{action}|{self.round.phase}|{question_number}|{effective_team or ''}"
        now = time.monotonic()
        if key == self._last_score_guard_key and (now - self._last_score_guard_at) < SCORE_ACTION_GUARD_SECONDS:
            return False
        self._last_score_guard_key = key
        self._last_score_guard_at = now
        return True

    def _upsert_match_history(self, team_id: str, outcome: Optional[str] = None) -> None:
        """Records or refreshes one team's ledger row for the active match."""
        match = self.current_match
        team = self.teams.get(team_id)
        if not match or not team or match.status != "COMPLETED":
            return
        opponent_id = match.team_b_id if team_id == match.team_a_id else match.team_a_id
        opponent = self.teams.get(opponent_id) if opponent_id else None
        team_score = int(match.scores.get(team_id, 0))
        opponent_score = int(match.scores.get(opponent_id, 0)) if opponent_id else 0
        stats = match.stats.get(team_id, {})
        if outcome is None:
            if match.winner_id == team_id:
                outcome = "WIN"
            elif match.loser_id == team_id:
                outcome = "LOSS"
            elif team_score == opponent_score:
                outcome = "TIE"
            else:
                outcome = "PENDING"

        row = {
            "match_number": int(match.match_number),
            "stage": str(match.stage),
            "opponent_id": opponent_id,
            "opponent_name": opponent.name if opponent else "TBD",
            "team_score": team_score,
            "opponent_score": opponent_score,
            "rapid_fire_points": int(stats.get("rapid_fire_points", 0)),
            "buzzer_points": int(stats.get("buzzer_points", 0)),
            "foul_penalties": int(stats.get("foul_penalties", 0)),
            "questions_answered": int(stats.get("questions_answered", 0)),
            "outcome": outcome,
            "timestamp": self._now_iso(),
        }
        existing = next(
            (item for item in team.match_history if int(item.get("match_number", -1)) == match.match_number),
            None,
        )
        if existing:
            existing.update(row)
        else:
            team.match_history.append(row)

    def _refresh_completed_history(self) -> None:
        if self.current_match and self.current_match.status == "COMPLETED":
            for team_id in (self.current_match.team_a_id, self.current_match.team_b_id):
                if team_id:
                    self._upsert_match_history(team_id)

    def _save_match_snapshot(self) -> None:
        if not self.current_match or self.current_match.status != "COMPLETED":
            return
        if not callable(self.snapshot_saver):
            return
        payload = {
            "saved_at": self._now_iso(),
            "match": self.current_match.to_dict(),
            "state": self.get_state(),
        }
        try:
            self.snapshot_saver(self.current_match.match_number, payload)
        except Exception as exc:
            self._log_action("match_snapshot_error", {"match_number": self.match_number, "error": str(exc)})

    def set_display_view(self, view: str) -> Dict[str, str]:
        view = str(view).lower()
        if view not in {"auto", "match", "bracket", "result"}:
            raise ValueError("Display view must be auto, match, bracket, or result")
        self.display_view = view
        self._log_action("set_display_view", {"view": view})
        return {"view": view}

    def _log_action(self, action: str, details: Optional[Dict[str, Any]] = None) -> None:
        entry = LogEntry(
            timestamp=self._now_iso(),
            action=action,
            details=details or {},
        )
        self.log.append(entry)

    # -------------------------------------------------------------------------
    # Tournament Initialization & Bracket Setup
    # -------------------------------------------------------------------------

    def init_default_tournament(self) -> None:
        """Initializes 12 teams and the 13-match bracket structure."""
        self.display_view = "auto"
        self.teams.clear()
        for i in range(1, 13):
            t_id = f"team_{i}"
            speaker = f"Player {i}A"
            self.teams[t_id] = Team(
                id=t_id,
                name=f"Team {i:02d}",
                members=[f"Player {i}A", f"Player {i}B"],
                designated_speaker=speaker,
                accent_color="#0ea5e9" if i % 2 else "#f97316",
                match_scores={},
                win_loss={"wins": 0, "losses": 0},
            )

        matches: List[MatchData] = []
        # Matches 1-6: Qualifiers (12 teams -> 6 matches)
        for m in range(1, 7):
            t_a = f"team_{2*m - 1}"
            t_b = f"team_{2*m}"
            matches.append(
                MatchData(
                    match_number=m,
                    stage=Stage.QUALIFIER.value,
                    team_a_id=t_a,
                    team_b_id=t_b,
                    scores={t_a: 0, t_b: 0},
                    status="PENDING",
                )
            )

        # Matches 7-10: Quarterfinals (8 teams -> 4 matches)
        for m in range(7, 11):
            matches.append(
                MatchData(
                    match_number=m,
                    stage=Stage.QUARTERFINAL.value,
                    scores={},
                    status="PENDING",
                )
            )

        # Matches 11-12: Semifinals (4 teams -> 2 matches)
        for m in range(11, 13):
            matches.append(
                MatchData(
                    match_number=m,
                    stage=Stage.SEMIFINAL.value,
                    scores={},
                    status="PENDING",
                )
            )

        # Match 13: Final (2 teams -> 1 match)
        matches.append(
            MatchData(
                match_number=13,
                stage=Stage.FINAL.value,
                scores={},
                status="PENDING",
            )
        )

        self.bracket = BracketData(matches=matches)
        self.used_question_numbers.clear()
        self.question_bank_warning = None
        self.setup_match(Stage.QUALIFIER.value, 1, "team_1", "team_2")
        self._log_action("init_default_tournament", {"team_count": 12, "match_count": 13})

    def setup_match(
        self,
        stage: str,
        match_number: int,
        team_a_id: str,
        team_b_id: str,
    ) -> None:
        """Sets up the active match between team A and team B."""
        if team_a_id not in self.teams:
            raise ValueError(f"Team '{team_a_id}' does not exist in tournament")
        if team_b_id not in self.teams:
            raise ValueError(f"Team '{team_b_id}' does not exist in tournament")
        if team_a_id == team_b_id:
            raise ValueError("Team A and Team B cannot be the same team")

        self.stage = stage
        self.match_number = match_number

        # Update bracket match record
        bracket_match = next((m for m in self.bracket.matches if m.match_number == match_number), None)
        if bracket_match:
            bracket_match.team_a_id = team_a_id
            bracket_match.team_b_id = team_b_id
            bracket_match.stage = stage
            bracket_match.status = "IN_PROGRESS"
            if team_a_id not in bracket_match.scores:
                bracket_match.scores[team_a_id] = 0
            if team_b_id not in bracket_match.scores:
                bracket_match.scores[team_b_id] = 0
            bracket_match.ensure_stats([team_a_id, team_b_id])
            self.current_match = bracket_match
        else:
            self.current_match = MatchData(
                match_number=match_number,
                stage=stage,
                team_a_id=team_a_id,
                team_b_id=team_b_id,
                scores={team_a_id: 0, team_b_id: 0},
                status="IN_PROGRESS",
            )
            self.current_match.ensure_stats([team_a_id, team_b_id])
            self.bracket.matches.append(self.current_match)

        # Reset round and buzzer states for the match
        self.round = RoundState(phase=RoundPhase.IDLE.value, timer_seconds_remaining=0, timer_running=False)
        self.question = QuestionState()
        self.buzzers = BuzzersState(locked=True)
        self._undo_stack = []
        self._question_index = 0
        self._zero_match_counters()

        self._log_action(
            "setup_match",
            {
                "stage": stage,
                "match_number": match_number,
                "team_a": team_a_id,
                "team_b": team_b_id,
            },
        )

    # -------------------------------------------------------------------------
    # Game Flow Actions
    # -------------------------------------------------------------------------

    def start_rapid_fire(self, team_id: str, duration_seconds: int = 120) -> None:
        """Starts Rapid Fire round for designated team.
        Rules:
        - 120 seconds per team
        - One designated speaker
        - +10 per correct answer, 0 for wrong, no negative marking
        - Buzzers locked during rapid fire
        """
        if not self.current_match:
            raise ValueError("No active match configured")
        if team_id not in (self.current_match.team_a_id, self.current_match.team_b_id):
            raise ValueError(f"Team '{team_id}' is not participating in current match")

        self.round.phase = RoundPhase.RAPID_FIRE.value
        self._spoken_matrix_mode = True
        self.round.active_team_id = team_id
        # The selected team owns Q1. Subsequent questions are derived from
        # this side for AUTO_ALTERNATE and TEAM_BLOCK routing.
        self.round.turn_start_side = "A" if team_id == self.current_match.team_a_id else "B"
        if self.round.routing_mode == "BUZZER_OPEN":
            self.round.routing_mode = "TEAM_BLOCK"
            self.round.team_block_size = 10
        # A fresh round honors the moderator's configured starting side. A
        # repeated Rapid Fire start explicitly selects the other team's turn.
        self.question_matrix.routing_mode = self.round.routing_mode
        self.question_matrix.turn_start_side = self.round.turn_start_side
        self.question_matrix.team_block_size = self.round.team_block_size
        self.round.timer_seconds_remaining = duration_seconds
        self.round.timer_duration_seconds = duration_seconds
        self.round.timer_running = False  # Timer is started explicitly

        # Buzzers locked during Rapid Fire
        self.buzzers = BuzzersState(locked=True)
        self.question = QuestionState()
        self._rapid_fire_started_at = None
        self._rapid_fire_durations = []
        self._rapid_fire_streak = 0
        self._last_score_guard_key = ""
        self._last_score_guard_at = 0.0

        self._log_action(
            "start_rapid_fire",
            {"team_id": team_id, "duration": duration_seconds, "speaker": self.teams[team_id].designated_speaker},
        )

    def start_buzzer_battle(self) -> None:
        """Starts Buzzer Battle phase.
        Fix: Arms Q1 immediately — sets buzzers unlocked and question open so
        hardware & mobile buzzers are ready from millisecond zero.
        """
        if not self.current_match:
            raise ValueError("No active match configured")

        self.round.phase = RoundPhase.BUZZER_BATTLE.value
        self._spoken_matrix_mode = True
        self.round.active_team_id = None
        self.round.routing_mode = "BUZZER_OPEN"
        self.question_matrix.routing_mode = "BUZZER_OPEN"
        self.round.timer_running = False
        self.round.timer_seconds_remaining = 0
        # Arm Q1 immediately: open question and unlock buzzers
        self.question = QuestionState(is_open=True)
        self.buzzers = BuzzersState(
            locked=False,
            first_team=None,
            press_timestamp=None,
            penalised_team=None,
            passed_to_team=None,
            attempted_teams=[],
        )

        self._log_action("start_buzzer_battle", {"match_number": self.match_number, "q1_armed": True})

    def open_question(self, question_card: Optional[QuestionCard] = None) -> Dict[str, Any]:
        """Opens a question for answering.
        Tracks used questions across the entire event to ensure no question is ever repeated.
        When the bank is nearly empty (<= 2 unused questions left), sends the moderator a warning.
        Raises ValueError when no unused questions remain (never wraps around).
        In Buzzer Battle or Sudden Death, automatically unlocks buzzers.
        """
        if not self.current_match:
            raise ValueError("No active match configured")

        all_questions = self.question_provider.list_questions()

        if question_card is None:
            # Pick next unused question from provider
            unused_questions = [q for q in all_questions if q.number not in self.used_question_numbers]
            if not unused_questions and not self._spoken_matrix_mode:
                raise ValueError("Question bank exhausted: all available questions have been used in this event.")
            if not unused_questions:
                next_matrix_question = next(
                    (
                        item["num"]
                        for item in self.question_matrix.statuses
                        if item["status"] == "unasked"
                    ),
                    None,
                )
                if next_matrix_question is None:
                    raise ValueError("Question matrix exhausted: all configured questions have been used.")
                # The moderator speaks the question; a matrix slot does not
                # require question content in the server or public state.
                question_card = QuestionCard(
                    number=next_matrix_question,
                    type="spoken",
                    text="",
                    points=10,
                )
            else:
                question_card = unused_questions[0]
        else:
            if question_card.number in self.used_question_numbers:
                raise ValueError(f"Question #{question_card.number} has already been used in this event.")

        # Mark as used
        if question_card.number not in self.used_question_numbers:
            self.used_question_numbers.append(question_card.number)

        # Check remaining unused questions
        remaining_count = len([q for q in all_questions if q.number not in self.used_question_numbers])
        if remaining_count <= 2:
            self.question_bank_warning = (
                f"Question bank is nearly empty: only {remaining_count} question(s) remaining."
            )
        else:
            self.question_bank_warning = None

        # Determine default points if not set
        points = question_card.points
        if self.round.phase == RoundPhase.RAPID_FIRE.value:
            points = 10
        elif self.round.phase in (RoundPhase.BUZZER_BATTLE.value, RoundPhase.SUDDEN_DEATH.value):
            points = 15

        active_card = QuestionCard(
            number=question_card.number,
            type=question_card.type,
            text=question_card.text,
            image=question_card.image,
            answer=question_card.answer,
            points=points,
        )

        self.question = QuestionState(
            current_question=active_card,
            revealed=False,
            is_open=True,
        )

        # Buzzer handling based on phase
        if self.round.phase in (RoundPhase.BUZZER_BATTLE.value, RoundPhase.SUDDEN_DEATH.value):
            self.buzzers = BuzzersState(
                locked=False,
                first_team=None,
                press_timestamp=None,
                penalised_team=None,
                passed_to_team=None,
                attempted_teams=[],
            )
        else:
            self.buzzers = BuzzersState(locked=True)

        self._mark_matrix_active(active_card.number)
        if self.round.phase == RoundPhase.RAPID_FIRE:
            self._rapid_fire_started_at = time.time()
        self._log_action(
            "open_question",
            {
                "question_number": active_card.number,
                "type": active_card.type,
                "points": active_card.points,
                "phase": self.round.phase,
                "remaining_questions": remaining_count,
                "warning": self.question_bank_warning,
            },
        )

        return {
            "question_number": active_card.number,
            "warning": self.question_bank_warning,
            "remaining": remaining_count,
        }

    def set_total_questions(self, total_questions: int) -> Dict[str, Any]:
        total = int(total_questions)
        if total < 1 or total > 100:
            raise ValueError("total_questions must be between 1 and 100")
        self.question_matrix = QuestionMatrixState(total_questions=total)
        if hasattr(self.question_provider, "set_count"):
            self.question_provider.set_count(total)
        self._spoken_matrix_mode = True
        self.question_matrix.routing_mode = self.round.routing_mode
        self.question_matrix.turn_start_side = self.round.turn_start_side
        self.question_matrix.team_block_size = self.round.team_block_size
        self._log_action("set_total_questions", {"total_questions": total})
        return self.question_matrix.to_dict()

    def configure_routing(
        self,
        mode: str,
        start_side: str = "A",
        block_size: int = 10,
    ) -> Dict[str, Any]:
        mode = mode.upper()
        if mode not in {"AUTO_ALTERNATE", "TEAM_BLOCK", "BUZZER_OPEN"}:
            raise ValueError("Invalid routing mode")
        if start_side.upper() not in {"A", "B"}:
            raise ValueError("start_side must be A or B")
        if int(block_size) < 1 or int(block_size) > 100:
            raise ValueError("block_size must be between 1 and 100")
        self.round.routing_mode = mode
        self.round.turn_start_side = start_side.upper()
        self.round.team_block_size = int(block_size)
        self.question_matrix.routing_mode = mode
        self.question_matrix.turn_start_side = start_side.upper()
        self.question_matrix.team_block_size = int(block_size)
        if self.question_matrix.current_question_num:
            self._set_active_turn(self.question_matrix.current_question_num)
        self._log_action(
            "configure_routing",
            {"mode": mode, "start_side": start_side.upper(), "block_size": int(block_size)},
        )
        return self.routing_state()

    def routing_state(self) -> Dict[str, Any]:
        return {
            "mode": self.round.routing_mode,
            "start_side": self.round.turn_start_side,
            "block_size": self.round.team_block_size,
            "active_team_id": self.round.active_team_id,
        }

    def telemetry(self) -> Dict[str, Any]:
        average = (
            sum(self._rapid_fire_durations) / len(self._rapid_fire_durations)
            if self._rapid_fire_durations
            else 0.0
        )
        return {
            "average_seconds_per_question": round(average, 2),
            "current_streak": self._rapid_fire_streak,
        }

    def _set_active_turn(self, question_number: int) -> None:
        if not self.current_match or self.round.routing_mode == "BUZZER_OPEN":
            self.round.active_team_id = None
            return
        if self.round.routing_mode == "TEAM_BLOCK":
            block = (question_number - 1) // self.round.team_block_size
        else:
            block = question_number - 1
        start_is_a = self.round.turn_start_side == "A"
        side_a = (block % 2 == 0) == start_is_a
        self.round.active_team_id = (
            self.current_match.team_a_id if side_a else self.current_match.team_b_id
        )

    def switch_turn(self, reset_seconds: int = 120) -> Dict[str, Any]:
        if not self.current_match:
            raise ValueError("No active match configured")
        if self.round.routing_mode == "BUZZER_OPEN":
            raise ValueError("Buzzer-open mode has no active turn")
        current_side_a = self.round.active_team_id == self.current_match.team_a_id
        self.round.active_team_id = (
            self.current_match.team_b_id if current_side_a else self.current_match.team_a_id
        )
        self.round.timer_seconds_remaining = int(reset_seconds)
        self.round.timer_duration_seconds = int(reset_seconds)
        self.round.timer_running = False
        self._log_action("switch_turn", self.routing_state())
        return self.routing_state()

    def select_question(self, question_number: int) -> Dict[str, Any]:
        self._record_undo_snapshot("select_question")
        number = int(question_number)
        card = next(
            (question for question in self.question_provider.list_questions()
             if question.number == number),
            None,
        )
        if card is None:
            card = QuestionCard(number=number, type="spoken", text="", points=10)
        if number not in self.used_question_numbers and card.text:
            self.open_question(card)
        else:
            self.question = QuestionState(
                current_question=card,
                revealed=False,
                is_open=True,
            )
            self.buzzers = BuzzersState(
                locked=self.round.phase not in (
                    RoundPhase.BUZZER_BATTLE.value,
                    RoundPhase.SUDDEN_DEATH.value,
                )
            )
            self._mark_matrix_active(number)
        self._log_action("select_question", {"question_number": number})
        return {"question_number": number}

    def update_team(
        self,
        team_id: str,
        name: str,
        members: List[str],
        designated_speaker: str,
        accent_color: Optional[str] = None,
    ) -> Dict[str, Any]:
        if team_id not in self.teams:
            raise ValueError(f"Team '{team_id}' does not exist")
        if len(members) < 1 or len(members) > 2:
            raise ValueError("A team must have one or two members")
        if designated_speaker not in members:
            raise ValueError("Designated speaker must be one of the team members")
        team = self.teams[team_id]
        team.name = name.strip() or team.name
        team.members = list(members)
        team.designated_speaker = designated_speaker
        if accent_color:
            team.accent_color = accent_color
        self._log_action("team_updated", {"team_id": team_id, "name": team.name})
        return team.to_dict()

    def _matrix_status(self, number: int) -> Dict[str, Any]:
        if number < 1 or number > self.question_matrix.total_questions:
            raise ValueError(
                f"Question number must be between 1 and {self.question_matrix.total_questions}"
            )
        return self.question_matrix.statuses[number - 1]

    def _mark_matrix_active(self, number: int) -> None:
        item = self._matrix_status(number)
        item.update({"status": "active", "winner_side": None, "phase": self.round.phase})
        self.question_matrix.current_question_num = number
        self._set_active_turn(number)
        self.question_matrix.recalculate()

    def _record_undo_snapshot(self, action: str) -> None:
        self._undo_stack.append(
            {
                "action": action,
                "current_match": copy.deepcopy(self.current_match),
                "teams": copy.deepcopy(self.teams),
                "round": copy.deepcopy(self.round),
                "question": copy.deepcopy(self.question),
                "buzzers": copy.deepcopy(self.buzzers),
                "question_matrix": copy.deepcopy(self.question_matrix),
                "used_question_numbers": list(self.used_question_numbers),
                "question_bank_warning": self.question_bank_warning,
                "rapid_fire_started_at": self._rapid_fire_started_at,
                "rapid_fire_durations": list(self._rapid_fire_durations),
                "rapid_fire_streak": self._rapid_fire_streak,
                "log": list(self.log),
            }
        )
        self._undo_stack = self._undo_stack[-5:]

    def undo_last_action(self) -> Dict[str, Any]:
        if not self._undo_stack:
            raise ValueError("No undoable action is available")
        snapshot = self._undo_stack.pop()
        self.current_match = snapshot["current_match"]
        self.teams = snapshot["teams"]
        self.round = snapshot["round"]
        self.question = snapshot["question"]
        self.buzzers = snapshot["buzzers"]
        self.question_matrix = snapshot["question_matrix"]
        self.used_question_numbers = snapshot["used_question_numbers"]
        self.question_bank_warning = snapshot["question_bank_warning"]
        self._rapid_fire_started_at = snapshot["rapid_fire_started_at"]
        self._rapid_fire_durations = snapshot["rapid_fire_durations"]
        self._rapid_fire_streak = snapshot["rapid_fire_streak"]
        self.log = snapshot["log"]
        self._log_action("undo_last_action", {"reverted_action": snapshot["action"]})
        return {"undone": snapshot["action"]}

    def mark_question_won(self, team_id: str) -> Dict[str, Any]:
        if not self.question_matrix.current_question_num:
            # Spoken-matrix mode: no matrix slot active yet — skip matrix update silently
            return self.question_matrix.to_dict()
        if not self.current_match or team_id not in (
            self.current_match.team_a_id,
            self.current_match.team_b_id,
        ):
            raise ValueError("Team is not in the active match")
        side = "A" if team_id == self.current_match.team_a_id else "B"
        item = self._matrix_status(self.question_matrix.current_question_num)
        item.update({"status": "won", "winner_side": side, "phase": self.round.phase})
        self.question_matrix.recalculate()
        return self.question_matrix.to_dict()

    def mark_question_dead(self, record_undo: bool = True) -> Dict[str, Any]:
        if record_undo:
            self._record_undo_snapshot("mark_question_dead")
        if not self.question_matrix.current_question_num:
            # Spoken-matrix mode: no matrix slot active — skip silently
            return self.question_matrix.to_dict()
        item = self._matrix_status(self.question_matrix.current_question_num)
        item.update({"status": "dead", "winner_side": None, "phase": self.round.phase})
        self.question_matrix.recalculate()
        return self.question_matrix.to_dict()

    def reset_question_matrix(self) -> Dict[str, Any]:
        self.question_matrix = QuestionMatrixState(
            total_questions=self.question_matrix.total_questions,
            routing_mode=self.round.routing_mode,
            turn_start_side=self.round.turn_start_side,
            team_block_size=self.round.team_block_size,
        )
        self._log_action("reset_question_matrix")
        return self.question_matrix.to_dict()

    def buzz(self, team_id: str, timestamp: Optional[float] = None) -> Dict[str, Any]:
        """Registers a buzz from a team.
        Rules:
        - Server decides by arrival order. First valid press locks buzzers for everyone else.
        - Only active match teams can buzz.
        - If buzzers are locked or first_team already set, buzz is rejected.
        - If question was passed to other team after wrong answer, only passed_to_team can buzz.
        - If team already attempted this question, buzz is rejected.
        """
        if not self.current_match:
            raise ValueError("No active match configured")
        if not self.question.is_open:
            raise ValueError("No question is currently open for buzzing")
        if self.round.phase not in (RoundPhase.BUZZER_BATTLE.value, RoundPhase.SUDDEN_DEATH.value):
            raise ValueError(f"Buzzing is not allowed during phase '{self.round.phase}'")
        if team_id not in (self.current_match.team_a_id, self.current_match.team_b_id):
            raise ValueError(f"Team '{team_id}' is not in current match")
        if self.buzzers.locked:
            raise ValueError("Buzzers are currently locked")
        if self.buzzers.first_team is not None:
            raise ValueError(f"Team '{self.buzzers.first_team}' has already buzzed first")
        if self.buzzers.passed_to_team and team_id != self.buzzers.passed_to_team:
            raise ValueError(f"Question is passed exclusively to '{self.buzzers.passed_to_team}'")
        if team_id in self.buzzers.attempted_teams:
            raise ValueError(f"Team '{team_id}' has already attempted this question")

        ts = timestamp if timestamp is not None else time.time()

        # Atomic lock
        self.buzzers.first_team = team_id
        self.buzzers.press_timestamp = ts
        self.buzzers.locked = True

        self._log_action("buzz", {"team_id": team_id, "timestamp": ts})
        return {
            "success": True,
            "team_id": team_id,
            "press_timestamp": ts,
        }

    def confirm_first_buzz(self, team_id: Optional[str] = None) -> Dict[str, Any]:
        """Moderator confirms the first buzz. (Decision is final)."""
        if team_id == "clear":
            self.buzzers.first_team = None
            self.buzzers.press_timestamp = None
            self.buzzers.locked = False
            self._log_action("clear_first_buzz")
            return {"confirmed_team": None, "cleared": True}
        selected_team = team_id or self.buzzers.first_team
        if not selected_team:
            raise ValueError("No team has buzzed to confirm")
        if selected_team not in (
            self.current_match.team_a_id if self.current_match else None,
            self.current_match.team_b_id if self.current_match else None,
        ):
            raise ValueError("No valid team has buzzed to confirm")

        if team_id:
            self.buzzers.first_team = team_id
            self.buzzers.locked = True
        team_id = self.buzzers.first_team
        self._log_action("confirm_first_buzz", {"team_id": team_id})
        return {"confirmed_team": team_id}

    def mark_correct(self, team_id: Optional[str] = None) -> Dict[str, Any]:
        """Marks current question as answered correctly.
        Scoring:
        - Rapid Fire: +10 pts (no negative marking)
        - Buzzer Battle: +15 pts
        - Sudden Death: +15 pts, first correct answer immediately wins match!

        Note: In spoken-matrix mode (BUZZER_BATTLE / SUDDEN_DEATH) the
        current_question card may be None when Q1 was armed directly by
        start_buzzer_battle / start_sudden_death without an open_question call.
        In that case we fall back to phase-appropriate default points.
        """
        if not self.current_match:
            raise ValueError("No active match configured")
        if not self._score_action_allowed("mark_correct", team_id):
            return {"status": "DUPLICATE_IGNORED", "duplicate": True, "team_id": team_id}
        phase = self.round.phase
        # Allow spoken-matrix mode: buzzer phases with is_open=True but no card
        buzzer_spoken = phase in (RoundPhase.BUZZER_BATTLE.value, RoundPhase.SUDDEN_DEATH.value)
        if not self.question.is_open:
            raise ValueError("No open question to mark correct")
        if not self.question.current_question and not buzzer_spoken:
            raise ValueError("No open question to mark correct")

        self._record_undo_snapshot("mark_correct")
        phase = self.round.phase
        target_team: Optional[str] = None

        if phase == RoundPhase.RAPID_FIRE.value:
            target_team = team_id or self.round.active_team_id
            if not target_team:
                raise ValueError("No active team set for Rapid Fire")
            points = RAPID_FIRE_CORRECT_POINTS
        elif phase in (RoundPhase.BUZZER_BATTLE.value, RoundPhase.SUDDEN_DEATH.value):
            target_team = team_id or self.buzzers.first_team or self.buzzers.passed_to_team
            if not target_team:
                raise ValueError("No team selected (no buzz registered)")
            points = BUZZER_CORRECT_POINTS
        else:
            target_team = team_id or self.current_match.team_a_id
            points = RAPID_FIRE_CORRECT_POINTS

        # Award points
        old_score = self.current_match.scores.get(target_team, 0)
        new_score = old_score + points
        self.current_match.scores[target_team] = new_score
        self._set_team_score(target_team, new_score)
        self._bump_match_stat(
            target_team,
            "rapid_fire_points" if phase == RoundPhase.RAPID_FIRE.value else "buzzer_points",
            points,
        )
        self._bump_match_stat(target_team, "questions_answered", 1)
        self._refresh_completed_history()

        # Close question and reveal answer
        self.question.is_open = False
        self.question.revealed = True
        self.buzzers.locked = True
        self.mark_question_won(target_team)
        if phase == RoundPhase.RAPID_FIRE.value:
            if self._rapid_fire_started_at is not None:
                self._rapid_fire_durations.append(max(0.0, time.time() - self._rapid_fire_started_at))
            self._rapid_fire_streak += 1

        self._log_action(
            "mark_correct",
            {
                "team_id": target_team,
                "points_added": points,
                "new_score": new_score,
                "phase": phase,
            },
        )

        result: Dict[str, Any] = {
            "status": "CORRECT",
            "team_id": target_team,
            "points_awarded": points,
            "new_score": new_score,
        }

        # Sudden Death resolution
        if phase == RoundPhase.SUDDEN_DEATH.value:
            # Rule: first correct answer wins the match!
            loser_id = (
                self.current_match.team_b_id
                if target_team == self.current_match.team_a_id
                else self.current_match.team_a_id
            )
            self._finalize_match(winner_id=target_team, loser_id=loser_id)
            result["sudden_death_winner"] = target_team

        return result

    def mark_wrong(self, team_id: Optional[str] = None) -> Dict[str, Any]:
        """Marks current question as answered wrong.
        Rules:
        - Rapid Fire: 0 pts (no negative marking). Question closes.
        - Buzzer Battle: -5 pts.
          Passes to the OTHER team only, without being reread.
          If both teams fail, question closes.
        - Sudden Death: passes to other team; if both fail, question closes (moderator opens next).

        Note: In spoken-matrix buzzer mode, current_question may be None.
        is_open=True is the authoritative signal.
        """
        if not self.current_match:
            raise ValueError("No active match configured")
        if not self._score_action_allowed("mark_wrong", team_id):
            return {"status": "DUPLICATE_IGNORED", "duplicate": True, "team_id": team_id}
        phase = self.round.phase
        buzzer_spoken = phase in (RoundPhase.BUZZER_BATTLE.value, RoundPhase.SUDDEN_DEATH.value)
        if not self.question.is_open:
            raise ValueError("No open question to mark wrong")
        if not self.question.current_question and not buzzer_spoken:
            raise ValueError("No open question to mark wrong")

        self._record_undo_snapshot("mark_wrong")
        if phase == RoundPhase.RAPID_FIRE.value:
            self._rapid_fire_streak = 0
            if self._rapid_fire_started_at is not None:
                self._rapid_fire_durations.append(max(0.0, time.time() - self._rapid_fire_started_at))
        target_team: Optional[str] = None

        if phase == RoundPhase.RAPID_FIRE.value:
            target_team = team_id or self.round.active_team_id
            if not target_team:
                raise ValueError("No active team set for Rapid Fire")
            # Rapid Fire: 0 points, no penalty
            self.question.is_open = False
            self._bump_match_stat(target_team, "questions_answered", 1)
            self._refresh_completed_history()
            self.mark_question_dead(record_undo=False)
            self._log_action("mark_wrong", {"team_id": target_team, "penalty": 0, "phase": phase})
            return {"status": "WRONG", "team_id": target_team, "penalty": 0, "question_closed": True}

        elif phase in (RoundPhase.BUZZER_BATTLE.value, RoundPhase.SUDDEN_DEATH.value):
            target_team = team_id or self.buzzers.first_team or self.buzzers.passed_to_team
            if not target_team:
                raise ValueError("No team selected (no buzz registered)")

            penalty = BUZZER_WRONG_PENALTY
            if penalty > 0:
                old_score = self.current_match.scores.get(target_team, 0)
                new_score = old_score - penalty
                self.current_match.scores[target_team] = new_score
                self._set_team_score(target_team, new_score)
                self._bump_match_stat(target_team, "buzzer_points", -penalty)
            self._bump_match_stat(target_team, "questions_answered", 1)
            self._refresh_completed_history()

            self.buzzers.penalised_team = target_team
            if target_team not in self.buzzers.attempted_teams:
                self.buzzers.attempted_teams.append(target_team)

            # Determine other team
            other_team = (
                self.current_match.team_b_id
                if target_team == self.current_match.team_a_id
                else self.current_match.team_a_id
            )

            # Check if other team has not attempted yet
            if other_team and other_team not in self.buzzers.attempted_teams:
                # Pass to other team without rereading
                self.buzzers.passed_to_team = other_team
                self.buzzers.first_team = None
                self.buzzers.locked = False  # Unlocked exclusively for the other team
                self._log_action(
                    "mark_wrong",
                    {
                        "team_id": target_team,
                        "penalty": penalty,
                        "passed_to": other_team,
                        "phase": phase,
                    },
                )
                return {
                    "status": "WRONG",
                    "penalised_team": target_team,
                    "penalty": penalty,
                    "passed_to": other_team,
                    "question_closed": False,
                }
            else:
                # Both teams have failed! Question closes.
                self.question.is_open = False
                self.buzzers.locked = True
                self.buzzers.passed_to_team = None
                self.mark_question_dead(record_undo=False)
                self._log_action(
                    "mark_wrong",
                    {
                        "team_id": target_team,
                        "penalty": penalty,
                        "passed_to": None,
                        "both_failed": True,
                        "phase": phase,
                    },
                )
                return {
                    "status": "WRONG",
                    "penalised_team": target_team,
                    "penalty": penalty,
                    "both_failed": True,
                    "question_closed": True,
                }

        else:
            self.question.is_open = False
            return {"status": "WRONG", "question_closed": True}

    def reveal_answer(self) -> None:
        """Reveals the answer for current question."""
        if not self.question.current_question:
            raise ValueError("No question currently active")
        self.question.revealed = True
        self._log_action("reveal_answer", {"question_number": self.question.current_question.number})

    def apply_violation(
        self,
        team_id: str,
        violation: str,
        penalty: int = 0,
    ) -> Dict[str, Any]:
        if not self.current_match or team_id not in (
            self.current_match.team_a_id,
            self.current_match.team_b_id,
        ):
            raise ValueError("Team is not in the active match")
        self._record_undo_snapshot("foul_penalty" if penalty else "warning_logged")
        allowed = {"No Mic", "Audience Coaching", "Buzzer Interference", "Speaker Violation"}
        if violation not in allowed:
            raise ValueError("Invalid violation reason")
        if penalty:
            old_score = self.current_match.scores.get(team_id, 0)
            new_score = old_score - abs(int(penalty))
            self.current_match.scores[team_id] = new_score
            self._set_team_score(team_id, new_score)
            self._bump_match_stat(team_id, "foul_penalties", abs(int(penalty)))
            self._refresh_completed_history()
        action = "foul_penalty" if penalty else "warning_logged"
        self._log_action(
            action,
            {"team_id": team_id, "violation": violation, "penalty": abs(int(penalty))},
        )
        return {"team_id": team_id, "violation": violation, "penalty": abs(int(penalty))}

    def lock_buzzers(self) -> None:
        """Locks buzzers."""
        self.buzzers.locked = True
        self._log_action("lock_buzzers")

    def unlock_buzzers(self) -> None:
        """Unlocks buzzers for the current question."""
        if not self.question.is_open:
            raise ValueError("Cannot unlock buzzers when no question is open")
        self.buzzers.locked = False
        self.buzzers.first_team = None
        self._log_action("unlock_buzzers")

    def next_question(self, question_card: Optional[QuestionCard] = None) -> Dict[str, Any]:
        """Closes current question and opens next question."""
        return self.open_question(question_card)

    def previous_question(self) -> Dict[str, Any]:
        """Reopens the most recently opened question before the current one."""
        current_number = self.question.current_question.number if self.question.current_question else None
        opened_numbers = [
            entry.details.get("question_number")
            for entry in self.log
            if entry.action == "open_question"
        ]
        previous_numbers = [
            number for number in opened_numbers
            if number is not None and number != current_number
        ]
        if not previous_numbers:
            raise ValueError("No previous question is available")

        previous_number = previous_numbers[-1]
        card = next(
            (question for question in self.question_provider.list_questions()
             if question.number == previous_number),
            None,
        )
        if card is None:
            raise ValueError(f"Question #{previous_number} is no longer available")

        points = card.points
        if self.round.phase == RoundPhase.RAPID_FIRE.value:
            points = 10
        elif self.round.phase in (RoundPhase.BUZZER_BATTLE.value, RoundPhase.SUDDEN_DEATH.value):
            points = 15
        self.question = QuestionState(
            current_question=QuestionCard(
                number=card.number,
                type=card.type,
                text=card.text,
                image=card.image,
                answer=card.answer,
                points=points,
            ),
            revealed=False,
            is_open=True,
        )
        self.buzzers = BuzzersState(
            locked=self.round.phase not in (RoundPhase.BUZZER_BATTLE.value, RoundPhase.SUDDEN_DEATH.value)
        )
        self._log_action("previous_question", {"question_number": previous_number})
        return {"question_number": previous_number}

    def start_sudden_death(self) -> None:
        """Starts Sudden Death phase.
        Rule: "Tie at match end: SUDDEN_DEATH with buzzer questions; first correct answer wins."
        Fix: Arms Q1 immediately — buzzers unlocked and question open from the start.
        """
        if not self.current_match:
            raise ValueError("No active match configured")

        self.round.phase = RoundPhase.SUDDEN_DEATH.value
        self._spoken_matrix_mode = True
        self.round.timer_running = False
        self.round.timer_seconds_remaining = 0
        # Arm Q1 immediately
        self.question = QuestionState(is_open=True)
        self.buzzers = BuzzersState(
            locked=False,
            first_team=None,
            press_timestamp=None,
            penalised_team=None,
            passed_to_team=None,
            attempted_teams=[],
        )

        self._log_action("start_sudden_death", {"match_number": self.match_number, "q1_armed": True})

    def end_match(self) -> Dict[str, Any]:
        """Ends current match and determines winner/loser.
        Rules:
        - Match winner: highest combined score.
        - Tie at match end: SUDDEN_DEATH with buzzer questions; first correct answer wins.
        - If tied, transitions to SUDDEN_DEATH automatically.
        - If not tied, finalizes match, updates bracket, handles wild cards / round advancement.
        """
        if not self.current_match:
            raise ValueError("No active match configured")

        t_a = self.current_match.team_a_id
        t_b = self.current_match.team_b_id
        if not t_a or not t_b:
            raise ValueError("Current match is missing teams")

        score_a = self.current_match.scores.get(t_a, 0)
        score_b = self.current_match.scores.get(t_b, 0)

        if score_a == score_b:
            # Match is tied! Transition to sudden death.
            self.start_sudden_death()
            return {
                "status": "TIED",
                "message": "Match ended in a tie. Starting SUDDEN_DEATH.",
                "scores": {t_a: score_a, t_b: score_b},
            }

        winner_id = t_a if score_a > score_b else t_b
        loser_id = t_b if score_a > score_b else t_a

        self._finalize_match(winner_id=winner_id, loser_id=loser_id)
        return {
            "status": "COMPLETED",
            "winner_id": winner_id,
            "loser_id": loser_id,
            "scores": {t_a: score_a, t_b: score_b},
        }

    def advance_winner(self, match_number: Any, winner_id: Optional[str] = None) -> Dict[str, Any]:
        """Advances the winner of a specific bracket match (M1-M13) to the next round.
        If winner_id is omitted or empty, auto-determines from match scores; raises ValueError if tied.
        """
        try:
            m_num = int(match_number)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid match_number '{match_number}'")

        match = next((m for m in self.bracket.matches if m.match_number == m_num), None)
        if not match:
            raise ValueError(f"Match M{m_num:02d} not found in bracket")

        t_a = match.team_a_id
        t_b = match.team_b_id
        if not t_a or not t_b:
            raise ValueError(f"Match M{m_num:02d} is missing teams and cannot be advanced yet")

        # Sync live scores if this is the active match
        if self.current_match and self.current_match.match_number == m_num:
            match.scores = dict(self.current_match.scores)

        score_a = int(match.scores.get(t_a, 0))
        score_b = int(match.scores.get(t_b, 0))

        normalized_winner = str(winner_id).strip() if winner_id else ""
        if normalized_winner:
            if normalized_winner not in (t_a, t_b):
                raise ValueError(f"winner_id '{normalized_winner}' is not a participant in M{m_num:02d}")
            resolved_winner = normalized_winner
        else:
            if score_a > score_b:
                resolved_winner = t_a
            elif score_b > score_a:
                resolved_winner = t_b
            else:
                raise ValueError(
                    f"Match M{m_num:02d} is tied ({score_a}–{score_b}). Break the tie or specify winner_id before advancing."
                )

        resolved_loser = t_b if resolved_winner == t_a else t_a

        if self.current_match and self.current_match.match_number == m_num:
            self._finalize_match(winner_id=resolved_winner, loser_id=resolved_loser)
        else:
            was_completed = match.status == "COMPLETED"
            match.winner_id = resolved_winner
            match.loser_id = resolved_loser
            match.status = "COMPLETED"
            if not was_completed:
                if resolved_winner in self.teams:
                    self.teams[resolved_winner].win_loss["wins"] += 1
                    self.teams[resolved_winner].matches_played += 1
                if resolved_loser in self.teams:
                    self.teams[resolved_loser].win_loss["losses"] += 1
                    self.teams[resolved_loser].matches_played += 1
            self._check_bracket_progression()

        self._log_action(
            "advance_winner",
            {
                "match_number": m_num,
                "winner_id": resolved_winner,
                "loser_id": resolved_loser,
                "scores": {t_a: score_a, t_b: score_b},
            },
        )

        return {
            "status": "COMPLETED",
            "match_number": m_num,
            "winner_id": resolved_winner,
            "loser_id": resolved_loser,
            "scores": {t_a: score_a, t_b: score_b},
            "champion": self.bracket.champion,
        }

    def _finalize_match(self, winner_id: str, loser_id: str) -> None:
        """Marks match completed, updates win/loss and cumulative ledgers."""
        if not self.current_match:
            return

        was_completed = self.current_match.status == "COMPLETED"
        self.current_match.winner_id = winner_id
        self.current_match.loser_id = loser_id
        self.current_match.status = "COMPLETED"
        self.current_match.ensure_stats([winner_id, loser_id])

        if not was_completed:
            self.teams[winner_id].win_loss["wins"] += 1
            self.teams[loser_id].win_loss["losses"] += 1
            self.teams[winner_id].matches_played += 1
            self.teams[loser_id].matches_played += 1

        self.round.phase = RoundPhase.RESULT.value
        self.round.timer_running = False
        self.buzzers.locked = True
        self.question.is_open = False

        self._upsert_match_history(winner_id, "WIN")
        self._upsert_match_history(loser_id, "LOSS")

        self._log_action(
            "end_match",
            {
                "match_number": self.match_number,
                "winner": winner_id,
                "loser": loser_id,
                "scores": dict(self.current_match.scores),
            },
        )

        self._check_bracket_progression()
        self._save_match_snapshot()

    def admin_adjust_score(self, team_id: str, delta: int, reason: str = "") -> Dict[str, Any]:
        """Admin manual score adjustment.
        Can be positive or negative integer.
        """
        if not self.current_match:
            raise ValueError("No active match configured")
        if team_id not in self.teams:
            raise ValueError(f"Team '{team_id}' does not exist")
        self._record_undo_snapshot("admin_adjust_score")

        old_score = self.current_match.scores.get(team_id, 0)
        new_score = old_score + delta
        self.current_match.scores[team_id] = new_score
        self._set_team_score(team_id, new_score)
        self._refresh_completed_history()

        self._log_action(
            "admin_adjust_score",
            {
                "team_id": team_id,
                "delta": delta,
                "old_score": old_score,
                "new_score": new_score,
                "reason": reason,
            },
        )
        return {"team_id": team_id, "delta": delta, "new_score": new_score, "reason": reason}

    def reset_match(self) -> None:
        """Resets the current match state, scores, and round to initial IDLE state."""
        if not self.current_match:
            raise ValueError("No active match configured")

        t_a = self.current_match.team_a_id
        t_b = self.current_match.team_b_id

        if t_a:
            self.current_match.scores[t_a] = 0
            self._set_team_score(t_a, 0)
        if t_b:
            self.current_match.scores[t_b] = 0
            self._set_team_score(t_b, 0)
        self.current_match.ensure_stats([t_a, t_b])
        for team_id in (t_a, t_b):
            if team_id:
                self.current_match.stats[team_id] = {key: 0 for key in MATCH_STAT_KEYS}
                self.teams[team_id].match_history = [
                    row for row in self.teams[team_id].match_history
                    if int(row.get("match_number", -1)) != self.match_number
                ]

        self.current_match.winner_id = None
        self.current_match.loser_id = None
        self.current_match.status = "IN_PROGRESS"

        self.round = RoundState(phase=RoundPhase.IDLE.value, timer_seconds_remaining=0, timer_running=False)
        self.question = QuestionState()
        self.buzzers = BuzzersState(locked=True)
        self.question_matrix = QuestionMatrixState(
            total_questions=self.question_matrix.total_questions,
            routing_mode=self.round.routing_mode,
            turn_start_side=self.round.turn_start_side,
            team_block_size=self.round.team_block_size,
        )
        self._rapid_fire_started_at = None
        self._rapid_fire_durations = []
        self._rapid_fire_streak = 0
        self._last_score_guard_key = ""
        self._last_score_guard_at = 0.0

        self._log_action("reset_match", {"match_number": self.match_number})

    def reset_round(self) -> Dict[str, Any]:
        """Return the active round to idle without changing match scores."""
        self.round.phase = RoundPhase.IDLE.value
        self.round.active_team_id = None
        self.round.timer_seconds_remaining = 0
        self.round.timer_running = False
        self.question = QuestionState()
        self.buzzers = BuzzersState(locked=True)
        self._log_action("reset_round", {"match_number": self.match_number})
        return {"reset": True}

    # -------------------------------------------------------------------------
    # Bracket Progression & Wild Card Resolution
    # -------------------------------------------------------------------------

    def _check_bracket_progression(self) -> None:
        """Checks if current stage is completed and advances bracket accordingly."""
        # 1. Qualifiers (Matches 1-6) — only evaluate once (guard with wild_cards)
        qual_matches = [m for m in self.bracket.matches if m.stage == Stage.QUALIFIER.value]
        if (
            len(qual_matches) == 6
            and all(m.status == "COMPLETED" for m in qual_matches)
            and not self.bracket.qualifier_winners
        ):
            winners = [m.winner_id for m in qual_matches if m.winner_id]
            losers = [m.loser_id for m in qual_matches if m.loser_id]
            self.bracket.qualifier_winners = winners
            self.bracket.qualifier_losers = losers

            # Evaluate wild cards: 2 highest-scoring losers
            self._evaluate_qualifier_wild_cards(qual_matches)

        # 2. Quarterfinals (Matches 7-10)
        qf_matches = [m for m in self.bracket.matches if m.stage == Stage.QUARTERFINAL.value]
        if len(qf_matches) == 4 and all(m.status == "COMPLETED" for m in qf_matches):
            # Populate Semifinals (Matches 11-12)
            # M11: Winner M7 vs Winner M8
            # M12: Winner M9 vs Winner M10
            m7 = next(m for m in qf_matches if m.match_number == 7)
            m8 = next(m for m in qf_matches if m.match_number == 8)
            m9 = next(m for m in qf_matches if m.match_number == 9)
            m10 = next(m for m in qf_matches if m.match_number == 10)

            m11 = next(m for m in self.bracket.matches if m.match_number == 11)
            m12 = next(m for m in self.bracket.matches if m.match_number == 12)

            m11.team_a_id = m7.winner_id
            m11.team_b_id = m8.winner_id
            m11.scores = {m11.team_a_id: 0, m11.team_b_id: 0} if m11.team_a_id and m11.team_b_id else {}

            m12.team_a_id = m9.winner_id
            m12.team_b_id = m10.winner_id
            m12.scores = {m12.team_a_id: 0, m12.team_b_id: 0} if m12.team_a_id and m12.team_b_id else {}

        # 3. Semifinals (Matches 11-12)
        sf_matches = [m for m in self.bracket.matches if m.stage == Stage.SEMIFINAL.value]
        if len(sf_matches) == 2 and all(m.status == "COMPLETED" for m in sf_matches):
            m11 = next(m for m in sf_matches if m.match_number == 11)
            m12 = next(m for m in sf_matches if m.match_number == 12)
            m13 = next(m for m in self.bracket.matches if m.match_number == 13)

            m13.team_a_id = m11.winner_id
            m13.team_b_id = m12.winner_id
            m13.scores = {m13.team_a_id: 0, m13.team_b_id: 0} if m13.team_a_id and m13.team_b_id else {}

        # 4. Final (Match 13)
        final_match = next((m for m in self.bracket.matches if m.match_number == 13), None)
        if final_match and final_match.status == "COMPLETED":
            self.bracket.champion = final_match.winner_id
            self._log_action("tournament_champion", {"champion": self.bracket.champion})

    def _evaluate_qualifier_wild_cards(self, qual_matches: List[MatchData]) -> None:
        """Determines the 2 highest-scoring losing teams from qualifier matches.
        Rule: "after all 6 qualifier matches, the 2 highest-scoring losing teams advance;
        a wild-card tie is resolved by a sudden-death question."
        """
        loser_scores: List[Tuple[str, int]] = []
        for m in qual_matches:
            if m.loser_id:
                score = m.scores.get(m.loser_id, 0)
                loser_scores.append((m.loser_id, score))

        # Sort descending by score
        loser_scores.sort(key=lambda x: x[1], reverse=True)

        if len(loser_scores) < 2:
            return

        # Check for ties around the 2nd wild card spot
        top1_team, top1_score = loser_scores[0]
        top2_team, top2_score = loser_scores[1]

        # Case 1: Tie for spot 1 and 2 (e.g. multiple teams tied at top)
        # Check if 3rd place has identical score to 2nd place
        if len(loser_scores) > 2 and loser_scores[2][1] == top2_score:
            # We have a tie involving the 2nd wild card spot!
            tied_teams = [t for t, s in loser_scores if s == top2_score]
            if top1_score > top2_score:
                # top1 is safe as WC1
                self.bracket.wild_cards = [top1_team]
            else:
                self.bracket.wild_cards = []

            self.bracket.wild_card_tied_teams = tied_teams
            self._log_action("wild_card_tie_detected", {"tied_teams": tied_teams, "score": top2_score})
            return

        # No tie: top 2 advance directly
        self.bracket.wild_cards = [top1_team, top2_team]
        self.bracket.wild_card_tied_teams = []
        self._populate_quarterfinals(self.bracket.qualifier_winners, self.bracket.wild_cards)

    def resolve_wild_card_tie(self, winning_team_id: str) -> None:
        """Resolves wild card tie following sudden death question."""
        if not self.bracket.wild_card_tied_teams:
            raise ValueError("No active wild card tie to resolve")
        if winning_team_id not in self.bracket.wild_card_tied_teams:
            raise ValueError(f"Team '{winning_team_id}' is not among tied wild card teams")

        if winning_team_id not in self.bracket.wild_cards:
            self.bracket.wild_cards.append(winning_team_id)

        # If we need 2 wild cards and only had 1 before, we now have 2!
        if len(self.bracket.wild_cards) < 2 and len(self.bracket.wild_card_tied_teams) > 1:
            # Remove winner from tied list; if remaining need another tiebreak, leave them
            self.bracket.wild_card_tied_teams.remove(winning_team_id)

        if len(self.bracket.wild_cards) == 2:
            self.bracket.wild_card_tied_teams = []
            self._populate_quarterfinals(self.bracket.qualifier_winners, self.bracket.wild_cards)

        self._log_action(
            "resolve_wild_card_tie",
            {"winner": winning_team_id, "wild_cards": self.bracket.wild_cards},
        )

    def _populate_quarterfinals(self, winners: List[str], wild_cards: List[str]) -> None:
        """Populates the 4 quarterfinal matches (Matches 7 to 10).
        8 teams = 6 winners (W1..W6) + 2 wild cards (WC1, WC2).
        Seeding:
        - Match 7:  W1 vs WC2
        - Match 8:  W2 vs W5
        - Match 9:  W3 vs WC1
        - Match 10: W4 vs W6
        """
        if len(winners) < 6 or len(wild_cards) < 2:
            return

        w = winners
        wc = wild_cards

        pairings = [
            (7, w[0], wc[1]),
            (8, w[1], w[4]),
            (9, w[2], wc[0]),
            (10, w[3], w[5]),
        ]

        for m_num, t_a, t_b in pairings:
            m = next(m for m in self.bracket.matches if m.match_number == m_num)
            m.team_a_id = t_a
            m.team_b_id = t_b
            m.scores = {t_a: 0, t_b: 0}
            m.status = "PENDING"

        self._log_action(
            "populate_quarterfinals",
            {"pairings": [{"match": p[0], "team_a": p[1], "team_b": p[2]} for p in pairings]},
        )

    def override_quarterfinal_pairings(self, pairings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Allows an admin to manually set or override the quarterfinal pairings (Matches 7 to 10).
        Each pairing must specify match_number (7..10), team_a_id, and team_b_id.
        All teams must be valid, unique across matches, and distinct within each match.
        """
        if not pairings:
            raise ValueError("Pairings list cannot be empty")

        seen_teams = set()
        seen_matches = set()

        for p in pairings:
            m_num = int(p.get("match_number", 0))
            t_a = p.get("team_a_id")
            t_b = p.get("team_b_id")

            if m_num not in (7, 8, 9, 10):
                raise ValueError(f"Match number {m_num} is not a quarterfinal match (7-10)")
            if m_num in seen_matches:
                raise ValueError(f"Duplicate match number {m_num} in pairings")
            seen_matches.add(m_num)

            if not t_a or t_a not in self.teams:
                raise ValueError(f"Invalid or missing team_a_id: '{t_a}'")
            if not t_b or t_b not in self.teams:
                raise ValueError(f"Invalid or missing team_b_id: '{t_b}'")
            if t_a == t_b:
                raise ValueError(f"Team A and Team B cannot be identical ({t_a}) in match {m_num}")
            if t_a in seen_teams:
                raise ValueError(f"Team '{t_a}' appears in multiple quarterfinal matches")
            if t_b in seen_teams:
                raise ValueError(f"Team '{t_b}' appears in multiple quarterfinal matches")

            seen_teams.add(t_a)
            seen_teams.add(t_b)

        # Apply pairings to bracket matches
        for p in pairings:
            m_num = int(p["match_number"])
            m = next((m for m in self.bracket.matches if m.match_number == m_num), None)
            if not m:
                m = MatchData(match_number=m_num, stage=Stage.QUARTERFINAL.value)
                self.bracket.matches.append(m)
            m.team_a_id = p["team_a_id"]
            m.team_b_id = p["team_b_id"]
            m.stage = Stage.QUARTERFINAL.value
            m.scores = {p["team_a_id"]: 0, p["team_b_id"]: 0}
            m.status = "PENDING"
            m.winner_id = None
            m.loser_id = None

        self._log_action("override_quarterfinal_pairings", {"pairings": pairings})
        return {"status": "SUCCESS", "pairings": pairings}

    def get_tournament_progress(self) -> Dict[str, Any]:
        """Calculates comprehensive tournament progress, completed results, and standings."""
        total_matches = len(self.bracket.matches) if self.bracket.matches else 13
        completed_matches = [m for m in self.bracket.matches if m.status == "COMPLETED"]
        completed_count = len(completed_matches)
        percent = int(round((completed_count / total_matches) * 100)) if total_matches else 0

        # Stage breakdown
        stages = {
            "qualifiers": {
                "done": len([m for m in self.bracket.matches if m.match_number in range(1, 7) and m.status == "COMPLETED"]),
                "total": 6,
            },
            "quarterfinals": {
                "done": len([m for m in self.bracket.matches if m.match_number in range(7, 11) and m.status == "COMPLETED"]),
                "total": 4,
            },
            "semifinals": {
                "done": len([m for m in self.bracket.matches if m.match_number in range(11, 13) and m.status == "COMPLETED"]),
                "total": 2,
            },
            "final": {
                "done": len([m for m in self.bracket.matches if m.match_number == 13 and m.status == "COMPLETED"]),
                "total": 1,
            },
        }

        # Next ready match calculation
        next_ready = None
        curr_num = self.match_number if self.current_match else 0
        candidate_matches = [
            m for m in self.bracket.matches
            if m.status != "COMPLETED" and m.team_a_id and m.team_b_id and m.match_number > curr_num
        ]
        if not candidate_matches:
            candidate_matches = [
                m for m in self.bracket.matches
                if m.status != "COMPLETED" and m.team_a_id and m.team_b_id and (m.match_number != curr_num or (self.current_match and self.current_match.status == "COMPLETED"))
            ]

        if candidate_matches:
            nm = candidate_matches[0]
            next_ready = {
                "match_number": nm.match_number,
                "stage": nm.stage,
                "team_a_id": nm.team_a_id,
                "team_b_id": nm.team_b_id,
                "team_a_name": self.teams[nm.team_a_id].name if nm.team_a_id in self.teams else nm.team_a_id,
                "team_b_name": self.teams[nm.team_b_id].name if nm.team_b_id in self.teams else nm.team_b_id,
            }

        # Completed results
        completed_results = []
        for m in sorted(completed_matches, key=lambda x: x.match_number):
            w_name = self.teams[m.winner_id].name if (m.winner_id and m.winner_id in self.teams) else (m.winner_id or "")
            l_name = self.teams[m.loser_id].name if (m.loser_id and m.loser_id in self.teams) else (m.loser_id or "")
            t_a_name = self.teams[m.team_a_id].name if (m.team_a_id and m.team_a_id in self.teams) else (m.team_a_id or "")
            t_b_name = self.teams[m.team_b_id].name if (m.team_b_id and m.team_b_id in self.teams) else (m.team_b_id or "")
            completed_results.append({
                "match_number": m.match_number,
                "stage": m.stage,
                "team_a_id": m.team_a_id,
                "team_b_id": m.team_b_id,
                "team_a_name": t_a_name,
                "team_b_name": t_b_name,
                "score_a": m.scores.get(m.team_a_id, 0) if m.team_a_id else 0,
                "score_b": m.scores.get(m.team_b_id, 0) if m.team_b_id else 0,
                "winner_id": m.winner_id,
                "winner_name": w_name,
                "loser_id": m.loser_id,
                "loser_name": l_name,
            })

        # Standings: All 12 teams sorted by wins desc, total_score desc — enriched
        standings = []
        final_match = next((m for m in self.bracket.matches if m.match_number == 13), None)
        semi_match_nums = {11, 12}
        qf_match_nums = {7, 8, 9, 10}
        for t_id, team in self.teams.items():
            history = team.match_history
            rf_pts = sum(int(h.get("rapid_fire_points", 0)) for h in history)
            bz_pts = sum(int(h.get("buzzer_points", 0)) for h in history)
            fouls  = sum(int(h.get("foul_penalties", 0)) for h in history)
            # Live match contribution
            live_pts = 0
            if (self.current_match and self.current_match.status == "IN_PROGRESS"
                    and t_id in (self.current_match.team_a_id, self.current_match.team_b_id)):
                live_pts = int(self.current_match.scores.get(t_id, 0))
            # Status badge
            status = "ACTIVE"
            if self.bracket.champion == t_id:
                status = "CHAMPION"
            elif (final_match and final_match.status == "COMPLETED"
                  and t_id in (final_match.team_a_id, final_match.team_b_id)
                  and self.bracket.champion != t_id):
                status = "FINALIST"
            elif any(
                m.status == "COMPLETED" and m.winner_id == t_id and m.match_number in semi_match_nums
                for m in self.bracket.matches
            ) and self.bracket.champion != t_id and (
                not final_match or t_id not in (final_match.team_a_id, final_match.team_b_id)
            ):
                status = "SEMIFINALIST"
            elif any(
                m.status == "COMPLETED" and m.winner_id == t_id and m.match_number in qf_match_nums
                for m in self.bracket.matches
            ) and self.bracket.champion != t_id and not any(
                m.winner_id == t_id and m.match_number in semi_match_nums
                for m in self.bracket.matches
            ):
                status = "QUARTERFINALIST"
            elif t_id in self.bracket.wild_cards:
                status = "WILD_CARD"
            elif team.win_loss.get("losses", 0) > 0 and team.win_loss.get("wins", 0) == 0:
                status = "ELIMINATED"
            # In-match live badge
            in_live_match = (
                self.current_match is not None
                and self.current_match.status == "IN_PROGRESS"
                and t_id in (self.current_match.team_a_id, self.current_match.team_b_id)
            )
            standings.append({
                "team_id": t_id,
                "name": team.name,
                "designated_speaker": team.designated_speaker,
                "wins": team.win_loss.get("wins", 0),
                "losses": team.win_loss.get("losses", 0),
                "matches_played": team.matches_played,
                "total_points": team.total_points,
                "total_score": team.total_points,
                "rapid_fire_points": rf_pts,
                "buzzer_points": bz_pts,
                "foul_penalties": fouls,
                "live_match_points": live_pts,
                "in_live_match": in_live_match,
                "status": status,
                "accent_color": team.accent_color,
                "wild_card_qualified": t_id in self.bracket.wild_cards,
                "match_history": list(history),
            })
        standings.sort(key=lambda x: (x["wins"], x["total_score"]), reverse=True)
        for i, s in enumerate(standings):
            s["rank"] = i + 1

        # Highlights
        top_rf = max(standings, key=lambda x: x["rapid_fire_points"], default=None)
        top_bz = max(standings, key=lambda x: x["buzzer_points"], default=None)
        # Highest single-match score across all completed matches
        best_match_score = None
        for m in completed_matches:
            for t_id2 in (m.team_a_id, m.team_b_id):
                if t_id2:
                    sc = int(m.scores.get(t_id2, 0))
                    if best_match_score is None or sc > best_match_score["score"]:
                        best_match_score = {
                            "score": sc,
                            "team_id": t_id2,
                            "team_name": self.teams[t_id2].name if t_id2 in self.teams else t_id2,
                            "match_number": m.match_number,
                        }
        # Live match summary
        live_match_summary = None
        if self.current_match and self.current_match.status == "IN_PROGRESS":
            cm = self.current_match
            live_match_summary = {
                "match_number": cm.match_number,
                "stage": cm.stage,
                "team_a_id": cm.team_a_id,
                "team_b_id": cm.team_b_id,
                "team_a_name": self.teams[cm.team_a_id].name if cm.team_a_id in self.teams else cm.team_a_id,
                "team_b_name": self.teams[cm.team_b_id].name if cm.team_b_id in self.teams else cm.team_b_id,
                "score_a": int(cm.scores.get(cm.team_a_id, 0)) if cm.team_a_id else 0,
                "score_b": int(cm.scores.get(cm.team_b_id, 0)) if cm.team_b_id else 0,
                "phase": self.round.phase if self.round else None,
            }
        highlights = {
            "highest_match_score": best_match_score,
            "top_rapid_fire_team": {
                "team_id": top_rf["team_id"],
                "name": top_rf["name"],
                "points": top_rf["rapid_fire_points"],
            } if top_rf else None,
            "top_buzzer_team": {
                "team_id": top_bz["team_id"],
                "name": top_bz["name"],
                "points": top_bz["buzzer_points"],
            } if top_bz else None,
            "live_match": live_match_summary,
        }

        return {
            "total_matches": total_matches,
            "completed_matches": completed_count,
            "percent_complete": percent,
            "stages": stages,
            "next_ready_match": next_ready,
            "completed_results": completed_results,
            "standings": standings,
            "champion": self.bracket.champion,
            "wild_cards": list(self.bracket.wild_cards),
            "wild_card_tied_teams": list(self.bracket.wild_card_tied_teams),
            "highlights": highlights,
        }

    def advance_and_load_next(self) -> Dict[str, Any]:
        """Atomically completes the current match, advances the winner in the bracket,
        records per-team match_history, and automatically loads the next scheduled match."""
        if not self.current_match:
            raise ValueError("No active match configured")

        prev_match_num = self.match_number
        winner_id = self.current_match.winner_id

        # 1. Finalize if not already finalized
        if self.current_match.status != "COMPLETED":
            t_a = self.current_match.team_a_id
            t_b = self.current_match.team_b_id
            if not t_a or not t_b:
                raise ValueError("Current match is missing teams")

            score_a = self.current_match.scores.get(t_a, 0)
            score_b = self.current_match.scores.get(t_b, 0)

            if score_a == score_b:
                self.start_sudden_death()
                return {
                    "status": "TIED",
                    "message": "Match ended in a tie. Launching SUDDEN DEATH tie-breaker.",
                    "scores": {t_a: score_a, t_b: score_b},
                    "phase": RoundPhase.SUDDEN_DEATH.value,
                }

            winner_id = t_a if score_a > score_b else t_b
            loser_id = t_b if score_a > score_b else t_a
            self._finalize_match(winner_id=winner_id, loser_id=loser_id)

        # 2. Check if tournament champion is crowned
        if self.bracket.champion:
            champ_name = self.teams[self.bracket.champion].name if self.bracket.champion in self.teams else self.bracket.champion
            return {
                "advanced": True,
                "status": "TOURNAMENT_CHAMPION",
                "completed_match": prev_match_num,
                "winner_id": winner_id,
                "champion": self.bracket.champion,
                "champion_name": champ_name,
                "next_match": None,
                "message": f"Tournament Completed! Champion: {champ_name}",
            }

        # 3. Check for Wild-Card Tie following Qualifier Stage (Match 6)
        if self.bracket.wild_card_tied_teams:
            return {
                "advanced": True,
                "status": "WILD_CARD_TIE",
                "completed_match": prev_match_num,
                "winner_id": winner_id,
                "tied_teams": list(self.bracket.wild_card_tied_teams),
                "next_match": None,
                "message": f"Wild-card tie detected between teams: {', '.join(self.bracket.wild_card_tied_teams)}. Resolve tiebreak to advance.",
            }

        # 4. Find next ready match
        prog = self.get_tournament_progress()
        next_ready = prog.get("next_ready_match")
        if not next_ready:
            return {
                "advanced": True,
                "status": "AWAITING_TEAMS",
                "completed_match": prev_match_num,
                "winner_id": winner_id,
                "next_match": None,
                "message": "Match finalized. Waiting for next stage pairings to populate.",
            }

        next_match_num = next_ready["match_number"]
        next_stage = next_ready["stage"]
        next_team_a = next_ready["team_a_id"]
        next_team_b = next_ready["team_b_id"]

        self.setup_match(
            stage=next_stage,
            match_number=next_match_num,
            team_a_id=next_team_a,
            team_b_id=next_team_b,
        )

        self._log_action(
            "advance_and_load_next",
            {
                "completed_match": prev_match_num,
                "winner_id": winner_id,
                "loaded_match": next_match_num,
                "stage": next_stage,
                "team_a": next_team_a,
                "team_b": next_team_b,
            },
        )

        return {
            "advanced": True,
            "status": "NEXT_MATCH_LOADED",
            "completed_match": prev_match_num,
            "winner_id": winner_id,
            "next_match": next_match_num,
            "stage": next_stage,
            "team_a_id": next_team_a,
            "team_b_id": next_team_b,
            "team_a_name": next_ready["team_a_name"],
            "team_b_name": next_ready["team_b_name"],
        }

    def reset_scores_keep_roster(self) -> Dict[str, Any]:
        """Clears all match scores, bracket progress, audit logs, and team match histories back to zero,
        while preserving all 12 team names, speakers, members, and accent colors."""
        for t_id, team in self.teams.items():
            team.match_scores.clear()
            team.win_loss = {"wins": 0, "losses": 0}
            team.matches_played = 0
            team.match_history = []
            team.total_points = 0

        matches: List[MatchData] = []
        # Matches 1-6: Qualifiers
        for m in range(1, 7):
            t_a = f"team_{2*m - 1}"
            t_b = f"team_{2*m}"
            matches.append(
                MatchData(
                    match_number=m,
                    stage=Stage.QUALIFIER.value,
                    team_a_id=t_a if t_a in self.teams else None,
                    team_b_id=t_b if t_b in self.teams else None,
                    scores={t_a: 0, t_b: 0} if (t_a in self.teams and t_b in self.teams) else {},
                    status="PENDING",
                )
            )

        # Matches 7-10: Quarterfinals
        for m in range(7, 11):
            matches.append(MatchData(match_number=m, stage=Stage.QUARTERFINAL.value, scores={}, status="PENDING"))

        # Matches 11-12: Semifinals
        for m in range(11, 13):
            matches.append(MatchData(match_number=m, stage=Stage.SEMIFINAL.value, scores={}, status="PENDING"))

        # Match 13: Final
        matches.append(MatchData(match_number=13, stage=Stage.FINAL.value, scores={}, status="PENDING"))

        self.bracket = BracketData(matches=matches)
        self.used_question_numbers.clear()
        self.question_bank_warning = None
        self.log.clear()
        self.display_view = "auto"
        self.setup_match(Stage.QUALIFIER.value, 1, "team_1", "team_2")
        self._log_action("reset_scores_keep_roster", {"team_count": len(self.teams), "match_count": 13})
        return {"reset": True, "teams_kept": len(self.teams)}

    # -------------------------------------------------------------------------
    # State Serialization & Restoration
    # -------------------------------------------------------------------------

    def get_state(self) -> Dict[str, Any]:
        """Returns the full engine state dictionary matching the project spec."""
        return {
            "event": {
                "stage": self.stage,
                "match_number": self.match_number,
                "bracket": self.bracket.to_dict(),
            },
            "teams": {t_id: team.to_dict() for t_id, team in self.teams.items()},
            "current_match": self.current_match.to_dict() if self.current_match else None,
            "round": self.round.to_dict(),
            "question": self.question.to_dict(),
            "question_matrix": self.question_matrix.to_dict(),
            "routing": self.routing_state(),
            "telemetry": self.telemetry(),
            "buzzers": self.buzzers.to_dict(),
            "buzzer_source_mode": self.buzzer_source_mode,
            "used_question_numbers": list(self.used_question_numbers),
            "question_bank_warning": self.question_bank_warning,
            "display_view": self.display_view,
            "tournament_progress": self.get_tournament_progress(),
            "log": [entry.to_dict() for entry in self.log],
        }

    def restore_state(self, state_dict: Dict[str, Any]) -> None:
        """Restores complete game state from a state dictionary."""
        ev = state_dict.get("event", {})
        self.stage = ev.get("stage", Stage.QUALIFIER.value)
        self.match_number = int(ev.get("match_number", 1))
        self.bracket = BracketData.from_dict(ev.get("bracket", {}))

        self.teams = {
            t_id: Team.from_dict(t_data)
            for t_id, t_data in state_dict.get("teams", {}).items()
        }

        curr_m = state_dict.get("current_match")
        self.current_match = MatchData.from_dict(curr_m) if curr_m else None

        self.round = RoundState.from_dict(state_dict.get("round", {}))
        # Rule: on state restore, always restore the timer as paused
        self.round.timer_running = False

        self.question = QuestionState.from_dict(state_dict.get("question", {}))
        self.question_matrix = QuestionMatrixState.from_dict(state_dict.get("question_matrix", {}))
        routing = state_dict.get("routing", {})
        self.round.routing_mode = routing.get("mode", self.round.routing_mode)
        self.round.turn_start_side = routing.get("start_side", self.round.turn_start_side)
        self.round.team_block_size = int(routing.get("block_size", self.round.team_block_size))
        telemetry = state_dict.get("telemetry", {})
        self._rapid_fire_streak = int(telemetry.get("current_streak", 0))
        self._last_score_guard_key = ""
        self._last_score_guard_at = 0.0
        self.buzzers = BuzzersState.from_dict(state_dict.get("buzzers", {}))
        self.buzzer_source_mode = str(state_dict.get("buzzer_source_mode", self.buzzers.source_mode or "ESP32")).upper()
        self.buzzers.source_mode = self.buzzer_source_mode
        self.used_question_numbers = [int(n) for n in state_dict.get("used_question_numbers", [])]
        self.question_bank_warning = state_dict.get("question_bank_warning")
        self._spoken_matrix_mode = self.round.phase in (
            RoundPhase.RAPID_FIRE.value,
            RoundPhase.BUZZER_BATTLE.value,
            RoundPhase.SUDDEN_DEATH.value,
        )
        display_view = state_dict.get("display_view", "auto")
        self.display_view = display_view if display_view in {"auto", "match", "bracket", "result"} else "auto"

        self.log = [LogEntry.from_dict(e) for e in state_dict.get("log", [])]

        self._log_action("restore_state", {"match_number": self.match_number, "stage": self.stage})

    def set_buzzer_source_mode(self, mode: str) -> Dict[str, Any]:
        """Sets active buzzer source to 'ESP32' (hardware primary) or 'MOBILE' (backup failover)."""
        normalized = str(mode).strip().upper()
        if normalized not in ("ESP32", "MOBILE"):
            raise ValueError(f"Invalid buzzer source mode: '{mode}'. Must be 'ESP32' or 'MOBILE'.")
        self.buzzer_source_mode = normalized
        self.buzzers.source_mode = normalized
        self._log_action("set_buzzer_source_mode", {"mode": normalized})
        return {"buzzer_source_mode": self.buzzer_source_mode}
