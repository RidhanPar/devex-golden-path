from datetime import UTC, datetime, timedelta

import pytest

from dora.metrics import Commit, Deployment, compute, failed_flags, lead_times, restore_times

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def commit(sha: str, hours: float, message: str = "feat: change") -> Commit:
    return Commit(sha, at(hours), message)


def deploy(hours: float, ok: bool = True, commits: tuple[Commit, ...] = ()) -> Deployment:
    return Deployment(
        "o/r", f"sha{hours}", "production", at(hours), at(hours), ok, "deployments", commits
    )


def test_lead_time_measured_per_commit_from_commit_to_deploy() -> None:
    d = deploy(10, commits=(commit("a", 4), commit("b", 8)))
    assert lead_times([d]) == [6.0, 2.0]


def test_failed_deploys_contribute_no_lead_time() -> None:
    assert lead_times([deploy(10, ok=False, commits=(commit("a", 4),))]) == []


def test_failed_attempt_counts_as_change_failure() -> None:
    assert failed_flags([deploy(1), deploy(2, ok=False), deploy(3)]) == [False, True, False]


def test_successful_deploy_later_reverted_counts_as_failure() -> None:
    deploys = [
        deploy(1, commits=(commit("a", 0),)),
        deploy(5, commits=(commit("b", 4, 'Revert "feat: change"'),)),
    ]
    assert failed_flags(deploys) == [True, False]


@pytest.mark.parametrize("message", ["fix: hotfix for login", "chore: rollback config"])
def test_hotfix_and_rollback_messages_mark_previous_deploy(message: str) -> None:
    deploys = [deploy(1), deploy(2, commits=(commit("b", 1.5, message),))]
    assert failed_flags(deploys) == [True, False]


def test_restore_time_is_until_next_successful_deploy() -> None:
    deploys = [deploy(1), deploy(2, ok=False), deploy(3, ok=False), deploy(7)]
    flags = failed_flags(deploys)
    assert restore_times(deploys, flags) == ([5.0, 4.0], 0)


def test_failure_without_later_success_is_unrestored() -> None:
    deploys = [deploy(1), deploy(2, ok=False)]
    assert restore_times(deploys, failed_flags(deploys)) == ([], 1)


def test_compute_over_window() -> None:
    deploys = [
        deploy(-100),  # before the window: ignored
        deploy(1, commits=(commit("a", 0),)),
        deploy(2, ok=False),
        deploy(4, commits=(commit("b", 3),)),
    ]
    m = compute("o/r", "deployments", deploys, T0, T0 + timedelta(days=14))
    assert (m.attempts, m.successes, m.failures) == (3, 2, 1)
    assert m.deploys_per_week == pytest.approx(1.0)
    assert m.change_failure_rate == pytest.approx(1 / 3)
    assert m.median_lead_time_hours == pytest.approx(1.0)
    assert m.median_restore_hours == pytest.approx(2.0)


def test_compute_with_no_deploys_reports_nothing_rather_than_zero_rates() -> None:
    m = compute("o/r", "none", [], T0, T0 + timedelta(days=90))
    assert m.attempts == 0
    assert m.change_failure_rate is None
    assert m.median_lead_time_hours is None


@pytest.mark.parametrize(
    ("value", "text"),
    [(None, "n/a"), (12 / 3600, "12 s"), (0.5, "30 min"), (5.25, "5.2 h"), (72, "3.0 days")],
)
def test_fmt_hours(value: float | None, text: str) -> None:
    from dora.report import fmt_hours

    assert fmt_hours(value) == text
