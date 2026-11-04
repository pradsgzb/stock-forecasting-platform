#!/usr/bin/env python3
"""Generate local-only RSA credentials and short-lived development bearer tokens."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".local/secrets"))
    parser.add_argument("--issuer", default="https://local.identity.invalid/")
    parser.add_argument("--audience", default="stock-forecasting-platform")
    parser.add_argument("--hours", type=int, default=24)
    return parser


def _token(
    private_key: bytes,
    *,
    subject: str,
    name: str,
    roles: list[str],
    issuer: str,
    audience: str,
    now: datetime,
    hours: int,
) -> str:
    return jwt.encode(
        {
            "sub": subject,
            "name": name,
            "roles": roles,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "nbf": now - timedelta(seconds=5),
            "exp": now + timedelta(hours=hours),
            "jti": str(uuid4()),
        },
        private_key,
        algorithm="RS256",
    )


def main() -> int:
    args = _parser().parse_args()
    if args.hours <= 0 or args.hours > 168:
        raise SystemExit("--hours must be between 1 and 168")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_bytes = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    now = datetime.now(UTC)
    operator = _token(
        private_bytes,
        subject="local-operator",
        name="Local Research Operator",
        roles=["viewer", "operator", "auditor", "metrics_reader", "model_approver"],
        issuer=args.issuer,
        audience=args.audience,
        now=now,
        hours=args.hours,
    )
    metrics = _token(
        private_bytes,
        subject="local-prometheus",
        name="Local Prometheus",
        roles=["metrics_reader"],
        issuer=args.issuer,
        audience=args.audience,
        now=now,
        hours=args.hours,
    )
    values = {
        "jwt-private.pem": private_bytes,
        "jwt-public.pem": public_bytes,
        "operator-token": (operator + "\n").encode(),
        "prometheus-token": (metrics + "\n").encode(),
    }
    for name, data in values.items():
        path = output / name
        path.write_bytes(data)
        os.chmod(path, 0o600 if "private" in name or "token" in name else 0o644)
    print(f"Generated local credentials in {output}")
    print(f"Operator token: {output / 'operator-token'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
