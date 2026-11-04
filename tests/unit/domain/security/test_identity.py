import pytest

from stock_predictor.domain.common.errors import AuthorizationError, DomainValidationError
from stock_predictor.domain.security.identity import Principal, PrincipalRole


def test_principal_requires_role() -> None:
    principal = Principal("user-1", "User", frozenset({PrincipalRole.VIEWER}))

    principal.require_any(PrincipalRole.VIEWER, PrincipalRole.ADMIN)
    with pytest.raises(AuthorizationError):
        principal.require_any(PrincipalRole.OPERATOR)


def test_principal_rejects_blank_identity() -> None:
    with pytest.raises(DomainValidationError):
        Principal("", "User", frozenset({PrincipalRole.VIEWER}))
