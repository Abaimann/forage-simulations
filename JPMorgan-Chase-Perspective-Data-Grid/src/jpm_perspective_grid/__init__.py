"""J.P. Morgan Chase & Co. -- live Perspective data grid and stream processor.

The package is organised in three layers:

``core``
    Pure domain logic: models, validation, rolling thresholds and the
    aggregation engine.  No I/O, no third party dependencies.
``infrastructure``
    Adapters: mock tick generator, TCP feed server/client and the sinks
    (Perspective table and in-memory buffer).
``application``
    Services orchestrating the flow from the feed to the grid.

The public API is re-exported here for convenience.
"""

from __future__ import annotations

from .application.pipeline import GridPipeline, ThroughputReport, build_pipeline
from .core.aggregator import AggregationStats, QuoteAggregator
from .core.errors import (
    AggregationError,
    FeedConnectionError,
    FeedError,
    FeedProtocolError,
    GridError,
    TickValidationError,
)
from .core.models import (
    GRID_FIELDS,
    KIND_PAIR,
    KIND_SYMBOL,
    TICK_FIELDS,
    Band,
    GridRow,
    Quote,
    Tick,
)
from .core.thresholds import PriceBaseline, RollingRatioTracker, ThresholdPolicy

__all__ = [
    "AggregationError",
    "AggregationStats",
    "Band",
    "FeedConnectionError",
    "FeedError",
    "FeedProtocolError",
    "GRID_FIELDS",
    "GridError",
    "GridPipeline",
    "GridRow",
    "KIND_PAIR",
    "KIND_SYMBOL",
    "PriceBaseline",
    "Quote",
    "QuoteAggregator",
    "RollingRatioTracker",
    "TICK_FIELDS",
    "ThroughputReport",
    "ThresholdPolicy",
    "Tick",
    "TickValidationError",
    "build_pipeline",
]

__version__ = "1.0.0"
