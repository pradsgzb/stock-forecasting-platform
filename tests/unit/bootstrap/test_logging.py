import json
import logging

from stock_predictor.bootstrap.logging import JsonFormatter, configure_logging
from stock_predictor.bootstrap.settings import LogLevel, RuntimeEnvironment


def test_json_formatter_serializes_message_and_exception() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "failure %s", ("x",), None)
    payload = json.loads(formatter.format(record))

    assert payload["level"] == "ERROR"
    assert payload["message"] == "failure x"


def test_configure_logging_uses_json_in_production() -> None:
    configure_logging(LogLevel.INFO, RuntimeEnvironment.PRODUCTION)
    root = logging.getLogger()

    assert root.level == logging.INFO
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_configure_logging_uses_text_locally() -> None:
    configure_logging(LogLevel.DEBUG, RuntimeEnvironment.LOCAL)
    root = logging.getLogger()

    assert root.level == logging.DEBUG
    assert not isinstance(root.handlers[0].formatter, JsonFormatter)
