"""Load the packaged, schema-validated learning catalog."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.learning.models import (
    ExerciseDifficulty,
    LearningCatalog,
    LearningExercise,
    LearningTrack,
)


class LearningCatalogService:
    """Application boundary for student exercises and extension guidance."""

    __slots__ = ("_path",)

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    def load(self) -> LearningCatalog:
        payload = self._read_payload()
        schema_version = self._required_string(payload, "schema_version")
        raw_exercises = payload.get("exercises")
        if not isinstance(raw_exercises, list):
            raise DomainValidationError("Learning catalog exercises must be a list")
        exercises = tuple(self._exercise(item) for item in raw_exercises)
        return LearningCatalog(schema_version, exercises)

    def summary(self) -> dict[str, object]:
        catalog = self.load()
        return {
            "schema_version": catalog.schema_version,
            "exercise_count": len(catalog.exercises),
            "tracks": {
                track.value: len(catalog.for_track(track)) for track in LearningTrack
            },
            "ordered_exercise_ids": [item.exercise_id for item in catalog.ordered()],
        }

    def _read_payload(self) -> dict[str, Any]:
        if self._path is None:
            resource = files("stock_predictor.resources").joinpath("learning_catalog.json")
            text = resource.read_text(encoding="utf-8")
        else:
            if not self._path.is_file():
                raise DomainValidationError(
                    f"Learning catalog file does not exist: {self._path}"
                )
            text = self._path.read_text(encoding="utf-8")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DomainValidationError("Learning catalog is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise DomainValidationError("Learning catalog root must be an object")
        return cast(dict[str, Any], payload)

    def _exercise(self, value: object) -> LearningExercise:
        if not isinstance(value, dict):
            raise DomainValidationError("Each learning exercise must be an object")
        item = cast(dict[str, Any], value)
        return LearningExercise(
            exercise_id=self._required_string(item, "exercise_id"),
            title=self._required_string(item, "title"),
            track=LearningTrack(self._required_string(item, "track")),
            difficulty=ExerciseDifficulty(self._required_string(item, "difficulty")),
            objective=self._required_string(item, "objective"),
            prerequisites=self._strings(item, "prerequisites", allow_empty=True),
            extension_points=self._strings(item, "extension_points"),
            acceptance_criteria=self._strings(item, "acceptance_criteria"),
            verification_commands=self._strings(item, "verification_commands"),
            deliverables=self._strings(item, "deliverables"),
            expected_sessions=self._required_int(item, "expected_sessions"),
        )

    @staticmethod
    def _required_string(payload: dict[str, Any], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            raise DomainValidationError(f"Learning catalog field {name} must be a string")
        return value

    @staticmethod
    def _required_int(payload: dict[str, Any], name: str) -> int:
        value = payload.get(name)
        if not isinstance(value, int) or isinstance(value, bool):
            raise DomainValidationError(f"Learning catalog field {name} must be an integer")
        return value

    @staticmethod
    def _strings(
        payload: dict[str, Any],
        name: str,
        *,
        allow_empty: bool = False,
    ) -> tuple[str, ...]:
        value = payload.get(name)
        if not isinstance(value, list) or (not value and not allow_empty):
            raise DomainValidationError(f"Learning catalog field {name} must be a list")
        if any(not isinstance(item, str) for item in value):
            raise DomainValidationError(f"Learning catalog field {name} must contain strings")
        return tuple(cast(list[str], value))
