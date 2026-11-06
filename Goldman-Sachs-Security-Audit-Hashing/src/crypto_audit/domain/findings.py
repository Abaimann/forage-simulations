"""Audit findings: severity model, finding record and report container."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping

__all__ = [
    "Severity",
    "FindingCategory",
    "AuditFinding",
    "AuditReport",
]


class Severity(str, Enum):
    """Finding severity, ordered from most to least critical."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        """Numeric rank (higher = more severe) used for sorting."""
        return {
            Severity.CRITICAL: 5,
            Severity.HIGH: 4,
            Severity.MEDIUM: 3,
            Severity.LOW: 2,
            Severity.INFO: 1,
        }[self]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class FindingCategory(str, Enum):
    """Stable category codes so findings can be tracked over time."""

    WEAK_ALGORITHM = "WEAK_ALGORITHM"
    MISSING_SALT = "MISSING_SALT"
    SHORT_SALT = "SHORT_SALT"
    WEAK_PARAMETERS = "WEAK_PARAMETERS"
    LOW_ENTROPY = "LOW_ENTROPY"
    PASSWORD_REUSE = "PASSWORD_REUSE"
    POLICY_NON_COMPLIANT = "POLICY_NON_COMPLIANT"
    TIMING_RISK = "TIMING_RISK"
    UPGRADE_REQUIRED = "UPGRADE_REQUIRED"
    COMPLIANT = "COMPLIANT"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class AuditFinding:
    """A single, actionable observation about one credential (or the estate).

    Attributes:
        category: Stable machine-readable category code.
        severity: Severity of the observation.
        username: Affected account, or ``"*"`` for estate-wide findings.
        message: Human-readable description of the issue.
        recommendation: Concrete remediation guidance.
        evidence: Supporting facts (algorithm, salt length, metrics...).
    """

    category: FindingCategory
    severity: Severity
    message: str
    username: str = "*"
    recommendation: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", dict(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "username": self.username,
            "message": self.message,
            "recommendation": self.recommendation,
            "evidence": dict(self.evidence),
        }

    @property
    def sort_key(self) -> tuple[int, str]:
        return (-self.severity.rank, self.username)


@dataclass(frozen=True)
class AuditReport:
    """Aggregated result of an audit run."""

    findings: tuple[AuditFinding, ...] = ()
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    total_credentials: int = 0
    policy: Mapping[str, Any] = field(default_factory=dict)
    statistics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "policy", dict(self.policy))
        object.__setattr__(self, "statistics", dict(self.statistics))

    # ------------------------------------------------------------------
    def by_severity(self, severity: Severity) -> list[AuditFinding]:
        return [f for f in self.findings if f.severity is severity]

    def by_category(self, category: FindingCategory) -> list[AuditFinding]:
        return [f for f in self.findings if f.category is category]

    def severity_counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        return counts

    @property
    def highest_severity(self) -> Severity | None:
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=lambda s: s.rank)

    @property
    def compliant(self) -> bool:
        """True when no CRITICAL/HIGH finding was raised."""
        return not any(
            f.severity in (Severity.CRITICAL, Severity.HIGH) for f in self.findings
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "total_credentials": self.total_credentials,
            "compliant": self.compliant,
            "severity_counts": self.severity_counts(),
            "policy": dict(self.policy),
            "statistics": dict(self.statistics),
            "findings": [f.to_dict() for f in self.findings],
        }

    def __len__(self) -> int:
        return len(self.findings)

    def __iter__(self) -> Iterable[AuditFinding]:
        return iter(self.findings)
