from abc import ABC, abstractmethod
from typing import List, Optional
from server.engine.models import QuestionCard, QuestionType


class QuestionProvider(ABC):
    """Abstract interface for quiz question providers."""

    @abstractmethod
    def get_question(self, number: int) -> Optional[QuestionCard]:
        """Fetch a question card by question number."""
        pass

    @abstractmethod
    def get_by_index(self, index: int) -> Optional[QuestionCard]:
        """Fetch a question card by 0-based index."""
        pass

    @abstractmethod
    def list_questions(self) -> List[QuestionCard]:
        """Return all questions available in this provider."""
        pass

    @abstractmethod
    def count(self) -> int:
        """Return the total number of questions available."""
        pass


class SpokenQuestionProvider(QuestionProvider):
    """Spoken-only question provider for EEECi FA'26.
    Questions and answers are NEVER uploaded, stored, or displayed in the software.
    The host / moderator reads all questions aloud from physical paper/cards.
    This provider generates blank QuestionCard slots purely by question number.
    """

    def __init__(self, count: int = 15, questions: Optional[List[QuestionCard]] = None):
        if questions is not None:
            self._questions = list(questions)
        else:
            self._questions = [
                QuestionCard(
                    number=number,
                    type=QuestionType.TEXT.value,
                    text="",
                    image=None,
                    answer="",
                    points=10,
                )
                for number in range(1, count + 1)
            ]

    def set_count(self, count: int) -> None:
        self._questions = [
            QuestionCard(
                number=number,
                type=QuestionType.TEXT.value,
                text="",
                image=None,
                answer="",
                points=10,
            )
            for number in range(1, count + 1)
        ]

    def get_question(self, number: int) -> Optional[QuestionCard]:
        for q in self._questions:
            if q.number == number:
                return q
        return QuestionCard(
            number=number,
            type=QuestionType.TEXT.value,
            text="",
            image=None,
            answer="",
            points=10,
        )

    def get_by_index(self, index: int) -> Optional[QuestionCard]:
        if 0 <= index < len(self._questions):
            return self._questions[index]
        return None

    def list_questions(self) -> List[QuestionCard]:
        return list(self._questions)

    def count(self) -> int:
        return len(self._questions)


class SampleQuestionProvider(SpokenQuestionProvider):
    """Spoken-only question provider initialized to the requested session question count.
    No hardcoded question texts or answers.
    """

    def __init__(self, questions: Optional[List[QuestionCard]] = None, count: Optional[int] = None):
        if questions is not None:
            super().__init__(count=len(questions), questions=questions)
        else:
            super().__init__(count=count if count is not None else 5)
