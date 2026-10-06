# ADR 0003: How to roll out AI coding tools safely

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

Engineers already use AI coding assistants and agents (Claude Code, Copilot, Cursor, chat
tools), with or without a policy. The benefits are real, and so are the risks:

- **Secrets and data leakage:** an agent that can read `.env` can paste its contents into a
  prompt, a log or a commit.
- **Unreviewed change volume:** agents produce plausible code fast, which can outpace review.
- **Test erosion:** an agent told "make CI green" may weaken or delete a test.
- **Supply chain:** assistants suggest packages that don't exist or aren't what they seem
  ("slopsquatting"). While building this repository, a warning told us to install `httpx2`.
  We verified its publisher and that Starlette itself depends on it before adding it.
- **Over-reach:** an agent with shell access can push, publish, or change CI and its own
  permissions.

## Decision

Roll AI tools out **through the golden path**, so the safe setup is the default in every new
service rather than something each team configures:

1. **Policy for humans:** `AI_USAGE.md` in every service. It says what agents may do, what
   always needs human review (dependencies, CI, auth, data handling, the agent's own config),
   the testing rules, and the data and secrets rules. Core principle: *the human who merges a
   change owns it.*
2. **Guardrails enforced by tooling, not just policy:** `.claude/settings.json` denies
   reading `.env*`, `secrets/`, keys and certificates. It denies `git push` and requires
   approval for commits, dependency edits, and changes to `.github/` or `.claude/`.
3. **Fast feedback loops for the agent:** a hook runs ruff after every AI edit and returns
   unfixable findings to the agent, so problems are fixed in the same step rather than in
   review. `CLAUDE.md` gives conventions and the exact `check` command that defines "done".
4. **Reusable, reviewable workflows:** `/review` reviews a change against `CLAUDE.md` and
   `AI_USAGE.md`, and `/write-tests` writes tests under the testing rules. Both are prompts in
   the repository, versioned and reviewed like code.
5. **The same gates for AI-written code.** CI does not care who wrote the code. Every gate in
   ADR 0002 applies, and branch protection requires a passing check and a PR.
6. **Staged rollout:** a pilot team first, then measurement, then the wider organisation.
   Measure with the DORA tool (`python -m dora`): lead time and change failure rate before and
   after. Mark AI-assisted commits with a `Co-Authored-By:` trailer so their effect can be
   measured.

## Consequences

- Client-side deny rules are **defence in depth, not a guarantee**. A determined process can
  still read files through other means. That is why secrets belong in a secrets manager,
  and why gitleaks runs in pre-commit and in CI.
- Guardrails only cover tools that read them (`.claude/`). Other tools are governed by
  `AI_USAGE.md` and code review until they get equivalent config.
- Review load may rise. If lead time rises while change failure rate stays flat, the
  bottleneck is review, and the fix is smaller PRs, not fewer checks.

## Alternatives considered

- **Ban AI tools:** unenforceable, and it pushes usage onto personal accounts with no
  guardrails at all. Rejected.
- **Allow freely, with no policy or config:** the risks above land in production. Rejected.
- **Central gateway or proxy for all AI traffic:** strong control and audit, but heavy for a
  small organisation. Worth revisiting if data-handling requirements grow.
