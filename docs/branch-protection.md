# Branch protection for golden-path services

Every service's default branch is protected by one repository **ruleset**, applied by a script
rather than by clicking through settings, so that it is reviewable, repeatable and identical
across repositories:

```bash
python scripts/apply_branch_protection.py OWNER/REPO               # team repo: 1 approval
python scripts/apply_branch_protection.py OWNER/REPO --approvals 0 # single-maintainer repo
python scripts/apply_branch_protection.py OWNER/REPO --dry-run     # print the JSON only
```

The script also enables Dependabot vulnerability alerts, which turns on the repository's
dependency graph. Without it the `dependency-review` gate fails on every pull request: the
first gate-proof run found exactly that, when even the harmless control PR was blocked.

## The rules

| Rule | Setting | Why |
|---|---|---|
| Changes go through a pull request | required | Every change gets CI and a reviewer before `main`. |
| Required approvals | 1 (0 for solo repos) | A second person owns the change. See `AI_USAGE.md`: AI-written code is reviewed like any other. |
| Dismiss stale approvals on push | on | An approval covers the code that was reviewed, not code added afterwards. |
| Require approval of the last push | on when approvals > 0 | Stops "get approval, then push something else". |
| Conversations resolved | required | Review comments can't be silently ignored. |
| Required status check | **`CI passed`**, from GitHub Actions only | See below. |
| Branch must be up to date | on | Checks ran against the code as it will be after merge. |
| Force push / deletion | blocked | History on `main` is immutable; DORA metrics depend on it. |
| Bypass list | empty | Admins follow the same rules. Emergency fixes go through the same PR flow. |

## Why one required check instead of ten

`CI passed` is the aggregate job at the end of every service's `ci.yml`. It fails unless all
of these succeeded (a job that is skipped by design, such as dependency review on a push,
counts as OK):

| Check (as shown on the PR) | Gate |
|---|---|
| `quality / lint` | ruff lint + format |
| `quality / typecheck` | mypy `--strict` |
| `quality / test (ubuntu-latest)`, `quality / test (windows-latest)` | pytest + coverage threshold |
| `security / sast (semgrep)` | static analysis |
| `security / sca (trivy)` | known-vulnerable dependencies |
| `security / dependency-review` | vulnerable dependencies introduced by this PR |
| `security / secrets (gitleaks)` | committed credentials |
| `container / build + image scan + smoke test` | image builds, has no fixable HIGH/CRITICAL CVEs, starts and answers `/health` |

Required checks are matched **by name**. If each repository listed all ten, every rename or new
gate in the shared workflows would need a branch-protection change in every repository. Worse,
a check listed in protection but no longer produced blocks merges forever, and a gate that is
added but not listed is silently optional. Requiring a single stable aggregate avoids all
three problems.

The check is pinned to the GitHub Actions app (`integration_id: 15368`), so a commit status
posted through the API by anything else with the name `CI passed` cannot satisfy it.

## Limits

- Rulesets on private repositories need a paid GitHub plan; on public repositories they are free.
- Branch protection proves a check passed, not that the check is any good. That is what the
  deliberate-breakage tests in phase 3 are for.
