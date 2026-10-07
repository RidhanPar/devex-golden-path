# ADR 0002: Which security gates, and how CI stays fast

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Every service needs protection against the most common ways small teams ship security
problems: leaked credentials, known-vulnerable dependencies, insecure code patterns and
vulnerable container images. Each gate adds CI time, and developers route around slow CI by
batching changes, skipping hooks or merging without waiting. That costs more safety than
the gate adds.

## Decision

### The gates

| Gate | Tool | Why this tool |
|---|---|---|
| Secrets | gitleaks (CI over the PR's commits; also in pre-commit) | Fast, open source, scans git history rather than just files, runs locally too |
| SAST | Semgrep (`p/python`, `p/dockerfile`) | Seconds per run, readable rules, works on private repos without GitHub Advanced Security. CodeQL finds deeper data-flow bugs but takes minutes and needs GHAS on private repos; it's the upgrade path |
| SCA | Trivy filesystem scan of pinned `requirements.txt` | Pinned versions make the scan exact; fails on fixable HIGH/CRITICAL |
| New vulnerable deps in a PR | GitHub dependency review | Shows the PR author exactly what their change introduced |
| Container image | Trivy image scan + smoke test | Catches OS packages and anything installed in the image, not just the app's deps |

All gates **block** (non-zero exit), at threshold *HIGH, fixed version available*. Blocking
on unfixable findings would fail builds nobody can fix, which trains people to ignore the
gate.

Every gate was proven by a pull request that deliberately broke it (`docs/gate-proof.md`).
The first real run also proved the image gate useful: it found 4 HIGH CVEs in libraries
vendored inside the base image's `pip`. The fix was to remove pip from the runtime image,
not to suppress the findings.

### Supply chain of the pipeline itself

- Third-party actions are pinned to **commit SHAs**, and the Trivy and gitleaks containers to
  **digests**. A tag can be re-pointed by whoever controls it; a SHA can't.
- Semgrep is the deliberate exception: it is installed from its **pinned PyPI version** with
  dependencies frozen to a resolution date, because pulling its container image took 19 of
  the job's ~22 seconds (v1.2.0, measured in `docs/dx-measurements.md`). That's slightly weaker
  pinning (a version plus PyPI's immutable release files, not a digest) in exchange for
  the job dropping from 35 s to 19 s.
- Deploys use **OIDC** (short-lived tokens). No long-lived cloud keys are stored anywhere.
- One required check (`CI passed`) aggregates every gate, so adding a gate never needs a
  branch-protection change in every repository.

### Keeping CI fast

1. **Parallel jobs.** Lint, typecheck, tests (Linux and Windows), each scanner and the
   container build all run at the same time. Wall-clock time is the slowest job, not the sum.
2. **Caching:** the virtualenv (keyed on OS, exact Python version and the dependency files),
   Docker layers (GitHub Actions cache), and the Trivy vulnerability DB (daily key). Caching
   can be switched off per run (`enable-cache`), and `scripts/measure_dx.py cache` measures
   the difference: see `docs/dx-measurements.md`.
3. **Fast checks shift left.** ruff, formatting and gitleaks run in pre-commit (seconds);
   mypy and tests run in `make check` and CI.
4. **Scope by event.** Dependency review runs only on PRs; gitleaks scans only the PR's
   commits on PRs.
5. **Cancel superseded PR runs** (`concurrency` with `cancel-in-progress` on PRs only; never on
   `main`, never on deploys).

## Consequences

- Five scanners means five tools to keep updated. Dependabot (or Renovate) for SHA-pinned
  actions and image digests is the natural next step and is not yet set up.
- Semgrep's registry rules change over time, so a rule update can fail a previously green
  build. Pinning the Semgrep version limits this; the rule packs themselves aren't pinned.
- Suppressions are allowed but must be inline, scoped to one rule, and justified (see
  `.claude/hooks/lint_after_edit.py`) so they show up in review.

## Alternatives considered

- **CodeQL instead of Semgrep:** deeper analysis, slower, and needs GHAS on private repos.
  Kept as an upgrade path for services that handle sensitive data.
- **Warn-only gates:** no friction, but warnings in CI logs are not read. Rejected.
- **Nightly scans instead of per-PR:** cheaper, but finds problems after merge, when the
  author has moved on. Rejected for code gates. A scheduled image rescan is still worth
  adding, for new CVEs in unchanged images.
