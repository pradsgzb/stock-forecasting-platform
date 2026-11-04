import pytest

from stock_predictor.domain.common.identifiers import AuditEventId
from stock_predictor.domain.operations.records import AuditEvent, AuditOutcome, JsonDocument

pytestmark = pytest.mark.contract


def test_operational_store_contract_is_transactional(operational_store, fixed_instant) -> None:
    event = AuditEvent(
        AuditEventId.new(),
        1,
        fixed_instant,
        "contract-user",
        "contract.verify",
        "contract.store",
        "resource-1",
        AuditOutcome.SUCCESS,
        "correlation-1",
        "request-1",
        "contract test",
        JsonDocument.from_mapping({"adapter": "sqlalchemy"}),
        None,
    )
    with operational_store() as uow:
        uow.audit.append(event)
        uow.commit()
    with operational_store() as uow:
        assert uow.audit.tail() == event
        assert uow.audit.verify_chain()
