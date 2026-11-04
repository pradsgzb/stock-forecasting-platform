"""Content-addressed, write-once local raw-object storage."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from threading import RLock

from stock_predictor.domain.common.errors import ImmutableObjectConflictError
from stock_predictor.domain.market_data.ingestion import RawObjectDescriptor, Sha256Digest


class StorageIntegrityError(RuntimeError):
    """Raised when durable bytes do not match their immutable descriptor."""


class LocalContentAddressedRawObjectStore:
    """Local development implementation of immutable object storage.

    Content is staged and then linked into a SHA-256-derived path. The final path is never
    replaced. A production cloud adapter should apply provider retention and object-lock controls
    while preserving this port contract.
    """

    __slots__ = ("_root", "_lock")

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    @staticmethod
    def _storage_key(digest: Sha256Digest) -> str:
        value = str(digest)
        return f"raw/sha256/{value[:2]}/{value[2:4]}/{value}.blob"

    def _path(self, digest: Sha256Digest) -> Path:
        return self._root / self._storage_key(digest)

    @staticmethod
    def _verify(path: Path, digest: Sha256Digest, byte_count: int | None = None) -> bytes:
        try:
            payload = path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageIntegrityError(f"Raw object is missing: {digest}") from exc
        if byte_count is not None and len(payload) != byte_count:
            raise StorageIntegrityError(f"Raw object size mismatch: {digest}")
        actual = Sha256Digest.from_bytes(payload)
        if actual != digest:
            raise StorageIntegrityError(f"Raw object checksum mismatch: {digest}")
        return payload

    @staticmethod
    def _sync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def put(self, payload: bytes) -> RawObjectDescriptor:
        if not payload:
            raise ValueError("Raw object payload cannot be empty")
        digest = Sha256Digest.from_bytes(payload)
        key = self._storage_key(digest)
        target = self._root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if target.exists():
                self._verify(target, digest, len(payload))
                return RawObjectDescriptor(digest, key, len(payload))
            file_descriptor, temporary_name = tempfile.mkstemp(
                dir=target.parent, prefix=f".{digest}.", suffix=".tmp"
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(file_descriptor, "wb", closefd=True) as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    self._verify(target, digest, len(payload))
                except OSError as exc:
                    raise StorageIntegrityError(
                        "Atomic hard-link publication is unavailable for the raw store"
                    ) from exc
                self._sync_directory(target.parent)
            finally:
                temporary.unlink(missing_ok=True)
        return RawObjectDescriptor(digest, key, len(payload))

    def read(self, descriptor: RawObjectDescriptor) -> bytes:
        expected_key = self._storage_key(descriptor.digest)
        if descriptor.storage_key != expected_key:
            raise ImmutableObjectConflictError(
                "Raw object descriptor key does not match its content digest"
            )
        return self._verify(
            self._root / descriptor.storage_key, descriptor.digest, descriptor.byte_count
        )

    def exists(self, digest: Sha256Digest) -> bool:
        return self._path(digest).is_file()
