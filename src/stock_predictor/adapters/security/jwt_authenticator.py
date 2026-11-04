"""Strict JWT bearer authentication with explicit issuer, audience, and algorithms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import jwt
from jwt import InvalidTokenError

from stock_predictor.domain.common.errors import AuthenticationError
from stock_predictor.domain.security.identity import Principal, PrincipalRole


@dataclass(frozen=True, slots=True)
class JwtValidationPolicy:
    issuer: str
    audience: str
    verification_key: str
    algorithms: tuple[str, ...] = ("RS256",)
    roles_claim: str = "roles"
    display_name_claim: str = "name"
    leeway_seconds: int = 30

    def __post_init__(self) -> None:
        issuer = self.issuer.strip()
        audience = self.audience.strip()
        key = self.verification_key.strip()
        algorithms = tuple(item.strip().upper() for item in self.algorithms)
        if not issuer or not audience or not key or not algorithms:
            raise ValueError("JWT validation policy requires issuer, audience, key, and algorithms")
        allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "HS256", "HS384", "HS512"}
        if any(item not in allowed for item in algorithms):
            raise ValueError("JWT validation policy contains an unsupported algorithm")
        if len(set(algorithms)) != len(algorithms) or self.leeway_seconds < 0:
            raise ValueError("JWT algorithms must be unique and leeway cannot be negative")
        object.__setattr__(self, "issuer", issuer)
        object.__setattr__(self, "audience", audience)
        object.__setattr__(self, "verification_key", key)
        object.__setattr__(self, "algorithms", algorithms)


class JwtAuthenticator:
    """Authenticates signed access tokens without trusting caller-supplied algorithms."""

    def __init__(self, policy: JwtValidationPolicy) -> None:
        self._policy = policy

    def authenticate(self, bearer_token: str) -> Principal:
        token = bearer_token.strip()
        if not token:
            raise AuthenticationError("Bearer token is missing")
        try:
            claims = jwt.decode(
                token,
                self._policy.verification_key,
                algorithms=list(self._policy.algorithms),
                audience=self._policy.audience,
                issuer=self._policy.issuer,
                leeway=self._policy.leeway_seconds,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except InvalidTokenError as exc:
            raise AuthenticationError("Bearer token validation failed") from exc
        if not isinstance(claims, dict):
            raise AuthenticationError("Bearer token claims are invalid")
        return self._principal_from_claims(claims)

    def _principal_from_claims(self, claims: Mapping[str, object]) -> Principal:
        subject = claims.get("sub")
        display = claims.get(self._policy.display_name_claim, subject)
        token_id = claims.get("jti")
        if not isinstance(subject, str) or not isinstance(display, str):
            raise AuthenticationError("Bearer token identity claims are invalid")
        raw_roles = claims.get(self._policy.roles_claim)
        role_names: tuple[str, ...]
        if isinstance(raw_roles, str):
            role_names = tuple(item for item in raw_roles.replace(",", " ").split() if item)
        elif isinstance(raw_roles, list) and all(isinstance(item, str) for item in raw_roles):
            role_names = tuple(raw_roles)
        else:
            raise AuthenticationError("Bearer token roles claim is invalid")
        try:
            roles = frozenset(PrincipalRole(item.strip().lower()) for item in role_names)
        except ValueError as exc:
            raise AuthenticationError("Bearer token contains an unsupported role") from exc
        if not roles:
            raise AuthenticationError("Bearer token does not grant any role")
        return Principal(
            subject=subject,
            display_name=display,
            roles=roles,
            token_id=token_id if isinstance(token_id, str) else None,
        )


class StaticBearerAuthenticator:
    """Deterministic adapter for tests and explicitly local development only."""

    def __init__(self, principals: Mapping[str, Principal]) -> None:
        self._principals = dict(principals)

    def authenticate(self, bearer_token: str) -> Principal:
        try:
            return self._principals[bearer_token.strip()]
        except KeyError as exc:
            raise AuthenticationError("Bearer token validation failed") from exc
