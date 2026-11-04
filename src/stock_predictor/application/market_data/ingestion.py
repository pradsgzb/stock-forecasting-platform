"""Resumable, idempotent ingestion of opaque provider pages into immutable raw storage."""

from __future__ import annotations

from dataclasses import dataclass

from stock_predictor.application.market_data.registry import MarketDataProviderRegistry
from stock_predictor.domain.common.clock import Clock
from stock_predictor.domain.common.errors import DomainConflictError, DomainValidationError
from stock_predictor.domain.common.identifiers import IngestionRunId
from stock_predictor.domain.market_data.contracts import PriceBarRequest
from stock_predictor.domain.market_data.ingestion import (
    IngestionCheckpoint,
    IngestionManifest,
    IngestionPageManifest,
    IngestionStatus,
)
from stock_predictor.ports.ingestion_catalog import IngestionCatalog
from stock_predictor.ports.raw_object_store import RawObjectStore


@dataclass(frozen=True, slots=True)
class IngestionPolicy:
    """Operational bounds that protect workers from unbounded provider responses."""

    maximum_pages: int = 10_000
    maximum_page_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.maximum_pages <= 0 or self.maximum_page_bytes <= 0:
            raise DomainValidationError("Ingestion limits must be positive")


class MarketDataIngestionService:
    """Coordinates capability checks, fetch, immutable storage, and checkpointing."""

    __slots__ = ("_catalog", "_clock", "_policy", "_providers", "_raw_objects")

    def __init__(
        self,
        providers: MarketDataProviderRegistry,
        raw_objects: RawObjectStore,
        catalog: IngestionCatalog,
        clock: Clock,
        policy: IngestionPolicy | None = None,
    ) -> None:
        self._providers = providers
        self._raw_objects = raw_objects
        self._catalog = catalog
        self._clock = clock
        self._policy = policy or IngestionPolicy()

    def ingest_price_bars(
        self, request: PriceBarRequest, *, idempotency_key: str | None = None
    ) -> IngestionManifest:
        key = (idempotency_key or request.request_fingerprint).strip()
        if not key or len(key) > 256:
            raise DomainValidationError(
                "Ingestion idempotency key must contain 1 to 256 characters"
            )
        completed = self._catalog.find_completed(key)
        if completed is not None:
            if completed.request.request_fingerprint != request.request_fingerprint:
                raise DomainConflictError(
                    "Idempotency key is already associated with a different request"
                )
            return completed

        provider = self._providers.get(request.provider)
        provider.capabilities.validate(request)
        checkpoint = self._catalog.load_checkpoint(key)
        if checkpoint is None:
            started_at = self._clock.now()
            checkpoint = IngestionCheckpoint(
                run_id=IngestionRunId.new(),
                idempotency_key=key,
                request_fingerprint=request.request_fingerprint,
                next_page_number=1,
                next_cursor=None,
                completed_pages=(),
                started_at=started_at,
                updated_at=started_at,
            )
            self._catalog.save_checkpoint(checkpoint)
        elif checkpoint.request_fingerprint != request.request_fingerprint:
            raise DomainConflictError(
                "Existing checkpoint belongs to a different request fingerprint"
            )

        pages = list(checkpoint.completed_pages)
        cursor = checkpoint.next_cursor
        page_number = checkpoint.next_page_number
        seen_cursors = {item.cursor_in for item in pages if item.cursor_in is not None}
        seen_cursors.update(item.cursor_out for item in pages if item.cursor_out is not None)

        while True:
            if page_number > self._policy.maximum_pages:
                raise DomainValidationError("Ingestion exceeded the configured page limit")
            page = provider.fetch_price_bars(request, cursor=cursor)
            if len(page.raw_payload) > self._policy.maximum_page_bytes:
                raise DomainValidationError("Provider page exceeded the configured byte limit")
            raw_object = self._raw_objects.put(page.raw_payload)
            manifest_page = IngestionPageManifest(
                page_number=page_number,
                cursor_in=cursor,
                cursor_out=page.next_cursor,
                provider_request_id=page.provider_request_id,
                schema_version=page.schema_version,
                content_type=page.content_type,
                advertised_record_count=page.advertised_record_count,
                raw_object=raw_object,
                retrieved_at=page.retrieved_at,
            )
            pages.append(manifest_page)
            if page.next_cursor is not None:
                if page.next_cursor == cursor or page.next_cursor in seen_cursors:
                    raise DomainValidationError("Provider cursor did not make forward progress")
                seen_cursors.add(page.next_cursor)
            checkpoint = IngestionCheckpoint(
                run_id=checkpoint.run_id,
                idempotency_key=key,
                request_fingerprint=request.request_fingerprint,
                next_page_number=page_number + 1,
                next_cursor=page.next_cursor,
                completed_pages=tuple(pages),
                started_at=checkpoint.started_at,
                updated_at=self._clock.now(),
            )
            self._catalog.save_checkpoint(checkpoint)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
            page_number += 1

        manifest = IngestionManifest(
            run_id=checkpoint.run_id,
            idempotency_key=key,
            provider=request.provider,
            request=request,
            started_at=checkpoint.started_at,
            completed_at=self._clock.now(),
            status=IngestionStatus.COMPLETED,
            pages=tuple(pages),
        )
        self._catalog.save_manifest(manifest)
        self._catalog.clear_checkpoint(key)
        return manifest
