"""Outbound interfaces owned by the application core."""

from stock_predictor.ports.calendar_provider import CalendarProvider
from stock_predictor.ports.feature_calculator import FeatureCalculator
from stock_predictor.ports.feature_store import FeatureStore
from stock_predictor.ports.ingestion_catalog import IngestionCatalog
from stock_predictor.ports.instrument_repository import InstrumentRepository
from stock_predictor.ports.market_data_provider import MarketDataProvider
from stock_predictor.ports.price_bar_repository import (
    AdjustmentFactorRepository,
    PriceBarRepository,
)
from stock_predictor.ports.raw_object_store import RawObjectStore
from stock_predictor.ports.validation_report_repository import ValidationReportRepository

__all__ = [
    "AdjustmentFactorRepository",
    "CalendarProvider",
    "FeatureCalculator",
    "FeatureStore",
    "IngestionCatalog",
    "InstrumentRepository",
    "MarketDataProvider",
    "PriceBarRepository",
    "RawObjectStore",
    "ValidationReportRepository",
]
