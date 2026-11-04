import json
from pathlib import Path

import pytest

from stock_predictor.application.learning.catalog import LearningCatalogService
from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.learning.models import LearningTrack


def test_packaged_learning_catalog_is_valid_and_ordered() -> None:
    service = LearningCatalogService()
    catalog = service.load()
    summary = service.summary()

    assert len(catalog.exercises) == 9
    assert catalog.ordered()[0].exercise_id == "python-domain-extension"
    assert catalog.for_track(LearningTrack.MLOPS)[0].exercise_id == "drift-policy"
    assert summary["exercise_count"] == 9
    assert summary["tracks"]["machine-learning"] == 1


def test_external_catalog_validation_errors(tmp_path: Path) -> None:
    missing = LearningCatalogService(tmp_path / "missing.json")
    with pytest.raises(DomainValidationError, match="does not exist"):
        missing.load()

    malformed = tmp_path / "bad.json"
    malformed.write_text("not-json", encoding="utf-8")
    with pytest.raises(DomainValidationError, match="valid JSON"):
        LearningCatalogService(malformed).load()

    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"schema_version": "1", "exercises": [3]}))
    with pytest.raises(DomainValidationError, match="must be an object"):
        LearningCatalogService(wrong).load()

    bad_field = tmp_path / "bad-field.json"
    bad_field.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "exercises": [
                    {
                        "exercise_id": "x",
                        "title": "X",
                        "track": "python-software-engineering",
                        "difficulty": "beginner",
                        "objective": "X",
                        "prerequisites": [],
                        "extension_points": [],
                        "acceptance_criteria": ["x"],
                        "verification_commands": ["x"],
                        "deliverables": ["x"],
                        "expected_sessions": 1,
                    }
                ],
            }
        )
    )
    with pytest.raises(DomainValidationError, match="extension_points"):
        LearningCatalogService(bad_field).load()
