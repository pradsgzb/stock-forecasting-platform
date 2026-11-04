import pytest

from stock_predictor.domain.common.errors import DomainNotFoundError, DomainValidationError
from stock_predictor.domain.learning.models import (
    ExerciseDifficulty,
    LearningCatalog,
    LearningExercise,
    LearningTrack,
)


def _exercise(exercise_id: str, prerequisites: tuple[str, ...] = ()) -> LearningExercise:
    return LearningExercise(
        exercise_id=exercise_id,
        title=f"Exercise {exercise_id}",
        track=LearningTrack.PYTHON,
        difficulty=ExerciseDifficulty.BEGINNER,
        objective="Demonstrate a bounded extension.",
        prerequisites=prerequisites,
        extension_points=("src/example.py",),
        acceptance_criteria=("Tests pass",),
        verification_commands=("uv run pytest",),
        deliverables=("Code",),
        expected_sessions=2,
    )


def test_catalog_orders_prerequisites_and_filters_tracks() -> None:
    first = _exercise("first")
    second = _exercise("second", ("first",))
    catalog = LearningCatalog("1.0.0", (second, first))

    assert tuple(item.exercise_id for item in catalog.ordered()) == ("first", "second")
    assert catalog.get(" SECOND ") == second
    assert catalog.for_track(LearningTrack.PYTHON) == (first, second)


def test_learning_models_reject_invalid_graphs_and_values() -> None:
    with pytest.raises(DomainValidationError, match="Exercise ID"):
        _exercise("Bad ID")
    with pytest.raises(DomainValidationError, match="between 1 and 40"):
        LearningExercise(
            exercise_id="bad-sessions",
            title="Bad",
            track=LearningTrack.PYTHON,
            difficulty=ExerciseDifficulty.BEGINNER,
            objective="Bad",
            prerequisites=(),
            extension_points=("src",),
            acceptance_criteria=("test",),
            verification_commands=("test",),
            deliverables=("test",),
            expected_sessions=0,
        )
    with pytest.raises(DomainValidationError, match="unknown prerequisites"):
        LearningCatalog("1", (_exercise("second", ("missing",)),))
    with pytest.raises(DomainValidationError, match="require itself"):
        LearningCatalog("1", (_exercise("self", ("self",)),))
    with pytest.raises(DomainValidationError, match="cycle"):
        LearningCatalog(
            "1",
            (_exercise("one", ("two",)), _exercise("two", ("one",))),
        )


def test_catalog_not_found() -> None:
    catalog = LearningCatalog("1", (_exercise("known"),))
    with pytest.raises(DomainNotFoundError, match="Unknown learning exercise"):
        catalog.get("missing")
