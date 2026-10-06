from typing import Any

from apply_branch_protection import GITHUB_ACTIONS_APP_ID, REQUIRED_CHECKS, build_ruleset


def rules_by_type(ruleset: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {rule["type"]: rule for rule in ruleset["rules"]}


def test_ruleset_targets_default_branch_with_no_bypass() -> None:
    ruleset = build_ruleset(approvals=1)
    assert ruleset["conditions"] == {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
    assert ruleset["bypass_actors"] == []
    assert ruleset["enforcement"] == "active"


def test_required_check_is_the_aggregate_pinned_to_github_actions() -> None:
    checks = rules_by_type(build_ruleset(approvals=1))["required_status_checks"]["parameters"]
    assert checks["required_status_checks"] == [
        {"context": "CI passed", "integration_id": GITHUB_ACTIONS_APP_ID}
    ]
    assert checks["strict_required_status_checks_policy"] is True
    assert REQUIRED_CHECKS == ["CI passed"]


def test_force_push_and_deletion_blocked() -> None:
    rules = rules_by_type(build_ruleset(approvals=1))
    assert {"deletion", "non_fast_forward"} <= rules.keys()


def test_last_push_approval_only_required_when_approvals_required() -> None:
    team = rules_by_type(build_ruleset(approvals=1))["pull_request"]["parameters"]
    solo = rules_by_type(build_ruleset(approvals=0))["pull_request"]["parameters"]
    assert team["required_approving_review_count"] == 1
    assert team["require_last_push_approval"] is True
    assert solo["required_approving_review_count"] == 0
    assert solo["require_last_push_approval"] is False
