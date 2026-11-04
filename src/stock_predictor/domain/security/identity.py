"""Authenticated principals and authorization roles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from stock_predictor.domain.common.errors import AuthorizationError, DomainValidationError


class PrincipalRole(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    MODEL_APPROVER = "model_approver"
    AUDITOR = "auditor"
    ADMIN = "admin"
    METRICS_READER = "metrics_reader"


@dataclass(frozen=True, slots=True)
class Principal:
    """Verified caller identity produced by an authentication adapter."""

    subject: str
    display_name: str
    roles: frozenset[PrincipalRole]
    token_id: str | None = None

    def __post_init__(self) -> None:
        subject = self.subject.strip()
        display = self.display_name.strip()
        token_id = self.token_id.strip() if self.token_id is not None else None
        if not subject or not display or not self.roles:
            raise DomainValidationError("Principal requires subject, display name, and roles")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "display_name", display)
        object.__setattr__(self, "token_id", token_id)

    def require_any(self, *roles: PrincipalRole) -> None:
        required = frozenset(roles)
        if not required or self.roles.isdisjoint(required):
            names = ", ".join(sorted(item.value for item in required))
            raise AuthorizationError(f"Principal lacks one of the required roles: {names}")
