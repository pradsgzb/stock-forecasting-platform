"""Port for immutable content-addressed raw bytes."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stock_predictor.domain.market_data.ingestion import RawObjectDescriptor, Sha256Digest


@runtime_checkable
class RawObjectStore(Protocol):
    """Persists raw provider payloads without mutation."""

    def put(self, payload: bytes) -> RawObjectDescriptor:
        """Store bytes once by digest and return their immutable descriptor."""
        ...

    def read(self, descriptor: RawObjectDescriptor) -> bytes:
        """Read and checksum-verify an immutable object."""
        ...

    def exists(self, digest: Sha256Digest) -> bool:
        """Return whether the digest is already present."""
        ...
