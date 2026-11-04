import json

import pytest

from stock_predictor.cli import main

pytestmark = pytest.mark.integration


def test_doctor_command_emits_non_secret_json(capsys, monkeypatch) -> None:
    monkeypatch.setenv("SP_SECURITY__MARKET_DATA_API_KEY", "classified")

    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert payload["settings"]["market_data_api_key_configured"] is True
    assert "classified" not in output
    assert {item["mic"] for item in payload["exchanges"]} == {"XNYS", "XBOM"}
