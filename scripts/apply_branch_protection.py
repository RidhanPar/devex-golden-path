"""Apply the golden-path branch protection ruleset and security settings to a repository.

Usage:
    python scripts/apply_branch_protection.py OWNER/REPO [--approvals N] [--dry-run]

Idempotent: enables Dependabot vulnerability alerts (which turns on the dependency graph that
the dependency-review gate needs), then creates the "golden-path-main" ruleset, or updates it
if it already exists.
Needs the GitHub CLI (`gh`) authenticated as a repository admin. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

RULESET_NAME = "golden-path-main"
GITHUB_ACTIONS_APP_ID = 15368  # only check runs from GitHub Actions can satisfy the check

# The one required check. It is the aggregate job in the service's ci.yml that fails unless
# lint, typecheck, tests (Linux + Windows), SAST, SCA, dependency review, secrets scan and the
# container build/scan/smoke test all passed. See docs/branch-protection.md.
REQUIRED_CHECKS = ["CI passed"]


def build_ruleset(approvals: int) -> dict[str, object]:
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": [],  # nobody bypasses, admins included
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": approvals,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": approvals > 0,
                    "required_review_thread_resolution": True,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,  # branch must be up to date
                    "required_status_checks": [
                        {"context": name, "integration_id": GITHUB_ACTIONS_APP_ID}
                        for name in REQUIRED_CHECKS
                    ],
                },
            },
        ],
    }


def gh(*args: str, payload: dict[str, object] | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["gh", "api", *args, *(["--input", "-"] if payload is not None else [])],  # noqa: S607
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.exit(f"gh api {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", help="OWNER/REPO")
    parser.add_argument(
        "--approvals",
        type=int,
        default=1,
        help="required PR approvals (default 1; use 0 for a single-maintainer repo)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the ruleset and exit")
    args = parser.parse_args()

    ruleset = build_ruleset(args.approvals)
    if args.dry_run:
        print(json.dumps(ruleset, indent=2))
        return

    # Without the dependency graph, the dependency-review gate fails on every PR.
    gh("-X", "PUT", f"repos/{args.repo}/vulnerability-alerts")
    print(f"Enabled Dependabot alerts and the dependency graph on {args.repo}")

    existing = json.loads(gh(f"repos/{args.repo}/rulesets"))
    match = next((r for r in existing if r["name"] == RULESET_NAME), None)
    if match:
        gh("-X", "PUT", f"repos/{args.repo}/rulesets/{match['id']}", payload=ruleset)
        print(f"Updated ruleset {RULESET_NAME!r} (id {match['id']}) on {args.repo}")
    else:
        created = json.loads(gh("-X", "POST", f"repos/{args.repo}/rulesets", payload=ruleset))
        print(f"Created ruleset {RULESET_NAME!r} (id {created['id']}) on {args.repo}")


if __name__ == "__main__":
    main()
