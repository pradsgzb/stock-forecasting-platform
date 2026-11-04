from pathlib import Path

import pytest

from stock_predictor.adapters.storage.local_raw_object_store import (
    LocalContentAddressedRawObjectStore,
    StorageIntegrityError,
)
from stock_predictor.domain.common.errors import ImmutableObjectConflictError
from stock_predictor.domain.market_data.ingestion import RawObjectDescriptor, Sha256Digest


def test_raw_store_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    store = LocalContentAddressedRawObjectStore(tmp_path)

    first = store.put(b"provider payload")
    second = store.put(b"provider payload")

    assert first == second
    assert store.exists(first.digest)
    assert store.read(first) == b"provider payload"
    assert first.storage_key.endswith(f"{first.digest}.blob")


def test_raw_store_detects_tampering(tmp_path: Path) -> None:
    store = LocalContentAddressedRawObjectStore(tmp_path)
    descriptor = store.put(b"original")
    (tmp_path / descriptor.storage_key).write_bytes(b"tampered")

    with pytest.raises(StorageIntegrityError, match="size mismatch|checksum mismatch"):
        store.read(descriptor)


def test_raw_store_rejects_descriptor_key_mismatch(tmp_path: Path) -> None:
    store = LocalContentAddressedRawObjectStore(tmp_path)
    descriptor = store.put(b"payload")
    conflicting = RawObjectDescriptor(
        descriptor.digest,
        "raw/sha256/00/00/not-the-digest.blob",
        descriptor.byte_count,
    )

    with pytest.raises(ImmutableObjectConflictError, match="does not match"):
        store.read(conflicting)


def test_raw_store_rejects_empty_payload(tmp_path: Path) -> None:
    store = LocalContentAddressedRawObjectStore(tmp_path)
    with pytest.raises(ValueError, match="cannot be empty"):
        store.put(b"")


def test_raw_store_reports_missing_object(tmp_path: Path) -> None:
    store = LocalContentAddressedRawObjectStore(tmp_path)
    descriptor = RawObjectDescriptor(
        Sha256Digest("a" * 64),
        f"raw/sha256/aa/aa/{'a' * 64}.blob",
        1,
    )
    with pytest.raises(StorageIntegrityError, match="missing"):
        store.read(descriptor)
