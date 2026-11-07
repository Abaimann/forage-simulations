"""Value objects of the Social Buzz engagement analytics domain.

The domain layer is intentionally free of I/O, framework and persistence
concerns.  It only describes *what* the business concepts are and the
invariants they must satisfy.  Application services orchestrate, adapters
perform I/O.

Layering (dependencies point inwards only)::

    infrastructure  ->  application  ->  domain
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Any, Final

__all__ = [
    "Channel",
    "ContentType",
    "ReactionType",
    "SentimentLabel",
    "UserSegment",
    "canonical_text",
    "normalize_category",
]


def canonical_text(raw: Any) -> str:
    """Normalize an arbitrary raw cell into a canonical comparable string.

    The transformation is intentionally conservative and deterministic:

    1. ``None`` becomes an empty string.
    2. Unicode is NFKC-normalized and converted to lowercase.
    3. Runs of whitespace collapse into a single space.
    4. Leading/trailing whitespace is removed.

    This function is meant for *descriptive* fields (labels, categories,
    segments).  Identifiers must be handled with
    :func:`normalize_identifier`, which preserves their case.

    Parameters
    ----------
    raw:
        Any value coming from a CSV cell or a configuration mapping.

    Returns
    -------
    str
        The canonical form of ``raw``; never ``None``.
    """
    if raw is None:
        return ""
    text = raw if isinstance(raw, str) else str(raw)
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", text).strip()


def normalize_identifier(raw: Any) -> str:
    """Normalize a primary or foreign key while preserving its case.

    Identifiers are case-sensitive business keys: ``"C000001"`` and
    ``"c000001"`` are *not* the same content item.  The normalization
    therefore only removes the surrounding whitespace and normalizes the
    Unicode form, and never lower-cases the value.

    Parameters
    ----------
    raw:
        Any value coming from a CSV cell.

    Returns
    -------
    str
        The trimmed identifier; never ``None``.
    """
    if raw is None:
        return ""
    text = raw if isinstance(raw, str) else str(raw)
    return unicodedata.normalize("NFKC", text).strip()


_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"[\s_\-]+")


class SentimentLabel(str, Enum):
    """Coarse sentiment polarity attached to a reaction or a review."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"

    @property
    def sign(self) -> int:
        """Numeric sign of the polarity (``+1``, ``0`` or ``-1``)."""
        return _SENTIMENT_SIGNS[self]

    @classmethod
    def from_score(cls, score: float, neutral_band: float = 0.1) -> SentimentLabel:
        """Derive a label from a continuous score in the ``[-1, 1]`` range.

        Parameters
        ----------
        score:
            Continuous sentiment score; values outside ``[-1, 1]`` are clamped.
        neutral_band:
            Absolute score below which the polarity is considered neutral.

        Returns
        -------
        SentimentLabel
            The derived polarity label.
        """
        clamped = max(-1.0, min(1.0, float(score)))
        if clamped > neutral_band:
            return cls.POSITIVE
        if clamped < -neutral_band:
            return cls.NEGATIVE
        return cls.NEUTRAL

    def __str__(self) -> str:
        return self.value


_SENTIMENT_SIGNS: Final[dict[SentimentLabel, int]] = {
    SentimentLabel.POSITIVE: 1,
    SentimentLabel.NEUTRAL: 0,
    SentimentLabel.NEGATIVE: -1,
}


class ReactionType(str, Enum):
    """A reaction a user can attach to a piece of content.

    Each reaction carries a *weight* (``score``) used by the engagement
    aggregation and a *sentiment polarity* used by the sentiment analysis.
    """

    LIKE = "like"
    LOVE = "love"
    HAHA = "haha"
    WOW = "wow"
    INSIGHTFUL = "insightful"
    CURIOUS = "curious"
    SAD = "sad"
    ANGRY = "angry"

    @property
    def score(self) -> int:
        """Engagement weight of the reaction (positive = amplifying)."""
        return _REACTION_SCORES[self]

    @property
    def sentiment(self) -> SentimentLabel:
        """Sentiment polarity carried by the reaction."""
        return _REACTION_SENTIMENTS[self]

    @classmethod
    def from_raw(cls, raw: Any) -> ReactionType:
        """Resolve a reaction type from a heterogeneous raw label.

        Handles casing, whitespace, hyphen/underscore separators and the
        common legacy synonyms found in the exported data.

        Raises
        ------
        ValueError
            If the label cannot be mapped to a known reaction type.
        """
        if isinstance(raw, ReactionType):
            return raw
        key = _WHITESPACE_RE.sub("_", canonical_text(raw))
        if key in _REACTION_ALIASES:
            return _REACTION_ALIASES[key]
        try:
            return cls(key)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(f"unknown reaction type: {raw!r}") from exc

    def __str__(self) -> str:
        return self.value


_REACTION_SCORES: Final[dict[ReactionType, int]] = {
    ReactionType.LIKE: 1,
    ReactionType.LOVE: 3,
    ReactionType.HAHA: 2,
    ReactionType.WOW: 4,
    ReactionType.INSIGHTFUL: 5,
    ReactionType.CURIOUS: 2,
    ReactionType.SAD: -1,
    ReactionType.ANGRY: -2,
}

_REACTION_SENTIMENTS: Final[dict[ReactionType, SentimentLabel]] = {
    ReactionType.LIKE: SentimentLabel.POSITIVE,
    ReactionType.LOVE: SentimentLabel.POSITIVE,
    ReactionType.HAHA: SentimentLabel.POSITIVE,
    ReactionType.WOW: SentimentLabel.POSITIVE,
    ReactionType.INSIGHTFUL: SentimentLabel.POSITIVE,
    ReactionType.CURIOUS: SentimentLabel.NEUTRAL,
    ReactionType.SAD: SentimentLabel.NEGATIVE,
    ReactionType.ANGRY: SentimentLabel.NEGATIVE,
}

_REACTION_ALIASES: Final[dict[str, ReactionType]] = {
    "like": ReactionType.LIKE,
    "likes": ReactionType.LIKE,
    "liked": ReactionType.LIKE,
    "thumbs_up": ReactionType.LIKE,
    "thumbsup": ReactionType.LIKE,
    "love": ReactionType.LOVE,
    "loved": ReactionType.LOVE,
    "heart": ReactionType.LOVE,
    "haha": ReactionType.HAHA,
    "lol": ReactionType.HAHA,
    "funny": ReactionType.HAHA,
    "wow": ReactionType.WOW,
    "amazing": ReactionType.WOW,
    "insightful": ReactionType.INSIGHTFUL,
    "insight": ReactionType.INSIGHTFUL,
    "curious": ReactionType.CURIOUS,
    "curiosity": ReactionType.CURIOUS,
    "sad": ReactionType.SAD,
    "sigh": ReactionType.SAD,
    "angry": ReactionType.ANGRY,
    "mad": ReactionType.ANGRY,
}


class ContentType(str, Enum):
    """Format of a piece of content."""

    VIDEO = "video"
    IMAGE = "image"
    ARTICLE = "article"
    LINK = "link"
    POST = "post"
    STORY = "story"
    REEL = "reel"
    LIVE = "live"

    @classmethod
    def from_raw(cls, raw: Any) -> ContentType:
        """Resolve a content type from a heterogeneous raw label.

        Raises
        ------
        ValueError
            If the label cannot be mapped to a known content type.
        """
        if isinstance(raw, ContentType):
            return raw
        key = _WHITESPACE_RE.sub("_", canonical_text(raw))
        if key in _CONTENT_TYPE_ALIASES:
            return _CONTENT_TYPE_ALIASES[key]
        try:
            return cls(key)
        except ValueError as exc:
            raise ValueError(f"unknown content type: {raw!r}") from exc

    def __str__(self) -> str:
        return self.value


_CONTENT_TYPE_ALIASES: Final[dict[str, ContentType]] = {
    "video": ContentType.VIDEO,
    "videos": ContentType.VIDEO,
    "clip": ContentType.VIDEO,
    "image": ContentType.IMAGE,
    "images": ContentType.IMAGE,
    "photo": ContentType.IMAGE,
    "picture": ContentType.IMAGE,
    "article": ContentType.ARTICLE,
    "blog": ContentType.ARTICLE,
    "story": ContentType.STORY,
    "stories": ContentType.STORY,
    "link": ContentType.LINK,
    "url": ContentType.LINK,
    "post": ContentType.POST,
    "text": ContentType.POST,
    "status": ContentType.POST,
    "reel": ContentType.REEL,
    "reels": ContentType.REEL,
    "short": ContentType.REEL,
    "live": ContentType.LIVE,
    "livestream": ContentType.LIVE,
}


class UserSegment(str, Enum):
    """Lifecycle segment of an audience member."""

    NEW = "new"
    ACTIVE = "active"
    POWER_USER = "power_user"
    VIP = "vip"
    CHURN_RISK = "churn_risk"

    @classmethod
    def from_raw(cls, raw: Any) -> UserSegment:
        """Resolve a user segment from a heterogeneous raw label.

        Unknown or empty labels fall back to :attr:`ACTIVE`, because an
        unknown segment must not silently remove a user from the funnel.

        Raises
        ------
        ValueError
            Never; unknown labels degrade to ``ACTIVE``.
        """
        if isinstance(raw, UserSegment):
            return raw
        key = _WHITESPACE_RE.sub("_", canonical_text(raw))
        if key in _USER_SEGMENT_ALIASES:
            return _USER_SEGMENT_ALIASES[key]
        return cls.ACTIVE

    def __str__(self) -> str:
        return self.value


_USER_SEGMENT_ALIASES: Final[dict[str, UserSegment]] = {
    "new": UserSegment.NEW,
    "newcomer": UserSegment.NEW,
    "registered": UserSegment.NEW,
    "active": UserSegment.ACTIVE,
    "regular": UserSegment.ACTIVE,
    "engaged": UserSegment.ACTIVE,
    "power_user": UserSegment.POWER_USER,
    "poweruser": UserSegment.POWER_USER,
    "heavy_user": UserSegment.POWER_USER,
    "vip": UserSegment.VIP,
    "champion": UserSegment.VIP,
    "superstar": UserSegment.VIP,
    "churn_risk": UserSegment.CHURN_RISK,
    "churn": UserSegment.CHURN_RISK,
    "at_risk": UserSegment.CHURN_RISK,
    "lapsing": UserSegment.CHURN_RISK,
}


class Channel(str, Enum):
    """Distribution channel a piece of content was published on."""

    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    X = "x"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    BLOG = "blog"
    NEWSLETTER = "newsletter"

    @classmethod
    def from_raw(cls, raw: Any) -> Channel:
        """Resolve a channel from a heterogeneous raw label.

        Raises
        ------
        ValueError
            If the label cannot be mapped to a known channel.
        """
        if isinstance(raw, Channel):
            return raw
        key = _WHITESPACE_RE.sub("_", canonical_text(raw))
        if key in _CHANNEL_ALIASES:
            return _CHANNEL_ALIASES[key]
        try:
            return cls(key)
        except ValueError as exc:
            raise ValueError(f"unknown channel: {raw!r}") from exc

    def __str__(self) -> str:
        return self.value


_CHANNEL_ALIASES: Final[dict[str, Channel]] = {
    "instagram": Channel.INSTAGRAM,
    "ig": Channel.INSTAGRAM,
    "insta": Channel.INSTAGRAM,
    "tiktok": Channel.TIKTOK,
    "tt": Channel.TIKTOK,
    "youtube": Channel.YOUTUBE,
    "yt": Channel.YOUTUBE,
    "x": Channel.X,
    "twitter": Channel.X,
    "linkedin": Channel.LINKEDIN,
    "li": Channel.LINKEDIN,
    "facebook": Channel.FACEBOOK,
    "fb": Channel.FACEBOOK,
    "blog": Channel.BLOG,
    "website": Channel.BLOG,
    "newsletter": Channel.NEWSLETTER,
    "email": Channel.NEWSLETTER,
}


#: Canonical content taxonomy.
#:
#: The keys are the *normalized* forms of the category names (lowercase,
#: whitespace-collapsed); the values are the executive-facing display
#: names.  Several aliases may point at the same display name: the alias
#: table is the single source of truth for the harmonization of the
#: ``category_id`` column of the ``Content`` dataset.
CATEGORY_ALIASES: Final[dict[str, str]] = {
    "technology": "Technology",
    "tech": "Technology",
    "technolgy": "Technology",
    "entertainment": "Entertainment",
    "entertaiment": "Entertainment",
    "entertainemnt": "Entertainment",
    "ent": "Entertainment",
    "sports": "Sports",
    "sport": "Sports",
    "finance": "Finance",
    "financial": "Finance",
    "business": "Business",
    "lifestyle": "Lifestyle",
    "life style": "Lifestyle",
    "health": "Health",
    "health wellness": "Health",
    "wellness": "Health",
    "food": "Food",
    "food drink": "Food",
    "travel": "Travel",
    "education": "Education",
    "educational": "Education",
    "gaming": "Gaming",
    "games": "Gaming",
    "news": "News",
    "beauty": "Beauty",
    "fashion": "Fashion",
    "other": "Other",
}

#: Display names of the canonical taxonomy, in presentation order.
CANONICAL_CATEGORIES: Final[tuple[str, ...]] = (
    "Technology",
    "Entertainment",
    "Sports",
    "Finance",
    "Lifestyle",
    "Health",
    "Food",
    "Travel",
    "Education",
    "Gaming",
    "Business",
    "News",
    "Beauty",
    "Fashion",
    "Other",
)


def normalize_category(raw: Any, default: str = "Other") -> str:
    """Map a raw content category onto the canonical taxonomy.

    The lookup is case-insensitive and tolerant of the spelling variants
    present in the source exports (``entertaiment``, ``life style``, ...).
    Categories that cannot be resolved are mapped to ``default`` so that no
    reaction is ever lost because of an unmapped label.

    Parameters
    ----------
    raw:
        The raw category label.
    default:
        Display name used when the label cannot be resolved.

    Returns
    -------
    str
        A canonical category display name.
    """
    key = canonical_text(raw)
    if not key:
        return default
    if key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[key]
    # Strip trailing qualifiers such as "technology & innovation".
    head = key.split("&")[0].strip()
    if head in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[head]
    head = head.split("/")[0].strip()
    if head in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[head]
    return default
