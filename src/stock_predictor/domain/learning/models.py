"""Validated learning exercises that extend the production platform safely."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from stock_predictor.domain.common.errors import DomainNotFoundError, DomainValidationError

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ExerciseDifficulty(StrEnum):
    """Relative exercise difficulty."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class LearningTrack(StrEnum):
    """Learning tracks aligned with the platform architecture."""

    PYTHON = "python-software-engineering"
    DATA = "data-engineering"
    MACHINE_LEARNING = "machine-learning"
    TIME_SERIES = "time-series"
    DEEP_LEARNING = "deep-learning"
    FINANCE = "financial-modeling"
    MLOPS = "mlops"
    CLOUD = "cloud-devops"
    RESEARCH = "research-methodology"


def _text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainValidationError(f"{field_name} cannot be empty")
    return normalized


def _items(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    normalized = tuple(_text(item, field_name=field_name) for item in values)
    if not normalized:
        raise DomainValidationError(f"{field_name} requires at least one item")
    if len(set(normalized)) != len(normalized):
        raise DomainValidationError(f"{field_name} items must be unique")
    return normalized


@dataclass(frozen=True, slots=True)
class LearningExercise:
    """One bounded extension exercise with executable acceptance criteria."""

    exercise_id: str
    title: str
    track: LearningTrack
    difficulty: ExerciseDifficulty
    objective: str
    prerequisites: tuple[str, ...]
    extension_points: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    verification_commands: tuple[str, ...]
    deliverables: tuple[str, ...]
    expected_sessions: int

    def __post_init__(self) -> None:
        identifier = self.exercise_id.strip().lower()
        if _ID_PATTERN.fullmatch(identifier) is None:
            raise DomainValidationError(
                "Exercise ID must contain lowercase letters, numbers, and single hyphens"
            )
        if self.expected_sessions <= 0 or self.expected_sessions > 40:
            raise DomainValidationError("Expected sessions must be between 1 and 40")
        object.__setattr__(self, "exercise_id", identifier)
        object.__setattr__(self, "title", _text(self.title, field_name="Exercise title"))
        object.__setattr__(self, "objective", _text(self.objective, field_name="Objective"))
        object.__setattr__(
            self,
            "prerequisites",
            tuple(item.strip().lower() for item in self.prerequisites if item.strip()),
        )
        object.__setattr__(
            self,
            "extension_points",
            _items(self.extension_points, field_name="Extension points"),
        )
        object.__setattr__(
            self,
            "acceptance_criteria",
            _items(self.acceptance_criteria, field_name="Acceptance criteria"),
        )
        object.__setattr__(
            self,
            "verification_commands",
            _items(self.verification_commands, field_name="Verification commands"),
        )
        object.__setattr__(
            self,
            "deliverables",
            _items(self.deliverables, field_name="Deliverables"),
        )


@dataclass(frozen=True, slots=True)
class LearningCatalog:
    """Topologically valid collection of learning exercises."""

    schema_version: str
    exercises: tuple[LearningExercise, ...]

    def __post_init__(self) -> None:
        version = self.schema_version.strip()
        if not version:
            raise DomainValidationError("Learning catalog schema version is required")
        if not self.exercises:
            raise DomainValidationError("Learning catalog cannot be empty")
        identifiers = tuple(item.exercise_id for item in self.exercises)
        if len(set(identifiers)) != len(identifiers):
            raise DomainValidationError("Learning exercise IDs must be unique")
        known = set(identifiers)
        for exercise in self.exercises:
            missing = sorted(set(exercise.prerequisites) - known)
            if missing:
                raise DomainValidationError(
                    f"Exercise {exercise.exercise_id} has unknown prerequisites: "
                    + ", ".join(missing)
                )
            if exercise.exercise_id in exercise.prerequisites:
                raise DomainValidationError("An exercise cannot require itself")
        self._validate_cycles()
        object.__setattr__(self, "schema_version", version)
        object.__setattr__(
            self,
            "exercises",
            tuple(sorted(self.exercises, key=lambda item: item.exercise_id)),
        )

    def get(self, exercise_id: str) -> LearningExercise:
        normalized = exercise_id.strip().lower()
        for exercise in self.exercises:
            if exercise.exercise_id == normalized:
                return exercise
        raise DomainNotFoundError(f"Unknown learning exercise: {exercise_id}")

    def for_track(self, track: LearningTrack) -> tuple[LearningExercise, ...]:
        return tuple(item for item in self.exercises if item.track is track)

    def ordered(self) -> tuple[LearningExercise, ...]:
        """Return a deterministic prerequisite-first order."""
        pending = {item.exercise_id: item for item in self.exercises}
        completed: set[str] = set()
        ordered: list[LearningExercise] = []
        while pending:
            available = tuple(
                sorted(
                    (
                        item
                        for item in pending.values()
                        if set(item.prerequisites).issubset(completed)
                    ),
                    key=lambda item: item.exercise_id,
                )
            )
            if not available:
                raise DomainValidationError("Learning catalog contains a prerequisite cycle")
            for item in available:
                ordered.append(item)
                completed.add(item.exercise_id)
                del pending[item.exercise_id]
        return tuple(ordered)

    def _validate_cycles(self) -> None:
        self.ordered()
