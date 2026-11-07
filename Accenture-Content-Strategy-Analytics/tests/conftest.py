"""Shared pytest fixtures of the Social Buzz analytics test suite."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from social_buzz_analytics.application.pipeline import PipelineConfig
from social_buzz_analytics.application.ports import DatasetReader

# --------------------------------------------------------------------------- #
# Canonical sample rows
# --------------------------------------------------------------------------- #

USERS: tuple[dict[str, str], ...] = (
    {
        "user_id": "U000001",
        "user_segment": "active",
        "user_country": "ID",
        "user_age": "28",
        "user_followers": "120",
        "user_created_at": "2025-01-15 08:30:00",
    },
    {
        "user_id": "U000002",
        "user_segment": "VIP",
        "user_country": "US",
        "user_age": "41",
        "user_followers": "15,300",
        "user_created_at": "2024-11-02T10:00:00",
    },
    {
        "user_id": "U000003",
        "user_segment": "Power User",
        "user_country": "GB",
        "user_age": "22",
        "user_followers": "980",
        "user_created_at": "2025-03-11",
    },
    {
        "user_id": "U000004",
        "user_segment": "churn risk",
        "user_country": "DE",
        "user_age": "",
        "user_followers": "-5",
        "user_created_at": "",
    },
)

CONTENT: tuple[dict[str, str], ...] = (
    {
        "content_id": "C000001",
        "content_type": "video",
        "url": "https://socialbuzz.example/p/1",
        "created_at": "2025-02-01 09:00:00",
        "content_body": "Launch teaser",
        "score": "42",
        "category_id": "Technology",
        "content_author_id": "U000001",
    },
    {
        "content_id": "C000002",
        "content_type": "article",
        "url": "https://socialbuzz.example/p/2",
        "created_at": "2025-02-05 09:00:00",
        "content_body": "Match report",
        "score": "17",
        "category_id": "sports",
        "content_author_id": "U000002",
    },
    {
        "content_id": "C000003",
        "content_type": "reel",
        "url": "",
        "created_at": "2025-02-07 09:00:00",
        "content_body": "Food review",
        "score": "9",
        "category_id": "FOOD",
        "content_author_id": "",
    },
    {
        "content_id": "C000004",
        "content_type": "post",
        "url": "https://socialbuzz.example/p/4",
        "created_at": "2025-02-09 09:00:00",
        "content_body": "Uncategorised",
        "score": "3",
        "category_id": "",
        "content_author_id": "U000003",
    },
)

REACTION_TYPES: tuple[dict[str, str], ...] = (
    {"reaction_type": "like", "score": "1"},
    {"reaction_type": "love", "score": "3"},
    {"reaction_type": "wow", "score": "4"},
    {"reaction_type": "haha", "score": "2"},
    {"reaction_type": "insightful", "score": "5"},
    {"reaction_type": "curious", "score": "2"},
    {"reaction_type": "sad", "score": "-1"},
    {"reaction_type": "angry", "score": "-2"},
)

REACTIONS: tuple[dict[str, str], ...] = (
    {"content_id": "C000001", "user_id": "U000001", "reaction_type": "like"},
    {"content_id": "C000001", "user_id": "U000002", "reaction_type": "LOVE"},
    {"content_id": "C000001", "user_id": "U000003", "reaction_type": "wow"},
    {"content_id": "C000002", "user_id": "U000001", "reaction_type": "haha"},
    {"content_id": "C000002", "user_id": "U000002", "reaction_type": "like"},
    {"content_id": "C000003", "user_id": "U000003", "reaction_type": "insightful"},
)

COMMENTS: tuple[dict[str, str], ...] = (
    {
        "comment_id": "CM0000001",
        "content_id": "C000001",
        "user_id": "U000001",
        "comment_text": "Great release",
        "comment_time": "2025-02-02 09:00:00",
        "comment_sentiment": "0.8",
    },
    {
        "comment_id": "CM0000002",
        "content_id": "C000001",
        "user_id": "U000002",
        "comment_text": "Not convinced",
        "comment_time": "2025-02-03 09:00:00",
        "comment_sentiment": "-0.6",
    },
    {
        "comment_id": "CM0000003",
        "content_id": "C000002",
        "user_id": "U000003",
        "comment_text": "Good match",
        "comment_time": "2025-02-04 09:00:00",
        "comment_sentiment": "0.2",
    },
)

PAGE_SHARES: tuple[dict[str, str], ...] = (
    {"content_id": "C000001", "share_date": "2025-02-02 10:00:00", "share_user_id": "U000003"},
    {"content_id": "C000002", "share_date": "2025-02-03 10:00:00", "share_user_id": "U000001"},
)

PAGE_VIEWS: tuple[dict[str, str], ...] = (
    {
        "content_id": "C000001",
        "view_date": "2025-02-01 12:00:00",
        "view_user_id": "U000001",
        "view_seconds": "45",
    },
    {
        "content_id": "C000001",
        "view_date": "2025-02-01 13:00:00",
        "view_user_id": "U000002",
        "view_seconds": "90",
    },
    {
        "content_id": "C000001",
        "view_date": "2025-02-02 12:00:00",
        "view_user_id": "U000003",
        "view_seconds": "30",
    },
    {
        "content_id": "C000002",
        "view_date": "2025-02-03 12:00:00",
        "view_user_id": "U000001",
        "view_seconds": "60",
    },
    {
        "content_id": "C000003",
        "view_date": "2025-02-04 12:00:00",
        "view_user_id": "U000002",
        "view_seconds": "15",
    },
)

DATASETS: Mapping[str, Sequence[Mapping[str, str]]] = {
    "Users.csv": USERS,
    "Content.csv": CONTENT,
    "ReactionTypes.csv": REACTION_TYPES,
    "Reactions.csv": REACTIONS,
    "Comments.csv": COMMENTS,
    "PageShares.csv": PAGE_SHARES,
    "PageViews.csv": PAGE_VIEWS,
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class InMemoryDatasetReader(DatasetReader):
    """A :class:`DatasetReader` serving datasets from a dictionary.

    Parameters:
        datasets:
            The raw rows, keyed by file name.
        fail_on:
            Optional file names that must raise ``FileNotFoundError``.
    """

    def __init__(
        self,
        datasets: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        fail_on: Iterable[str] = (),
    ) -> None:
        """Initialize the reader."""
        self._datasets = dict(datasets if datasets is not None else DATASETS)
        self._fail_on = set(fail_on)
        self.read_calls: list[Path] = []

    def read(self, path: Path) -> Any:
        """Yield the rows of the dataset named ``path.name``."""
        self.read_calls.append(path)
        if path.name in self._fail_on:
            raise FileNotFoundError(path)
        rows = self._datasets.get(path.name)
        if rows is None:
            raise FileNotFoundError(path)
        return iter([dict(row) for row in rows])


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], header: Sequence[str]) -> Path:
    """Write ``rows`` into ``path`` as a CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(header))
        writer.writeheader()
        writer.writerows(rows)
    return path


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def sample_datasets() -> Mapping[str, Sequence[Mapping[str, str]]]:
    """Return the canonical sample datasets."""
    return DATASETS


@pytest.fixture
def reader() -> InMemoryDatasetReader:
    """Return an in-memory dataset reader serving the sample datasets."""
    return InMemoryDatasetReader()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Return a directory holding the sample datasets as CSV files."""
    directory = tmp_path / "raw"
    directory.mkdir()
    for name, rows in DATASETS.items():
        header = list(rows[0]) if rows else []
        write_csv(directory / name, rows, header)
    return directory


@pytest.fixture
def config(data_dir: Path, tmp_path: Path) -> PipelineConfig:
    """Return a pipeline configuration pointing at the sample datasets."""
    return PipelineConfig(
        data_dir=data_dir,
        output_dir=tmp_path / "processed",
        top_n=5,
    )
