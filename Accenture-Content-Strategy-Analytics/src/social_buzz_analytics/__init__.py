"""Social Buzz - content engagement & sentiment analytics pipeline.

A dependency-free (standard library only) ETL and analytics pipeline that
harmonizes the seven Social Buzz datasets, relates them through
``content_id`` and ``reaction_type``, scores every content category and
produces executive-ready CSV and JSON summaries.

The package follows a clean (hexagonal) architecture::

    infrastructure  ->  application  ->  domain

* ``domain``        - entities, value objects and the scoring rules.
* ``application``   - cleaning, merging, aggregation and orchestration.
* ``infrastructure``- CSV readers/writers and other adapters.
"""

from __future__ import annotations

from .application.pipeline import AnalyticsPipeline, PipelineConfig, PipelineResult
from .domain.entities import EngagementSegment
from .domain.scoring import EngagementScoringService, ScoringWeights

__all__ = [
    "AnalyticsPipeline",
    "EngagementScoringService",
    "EngagementSegment",
    "PipelineConfig",
    "PipelineResult",
    "ScoringWeights",
    "__version__",
]

__version__ = "1.0.0"
