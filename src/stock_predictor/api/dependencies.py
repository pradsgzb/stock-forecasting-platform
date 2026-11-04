"""Authentication and role dependencies for the internal API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, Request

from stock_predictor.domain.common.errors import AuthenticationError
from stock_predictor.domain.security.identity import Principal, PrincipalRole
from stock_predictor.ports.authentication import Authenticator

PrincipalDependency = Callable[[Request], Awaitable[Principal]]


def build_principal_dependency(authenticator: Authenticator) -> PrincipalDependency:
    async def principal(request: Request) -> Principal:
        authorization = request.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationError("A Bearer access token is required")
        return authenticator.authenticate(token)

    return principal


def require_roles(
    principal_dependency: PrincipalDependency,
    *roles: PrincipalRole,
) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        principal: Principal = Depends(principal_dependency),
    ) -> Principal:
        principal.require_any(*roles)
        return principal

    return dependency
