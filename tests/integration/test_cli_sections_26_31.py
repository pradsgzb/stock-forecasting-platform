import json
from pathlib import Path

import pytest

from stock_predictor.cli import main

pytestmark = pytest.mark.integration


def test_learning_cli_lists_and_shows_exercises(capsys) -> None:
    assert main(["labs", "validate"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["exercise_count"] == 9

    assert main(["labs", "show", "model-plugin"]) == 0
    exercise = json.loads(capsys.readouterr().out)
    assert exercise["track"] == "machine-learning"


def test_release_manifest_cli_round_trip(tmp_path: Path, capsys) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("release", encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.py").write_text("VALUE = 1\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"

    assert (
        main(
            [
                "release-manifest",
                "create",
                "--version",
                "0.6.0",
                "--git-commit",
                "abcdef1234567",
                "--source-root",
                str(source),
                "--build-run-id",
                "run-1",
                "--artifact",
                f"checksums={artifact}",
                "--gate",
                "tests=pytest.xml",
                "--output",
                str(manifest),
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["ready"] is True

    assert (
        main(
            [
                "release-manifest",
                "verify",
                "--manifest",
                str(manifest),
                "--artifact-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    verified = json.loads(capsys.readouterr().out)
    assert verified["verified"] is True


def test_reference_scenario_cli_writes_report(tmp_path: Path, capsys) -> None:
    output = tmp_path / "report.json"
    assert (
        main(
            [
                "reference-scenario",
                "--workspace",
                str(tmp_path / "workspace"),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["paper_trading_only"] is True
    assert output.is_file()
