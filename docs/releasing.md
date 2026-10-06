# Releasing the golden path

Services consume the golden path in two ways, so each release produces two refs:

| Ref | Kind | Used by | Moves? |
|---|---|---|---|
| `v1` | **branch** | the service's `ci.yml`: `uses: RidhanPar/devex-golden-path/.github/workflows/<x>.yml@v1` | Forward only (fast-forward), protected by the `release-branch-v1` ruleset: no force-push, no deletion |
| `v1.2.3` | **tag** | Copier: `copier update --trust --vcs-ref v1.2.3`; recorded in each service's `.copier-answers.yml` | Never. Released versions are immutable |

```bash
python scripts/release.py 1.2.0 --dry-run   # checks only
python scripts/release.py 1.2.0
```

The script refuses unless `main`'s HEAD has a green `template-ci` run, which generates a
fresh service and runs its full pipeline on Linux and Windows. Then it tags `v1.2.0` and
fast-forwards `v1`.

## What reaches services, and when

- **Workflow changes** (new gate, bug fix in a shared job) reach every service on its next CI run
  as soon as `v1` moves. No service-side change is needed.
- **Template file changes** (Dockerfile, hook, pyproject) reach a service when it runs
  `copier update`. That produces a normal diff, reviewed in a normal PR. Copier merges the
  template change with the service's own edits and leaves conflict markers where they clash.
- **Breaking changes** (a gate that would fail existing services, a renamed input) go to a new
  `v2` branch. Services move when they're ready. `v1` keeps getting fixes for a while.

## Why `v1` is a branch, not a tag (a lesson from building this)

The first version used a floating `v1` **tag**, the convention many GitHub Actions use. Two
problems showed up:

1. **Copier reads every tag as a version.** `v1` parses as version `1`, so with both `v1` and
   `v1.1.1` present, Copier saw updating to `v1.1.1` as a *downgrade to 1* and refused.
2. **Moving a tag means force-pushing a published ref.** That's a destructive operation that
   tag-protection rules, and careful automation, rightly block. It also means the content
   behind `@v1` can change silently, with no history of what was there before.

A `v1` branch fixes both: Copier ignores branches, workflow `uses:` resolves branches exactly
like tags, and a fast-forward-only branch keeps an auditable history of every release.

## Release history

| Version | Commit | Change |
|---|---|---|
| v1.0.0 | `40120c3` | Phase 2: first release of the template and reusable workflows |
| v1.1.0 | `b4857ee` | Runtime image without pip (4 HIGH CVEs found by the first real run); lint-hook subprocess fix; template CI |
| v1.1.1 | `708f909` | Deploy job declares its own token permissions (the deploy failed on its first run with `contents: read` only) |
