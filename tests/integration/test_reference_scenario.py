import json
from pathlib import Path

import pytest

from stock_predictor.reference.service import ReferenceScenarioService

pytestmark = pytest.mark.integration


def test_reference_scenario_covers_controlled_learning_and_rollback(tmp_path: Path) -> None:
    report = ReferenceScenarioService().run(tmp_path / "scenario")
    output = tmp_path / "report.json"
    report.write(output)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert report.raw_page_count == 82
    assert report.validated_record_count == 82
    assert report.normalized_bar_count == 82
    assert report.dataset_row_count > 60
    assert report.prediction_count == 2
    assert report.outcome_count == 2
    assert report.challenger_promoted is True
    assert report.rollback_model_version_id == report.final_champion_model_version_id
    assert payload["paper_trading_only"] is True
    assert len(report.dataset_fingerprint) == 64
    assert len(report.backtest_fingerprint) == 64
