"""The four DORA metrics as pure functions over deployments and the commits they shipped.

Nothing here talks to GitHub, so every definition is unit-tested in isolation.

Definitions used (see docs/dora-metrics.md for the reasoning and the limits):

- Deployment frequency: successful production deployments per week in the window.
- Lead time for changes: for every commit shipped by a successful deployment, the time from
  the commit landing (committer date) to that deployment finishing. Reported as the median.
- Change failure rate: share of deployment attempts that failed, or that shipped a change
  which a later deployment had to revert or hotfix.
- Time to restore: for each failed deployment, the time until the next successful
  deployment of the same repository finished. Reported as the median.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

REMEDIATION = re.compile(r'^Revert "|\bhotfix\b|\brollback\b|\broll back\b', re.IGNORECASE)


@dataclass(frozen=True)
class Commit:
    sha: str
    committed_at: datetime
    message: str


@dataclass(frozen=True)
class Deployment:
    repo: str
    sha: str
    environment: str
    created_at: datetime
    finished_at: datetime
    succeeded: bool
    source: str  # "deployments" or "releases"
    commits: tuple[Commit, ...] = ()  # commits first shipped by this deployment


@dataclass
class RepoMetrics:
    repo: str
    source: str  # where deployments came from, or "none"
    window_days: int
    attempts: int = 0
    successes: int = 0
    deploys_per_week: float = 0.0
    lead_time_hours: list[float] = field(default_factory=list)
    failures: int = 0
    change_failure_rate: float | None = None
    restore_hours: list[float] = field(default_factory=list)
    unrestored_failures: int = 0

    @property
    def median_lead_time_hours(self) -> float | None:
        return median(self.lead_time_hours)

    @property
    def median_restore_hours(self) -> float | None:
        return median(self.restore_hours)


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600


def in_window(deploys: list[Deployment], start: datetime, end: datetime) -> list[Deployment]:
    return sorted((d for d in deploys if start <= d.finished_at < end), key=lambda d: d.finished_at)


def deployment_frequency(deploys: list[Deployment], window_days: int) -> float:
    """Successful deployments per week."""
    successes = sum(1 for d in deploys if d.succeeded)
    return successes / (window_days / 7)


def lead_times(deploys: list[Deployment]) -> list[float]:
    """Commit-to-production hours for every commit shipped by a successful deployment."""
    return [
        max(0.0, hours(d.finished_at - c.committed_at))
        for d in deploys
        if d.succeeded
        for c in d.commits
    ]


def failed_flags(deploys: list[Deployment]) -> list[bool]:
    """Per deployment (in time order): did this deployment count as a change failure?

    A deployment fails if the attempt itself failed, or if the next successful deployment
    shipped a commit that reverts or hotfixes something.
    """
    ordered = sorted(deploys, key=lambda d: d.finished_at)
    flags = [not d.succeeded for d in ordered]
    successes = [i for i, d in enumerate(ordered) if d.succeeded]
    for prev, nxt in zip(successes, successes[1:], strict=False):
        if any(REMEDIATION.search(c.message) for c in ordered[nxt].commits):
            flags[prev] = True
    return flags


def restore_times(deploys: list[Deployment], flags: list[bool]) -> tuple[list[float], int]:
    """Hours from each failure to the next successful deployment, plus failures not yet restored.

    For a failed attempt the clock starts when the attempt finished. For a successful
    deployment that was later remediated, the clock starts when it finished (the earliest
    the bad change could have been live) and stops when the remediating deployment finished.
    """
    ordered = sorted(deploys, key=lambda d: d.finished_at)
    restored: list[float] = []
    unrestored = 0
    for i, failed in enumerate(flags):
        if not failed:
            continue
        fix = next((d for d in ordered[i + 1 :] if d.succeeded), None)
        if fix is None:
            unrestored += 1
        else:
            restored.append(hours(fix.finished_at - ordered[i].finished_at))
    return restored, unrestored


def compute(
    repo: str, source: str, deploys: list[Deployment], start: datetime, end: datetime
) -> RepoMetrics:
    window_days = max(1, round((end - start).total_seconds() / 86400))
    windowed = in_window(deploys, start, end)
    metrics = RepoMetrics(repo=repo, source=source, window_days=window_days)
    if not windowed:
        return metrics
    flags = failed_flags(windowed)
    restored, unrestored = restore_times(windowed, flags)
    metrics.attempts = len(windowed)
    metrics.successes = sum(1 for d in windowed if d.succeeded)
    metrics.deploys_per_week = deployment_frequency(windowed, window_days)
    metrics.lead_time_hours = lead_times(windowed)
    metrics.failures = sum(flags)
    metrics.change_failure_rate = metrics.failures / metrics.attempts
    metrics.restore_hours = restored
    metrics.unrestored_failures = unrestored
    return metrics
