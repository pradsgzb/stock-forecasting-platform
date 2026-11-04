from uuid import UUID

import pytest

from stock_predictor.domain.common.errors import DomainValidationError
from stock_predictor.domain.common.identifiers import InstrumentId, ModelVersionId


def test_identifier_round_trip_and_type_separation() -> None:
    instrument_id = InstrumentId.new()

    assert InstrumentId.parse(str(instrument_id)) == instrument_id
    assert ModelVersionId.parse(str(instrument_id)) != instrument_id


def test_nil_uuid_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match="nil UUID"):
        InstrumentId(UUID(int=0))


def test_invalid_identifier_text_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match="Invalid InstrumentId"):
        InstrumentId.parse("not-a-uuid")
