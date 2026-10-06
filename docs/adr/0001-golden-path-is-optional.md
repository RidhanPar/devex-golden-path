# ADR 0001: The golden path is optional, not mandatory

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

A small engineering organisation wants new services to be fast to start and safe by
default. The platform (DevEx) team can make that happen in two ways: require every service
to use its template and pipeline, or offer them as the easiest route and let teams leave it
when they have a reason.

Things we know:

- Teams with unusual needs (a Rust service, a data pipeline, a vendor SDK that needs a
  different base image) exist from day one, and a mandate turns each one into an exception
  process the platform team has to staff.
- A mandated platform has a captive audience, so it loses its feedback signal. Adoption no
  longer tells us whether the path is any good.
- Safety outcomes (no leaked secrets, no known-vulnerable dependencies, reviewed changes)
  matter regardless of how a repository was created.

## Decision

1. **The template and its reusable workflows are optional.** They are the paved road: the
   cheapest way to a production-ready service. Using them takes one command and leaves zero
   hand-written CI files. A hand-made service is measured in `docs/dx-measurements.md`.
2. **A small set of outcomes is mandatory for every repository, golden path or not:**
   changes reach `main` through a pull request with a passing required check, secrets
   scanning runs, and dependencies are scanned. Branch protection is applied by script
   (`scripts/apply_branch_protection.py`) to every repository.
3. Off-path teams can **reuse individual pieces**, for example by calling only
   `reusable-security.yml`, instead of all or nothing.
4. **Adoption is a metric we watch, not a target we enforce.** Low adoption is treated as a
   product problem with the path.

## Consequences

- The platform team has to keep the path attractive: fast CI, a short time to first green
  run, clear docs, and painless updates (`copier update`, a `v1` release branch). Phase 5
  measures exactly these things.
- Some repositories will drift from the template. Copier records each service's template
  version in `.copier-answers.yml`, so drift is visible and updates are a reviewed diff.
- Security guarantees come from the mandatory outcomes, not from the template. A team that
  leaves the path still gets the gates.

## Alternatives considered

- **Mandate the template.** Highest consistency, but it creates an exception queue and
  hides whether the path is actually good. Rejected for an organisation of this size.
- **No shared path, only guidelines.** Every team rebuilds CI, scanning and containers
  differently. This is the baseline the project exists to improve on.
