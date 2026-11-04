from datetime import UTC, datetime, timedelta

import jwt
import pytest

from stock_predictor.adapters.security.jwt_authenticator import (
    JwtAuthenticator,
    JwtValidationPolicy,
    StaticBearerAuthenticator,
)
from stock_predictor.domain.common.errors import AuthenticationError
from stock_predictor.domain.security.identity import Principal, PrincipalRole

pytestmark = pytest.mark.security


def _claims(**overrides):
    now = datetime.now(UTC)
    claims = {
        "sub": "operator-1",
        "name": "Research Operator",
        "roles": ["viewer", "operator"],
        "iss": "https://issuer.example/",
        "aud": "stock-platform",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": "token-1",
    }
    claims.update(overrides)
    return claims


def _authenticator() -> JwtAuthenticator:
    return JwtAuthenticator(
        JwtValidationPolicy(
            issuer="https://issuer.example/",
            audience="stock-platform",
            verification_key="development-secret-with-sufficient-length",
            algorithms=("HS256",),
            leeway_seconds=0,
        )
    )


def _token(**overrides) -> str:
    return jwt.encode(
        _claims(**overrides),
        "development-secret-with-sufficient-length",
        algorithm="HS256",
    )


def test_valid_jwt_creates_typed_principal() -> None:
    principal = _authenticator().authenticate(_token())

    assert principal.subject == "operator-1"
    assert principal.display_name == "Research Operator"
    assert principal.roles == frozenset({PrincipalRole.VIEWER, PrincipalRole.OPERATOR})
    assert principal.token_id == "token-1"


def test_space_delimited_role_claim_and_missing_optional_claims() -> None:
    claims = _claims(roles="viewer metrics_reader", name="operator-1")
    claims.pop("jti")
    token = jwt.encode(
        claims,
        "development-secret-with-sufficient-length",
        algorithm="HS256",
    )

    principal = _authenticator().authenticate(token)

    assert principal.roles == frozenset(
        {PrincipalRole.VIEWER, PrincipalRole.METRICS_READER}
    )
    assert principal.token_id is None


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-jwt",
        _token(aud="wrong-audience"),
        _token(iss="https://wrong.example/"),
        _token(exp=datetime.now(UTC) - timedelta(minutes=1)),
    ],
)
def test_invalid_tokens_are_rejected_without_disclosing_crypto_details(token: str) -> None:
    with pytest.raises(AuthenticationError, match="token"):
        _authenticator().authenticate(token)


@pytest.mark.parametrize(
    "roles",
    [None, [], ["unknown"], ["viewer", 7]],
)
def test_invalid_role_claims_are_rejected(roles) -> None:
    with pytest.raises(AuthenticationError, match="role"):
        _authenticator().authenticate(_token(roles=roles))


def test_invalid_identity_claims_are_rejected() -> None:
    with pytest.raises(AuthenticationError, match="validation"):
        _authenticator().authenticate(_token(sub=42))


def test_policy_validation_rejects_unsafe_or_duplicate_algorithms() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        JwtValidationPolicy("issuer", "audience", "key", ("none",))
    with pytest.raises(ValueError, match="unique"):
        JwtValidationPolicy("issuer", "audience", "key", ("HS256", "hs256"))
    with pytest.raises(ValueError, match="requires"):
        JwtValidationPolicy("", "audience", "key")


def test_static_authenticator_is_deterministic() -> None:
    principal = Principal(
        "viewer-1",
        "Viewer",
        frozenset({PrincipalRole.VIEWER}),
    )
    authenticator = StaticBearerAuthenticator({"known-token": principal})

    assert authenticator.authenticate(" known-token ") == principal
    with pytest.raises(AuthenticationError):
        authenticator.authenticate("unknown-token")
