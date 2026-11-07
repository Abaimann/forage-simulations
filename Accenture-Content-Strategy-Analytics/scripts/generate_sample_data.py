"""Generate a realistic, deliberately dirty Social Buzz sample dataset.

The generator produces the seven CSV datasets of the Social Buzz platform
with a schema that mirrors the production exports::

    Content.csv        content_id, content_type, url, created_at, content_body,
                       score, category_id, content_author_id
    Reactions.csv      content_id, user_id, reaction_type
    ReactionTypes.csv  reaction_type, score
    Users.csv          user_id, user_segment, user_country, user_age,
                       user_followers, user_created_at
    Comments.csv       comment_id, content_id, user_id, comment_text,
                       comment_time, comment_sentiment
    PageShares.csv     content_id, share_date, share_user_id
    PageViews.csv      content_id, view_date, view_user_id, view_seconds

The generator models the platform with an explicit *popularity* model: every
content item draws a reach factor, the reach factor of a category is scaled
by its affinity, and the event datasets are then allocated proportionally
to that reach.  This is what makes the resulting engagement rates realistic
(a few percent of the views) and what makes the top-5 leaderboard a
meaningful business signal rather than an artefact of the sample size.

The data is *intentionally dirty* so that the cleaning pipeline has real
work to do:

* missing values in every optional column;
* inconsistent category spellings and casings;
* unknown reaction types and content types;
* outliers in scores, follower counts, ages and dwell times;
* duplicated rows and duplicated natural keys;
* orphan foreign keys (events referencing a non-existent content item);
* several timestamp formats.

Usage::

    python scripts/generate_sample_data.py --output data/raw --users 8000
"""

from __future__ import annotations

import argparse
import csv
import random
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #

#: Deliberately inconsistent spellings of the categories below.  They model
#: the manual re-tagging drift observed in the production exports.
CATEGORY_VARIANTS: Final[dict[str, tuple[str, ...]]] = {
    "Technology": ("tech", "TECH", " Technology ", "technology", "Technolgy"),
    "Entertainment": ("entertainment", "Entertainment", "entertaiment", "ENT"),
    "Sports": ("sports", "Sport", "sports ", "SPORTS"),
    "Finance": ("finance", "Financial", "finance "),
    "Lifestyle": ("lifestyle", "Life Style", "lifestyle "),
    "Health": ("health", "Health & Wellness", "health"),
    "Food": ("food", "Food & Drink", "FOOD"),
    "Travel": ("travel", "Travel ", "travel"),
    "Education": ("education", "Educational", "education "),
    "Gaming": ("gaming", "Games", "gaming"),
}

CONTENT_TYPES: Final[tuple[str, ...]] = (
    "video",
    "image",
    "article",
    "link",
    "post",
    "story",
    "reel",
    "live",
)

CONTENT_TYPE_VARIANTS: Final[dict[str, tuple[str, ...]]] = {
    "video": ("video", "Video", "VIDEO", "videos"),
    "image": ("image", "Image", "photo", "IMG"),
    "article": ("article", "Article", "blog"),
    "link": ("link", "Link", "url"),
    "post": ("post", "Post", "text"),
    "story": ("story", "Story", "stories"),
    "reel": ("reel", "Reel", "short"),
    "live": ("live", "Live", "livestream"),
}

REACTION_TYPES: Final[tuple[tuple[str, int], ...]] = (
    ("like", 1),
    ("love", 3),
    ("haha", 2),
    ("wow", 4),
    ("insightful", 5),
    ("curious", 2),
    ("sad", -1),
    ("angry", -2),
)

REACTION_TYPE_VARIANTS: Final[dict[str, tuple[str, ...]]] = {
    "like": ("like", "Like", "LIKE", "likes"),
    "love": ("love", "Love", "LOVE", "heart"),
    "haha": ("haha", "Haha", "lol"),
    "wow": ("wow", "Wow", "amazing"),
    "insightful": ("insightful", "Insightful", "insight"),
    "curious": ("curious", "Curious", "curiosity"),
    "sad": ("sad", "Sad", "sigh"),
    "angry": ("angry", "Angry", "mad"),
}

SEGMENTS: Final[tuple[str, ...]] = ("new", "active", "power_user", "vip", "churn_risk")
SEGMENT_VARIANTS: Final[dict[str, tuple[str, ...]]] = {
    "new": ("new", "New", "newcomer"),
    "active": ("active", "Active", "regular"),
    "power_user": ("power_user", "Power User", "heavy_user"),
    "vip": ("vip", "VIP", "champion"),
    "churn_risk": ("churn_risk", "Churn Risk", "at_risk"),
}

COUNTRIES: Final[tuple[str, ...]] = (
    "ID", "US", "GB", "DE", "FR", "BR", "IN", "JP", "SG", "AU", "CA", "NG",
)

#: Share of the content catalogue held by every category.
CATEGORY_WEIGHTS: Final[dict[str, float]] = {
    "Technology": 0.22,
    "Entertainment": 0.20,
    "Sports": 0.14,
    "Lifestyle": 0.11,
    "Finance": 0.09,
    "Gaming": 0.08,
    "Food": 0.06,
    "Travel": 0.05,
    "Health": 0.03,
    "Education": 0.02,
}

#: Reach multiplier of every category.  It scales the popularity of the
#: content items of the category, which drives the volume of the events and
#: therefore the position of the category in the engagement leaderboard.
CATEGORY_AFFINITY: Final[dict[str, float]] = {
    "Technology": 1.55,
    "Entertainment": 1.40,
    "Sports": 1.25,
    "Gaming": 1.05,
    "Lifestyle": 0.95,
    "Finance": 0.85,
    "Food": 0.80,
    "Travel": 0.75,
    "Health": 0.65,
    "Education": 0.55,
}

#: Share of the comments that are negative, per category.  It shapes the
#: sentiment profile of every segment.
CATEGORY_NEGATIVITY: Final[dict[str, float]] = {
    "Technology": 0.10,
    "Entertainment": 0.12,
    "Sports": 0.18,
    "Gaming": 0.22,
    "Lifestyle": 0.14,
    "Finance": 0.20,
    "Food": 0.08,
    "Travel": 0.09,
    "Health": 0.15,
    "Education": 0.11,
}

_BODY_FRAGMENTS: Final[tuple[str, ...]] = (
    "Our team finally shipped the new dashboard and the numbers are in.",
    "Three lessons we learned from a quarter of community feedback.",
    "Everything you need to know before the weekend event starts.",
    "A behind-the-scenes look at how the campaign was produced.",
    "The results surprised even the analysts who wrote the model.",
    "We asked the community and the answers were surprisingly mixed.",
    "A short guide to getting the most out of the new release.",
    "Five creators share what they would do differently next time.",
)

_COMMENT_FRAGMENTS: Final[tuple[str, ...]] = (
    "This is genuinely useful, thanks for sharing.",
    "Great breakdown, very easy to follow.",
    "I disagree with the second point but the rest is solid.",
    "Not convinced by this argument at all.",
    "The chart is wrong, the values do not match the source.",
    "Love this series, please keep it going.",
    "Interesting topic but the pacing drags in the middle.",
    "Been waiting for this all year.",
)

#: Timestamp layouts present in the exports (deliberately inconsistent).
_DATE_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d",
)

_EPOCH = datetime(2025, 1, 1, tzinfo=timezone.utc)

#: Number of days covered by the observation window.
_WINDOW_DAYS: Final[int] = 540


class _ContentPlan:
    """The generated plan of one content item.

    Attributes:
        content_id: Primary key of the content item.
        category: Canonical category of the content item.
        reach: Relative reach factor of the content item.
        reactions: Number of reactions allocated to the content item.
        views: Number of views allocated to the content item.
        shares: Number of shares allocated to the content item.
        comments: Number of comments allocated to the content item.
    """

    __slots__ = ("category", "comments", "content_id", "reach", "reactions", "shares", "views")

    def __init__(
        self,
        content_id: str,
        category: str,
        reach: float,
        reactions: int,
        views: int,
        shares: int,
        comments: int,
    ) -> None:
        """Initialize the plan of a content item."""
        self.content_id = content_id
        self.category = category
        self.reach = reach
        self.reactions = reactions
        self.views = views
        self.shares = shares
        self.comments = comments


def _weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    """Pick a key of ``weights`` proportionally to its value."""
    keys = list(weights)
    return rng.choices(keys, weights=[weights[key] for key in keys], k=1)[0]


def _maybe(rng: random.Random, probability: float) -> bool:
    """Return ``True`` with the given probability."""
    return rng.random() < probability


def _timestamp(rng: random.Random, days: int = _WINDOW_DAYS) -> datetime:
    """Draw a random timestamp inside the observation window."""
    return _EPOCH + timedelta(
        days=rng.randint(0, days),
        hours=rng.randint(0, 23),
        minutes=rng.randint(0, 59),
        seconds=rng.randint(0, 59),
    )


def _format_timestamp(rng: random.Random, moment: datetime) -> str:
    """Format a timestamp using one of the inconsistent export layouts."""
    return moment.strftime(rng.choice(_DATE_FORMATS))


def _allocate(total: int, weights: Sequence[float]) -> list[int]:
    """Split ``total`` into integer buckets proportional to ``weights``.

    The allocation is exact: the buckets always sum up to ``total``, so no
    event is lost or invented by the rounding.
    """
    if total <= 0 or not weights:
        return [0] * len(weights)
    weight_sum = sum(weights)
    if weight_sum <= 0:
        return [0] * len(weights)
    raw = [total * weight / weight_sum for weight in weights]
    buckets = [int(value) for value in raw]
    remainder = total - sum(buckets)
    # Hand the remaining events to the largest fractional parts.
    order = sorted(range(len(raw)), key=lambda i: raw[i] - buckets[i], reverse=True)
    for index in order[:remainder]:
        buckets[index] += 1
    return buckets


def _build_plan(
    rng: random.Random,
    contents: int,
    reactions: int,
    views: int,
    shares: int,
    comments: int,
) -> list[_ContentPlan]:
    """Build the reach-driven allocation plan of the content items."""
    categories = [_weighted_choice(rng, CATEGORY_WEIGHTS) for _ in range(contents)]
    reach = [
        rng.lognormvariate(0.0, 0.85) * CATEGORY_AFFINITY[category] for category in categories
    ]
    reaction_buckets = _allocate(reactions, reach)
    view_buckets = _allocate(views, [value**0.92 for value in reach])
    share_buckets = _allocate(shares, [value**1.08 for value in reach])
    comment_buckets = _allocate(comments, [value**0.85 for value in reach])

    return [
        _ContentPlan(
            content_id=f"C{index + 1:06d}",
            category=categories[index],
            reach=reach[index],
            reactions=reaction_buckets[index],
            views=view_buckets[index],
            shares=share_buckets[index],
            comments=comment_buckets[index],
        )
        for index in range(contents)
    ]


def generate(
    output_dir: Path,
    users: int = 8_000,
    contents: int = 4_500,
    reactions: int = 120_000,
    comments: int = 18_000,
    shares: int = 9_000,
    views: int = 1_200_000,
    seed: int = 20240,
) -> dict[str, int]:
    """Generate the seven sample datasets.

    Parameters
    ----------
    output_dir:
        The directory receiving the CSV files.
    users:
        Number of users to generate.
    contents:
        Number of content items to generate.
    reactions:
        Number of reaction events to generate.
    comments:
        Number of comments to generate.
    shares:
        Number of shares to generate.
    views:
        Number of page views to generate.
    seed:
        Seed of the random generator, for reproducibility.

    Returns
    -------
    dict[str, int]
        The number of rows written per dataset.
    """
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    plan = _build_plan(rng, contents, reactions, views, shares, comments)

    counts: dict[str, int] = {}
    counts["Users"] = _write_users(output_dir, rng, users)
    counts["Content"] = _write_content(output_dir, rng, plan, users)
    counts["ReactionTypes"] = _write_reaction_types(output_dir, rng)
    counts["Reactions"] = _write_reactions(output_dir, rng, plan, users)
    counts["Comments"] = _write_comments(output_dir, rng, plan, users)
    counts["PageShares"] = _write_shares(output_dir, rng, plan, users)
    counts["PageViews"] = _write_views(output_dir, rng, plan, users)
    return counts


def _write_users(output_dir: Path, rng: random.Random, users: int) -> int:
    """Write the ``Users`` dataset."""
    rows: list[dict[str, str]] = []
    for index in range(1, users + 1):
        segment = rng.choices(SEGMENTS, weights=(0.28, 0.34, 0.14, 0.08, 0.16), k=1)[0]
        age = rng.randint(13, 72)
        # A small share of the rows carries an impossible age.
        if _maybe(rng, 0.012):
            age = rng.choice((-5, 0, 150, 999))
        followers = rng.randint(0, 45_000)
        if _maybe(rng, 0.004):
            followers = rng.randint(1_000_000, 9_000_000)
        rows.append(
            {
                "user_id": f"U{index:06d}",
                "user_segment": rng.choice(SEGMENT_VARIANTS[segment]),
                "user_country": rng.choice(COUNTRIES) if not _maybe(rng, 0.03) else "",
                "user_age": str(age),
                "user_followers": str(followers),
                "user_created_at": _format_timestamp(rng, _timestamp(rng, 900)),
            }
        )
    # Duplicated users (the export was concatenated twice for part of the file).
    duplicates = rows[: max(1, len(rows) // 200)]
    rows.extend(duplicates)
    _write_csv(output_dir / "Users.csv", rows, list(rows[0]))
    return len(rows)


def _write_content(
    output_dir: Path, rng: random.Random, plan: Sequence[_ContentPlan], users: int
) -> int:
    """Write the ``Content`` dataset."""
    rows: list[dict[str, str]] = []
    for item in plan:
        content_type = rng.choices(
            CONTENT_TYPES, weights=(0.24, 0.22, 0.14, 0.12, 0.12, 0.08, 0.05, 0.03), k=1
        )[0]
        score = rng.randint(0, 480)
        if _maybe(rng, 0.006):
            score = rng.randint(90_000, 250_000)
        rows.append(
            {
                "content_id": item.content_id,
                "content_type": rng.choice(CONTENT_TYPE_VARIANTS[content_type]),
                "url": (
                    f"https://socialbuzz.example/p/{item.content_id}"
                    if not _maybe(rng, 0.02)
                    else ""
                ),
                "created_at": _format_timestamp(rng, _timestamp(rng)),
                "content_body": rng.choice(_BODY_FRAGMENTS),
                "score": str(score),
                "category_id": rng.choice(CATEGORY_VARIANTS[item.category]),
                "content_author_id": (
                    f"U{rng.randint(1, users):06d}" if not _maybe(rng, 0.01) else ""
                ),
            }
        )
    # A handful of content items have no category at all.
    for row in rng.sample(rows, k=max(1, len(rows) // 300)):
        row["category_id"] = ""
    # Duplicated content rows.
    rows.extend(rng.sample(rows, k=max(1, len(rows) // 400)))
    _write_csv(output_dir / "Content.csv", rows, list(rows[0]))
    return len(rows)


def _write_reaction_types(output_dir: Path, rng: random.Random) -> int:
    """Write the ``ReactionTypes`` reference dataset."""
    rows = [{"reaction_type": name, "score": str(score)} for name, score in REACTION_TYPES]
    # An unknown reaction type (a taxonomy the reference table never learned).
    rows.append({"reaction_type": "confused", "score": "0"})
    # A duplicated definition.
    rows.append({"reaction_type": "like", "score": "1"})
    _write_csv(output_dir / "ReactionTypes.csv", rows, list(rows[0]))
    return len(rows)


def _write_reactions(
    output_dir: Path, rng: random.Random, plan: Sequence[_ContentPlan], users: int
) -> int:
    """Write the ``Reactions`` dataset."""
    rows: list[dict[str, str]] = []
    orphan_content = f"C{len(plan) + 1:06d}"
    positive_weights = (0.34, 0.16, 0.18, 0.09, 0.05, 0.06, 0.06, 0.06)

    for item in plan:
        for _ in range(item.reactions):
            content_id = item.content_id
            if _maybe(rng, 0.004):
                content_id = orphan_content
            base = rng.choices(
                [name for name, _ in REACTION_TYPES], weights=positive_weights, k=1
            )[0]
            reaction_type = rng.choice(REACTION_TYPE_VARIANTS[base])
            if _maybe(rng, 0.003):
                reaction_type = rng.choice(("spooked", "confused", "hmm"))
            if _maybe(rng, 0.005):
                reaction_type = ""
            rows.append(
                {
                    "content_id": content_id,
                    "user_id": f"U{rng.randint(1, users):06d}",
                    "reaction_type": reaction_type,
                }
            )
    # Duplicated reaction events (retried deliveries of the same event).
    rows.extend(rng.sample(rows, k=max(1, len(rows) // 150)))
    _write_csv(output_dir / "Reactions.csv", rows, list(rows[0]))
    return len(rows)


def _write_comments(
    output_dir: Path, rng: random.Random, plan: Sequence[_ContentPlan], users: int
) -> int:
    """Write the ``Comments`` dataset."""
    rows: list[dict[str, str]] = []
    for item in plan:
        negativity = CATEGORY_NEGATIVITY[item.category]
        for _ in range(item.comments):
            sentiment = rng.gauss(0.35 - 0.9 * negativity, 0.42)
            if _maybe(rng, 0.01):
                sentiment = rng.choice((-4.5, 3.9, 12.0))
            rows.append(
                {
                    "comment_id": f"CM{len(rows) + 1:07d}",
                    "content_id": item.content_id,
                    "user_id": f"U{rng.randint(1, users):06d}",
                    "comment_text": rng.choice(_COMMENT_FRAGMENTS),
                    "comment_time": _format_timestamp(rng, _timestamp(rng)),
                    "comment_sentiment": f"{sentiment:.4f}",
                }
            )
    # A few comments miss their sentiment score entirely.
    for row in rng.sample(rows, k=max(1, len(rows) // 200)):
        row["comment_sentiment"] = ""
    # Duplicated comments (same author on the same content item).
    rows.extend(rng.sample(rows, k=max(1, len(rows) // 250)))
    _write_csv(output_dir / "Comments.csv", rows, list(rows[0]))
    return len(rows)


def _write_shares(
    output_dir: Path, rng: random.Random, plan: Sequence[_ContentPlan], users: int
) -> int:
    """Write the ``PageShares`` dataset."""
    rows: list[dict[str, str]] = []
    for item in plan:
        for _ in range(item.shares):
            rows.append(
                {
                    "content_id": item.content_id,
                    "share_date": _format_timestamp(rng, _timestamp(rng)),
                    "share_user_id": f"U{rng.randint(1, users):06d}",
                }
            )
    rows.extend(rng.sample(rows, k=max(1, len(rows) // 300)))
    _write_csv(output_dir / "PageShares.csv", rows, list(rows[0]))
    return len(rows)


def _write_views(
    output_dir: Path, rng: random.Random, plan: Sequence[_ContentPlan], users: int
) -> int:
    """Write the ``PageViews`` dataset."""
    rows: list[dict[str, str]] = []
    for item in plan:
        for _ in range(item.views):
            seconds = max(1, int(rng.lognormvariate(4.1, 0.9)))
            if _maybe(rng, 0.002):
                seconds = rng.randint(200_000, 900_000)
            rows.append(
                {
                    "content_id": item.content_id,
                    "view_date": _format_timestamp(rng, _timestamp(rng)),
                    "view_user_id": f"U{rng.randint(1, users):06d}",
                    "view_seconds": str(seconds),
                }
            )
    rows.extend(rng.sample(rows, k=max(1, len(rows) // 400)))
    _write_csv(output_dir / "PageViews.csv", rows, list(rows[0]))
    return len(rows)


def _write_csv(path: Path, rows: Sequence[dict[str, str]], header: Sequence[str]) -> None:
    """Write ``rows`` into ``path`` using ``header`` as the column order."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(header))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    """Run the generator from the command line."""
    parser = argparse.ArgumentParser(
        prog="generate_sample_data.py",
        description="Generate the dirty Social Buzz sample dataset.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw"),
        help="directory receiving the CSV files (default: data/raw)",
    )
    parser.add_argument("--users", type=int, default=8_000, help="number of users")
    parser.add_argument("--contents", type=int, default=4_500, help="number of content items")
    parser.add_argument("--reactions", type=int, default=120_000, help="number of reactions")
    parser.add_argument("--comments", type=int, default=18_000, help="number of comments")
    parser.add_argument("--shares", type=int, default=9_000, help="number of shares")
    parser.add_argument("--views", type=int, default=1_200_000, help="number of page views")
    parser.add_argument("--seed", type=int, default=20240, help="random seed")
    args = parser.parse_args(argv)

    counts = generate(
        output_dir=args.output,
        users=args.users,
        contents=args.contents,
        reactions=args.reactions,
        comments=args.comments,
        shares=args.shares,
        views=args.views,
        seed=args.seed,
    )
    total = sum(counts.values())
    print(f"Generated {total:,} rows into {args.output}:")
    for name, count in counts.items():
        print(f"  {name:<16} {count:>10,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
