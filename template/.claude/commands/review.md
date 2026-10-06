---
description: Review the current changes against this service's conventions and the AI usage policy
argument-hint: "[optional: branch or commit range, default: uncommitted changes]"
allowed-tools: Bash(git diff:*), Bash(git status), Bash(git log:*), Read, Grep, Glob
---

Review the changes in this repository. Scope: $ARGUMENTS (if empty, review `git diff HEAD` plus untracked files from `git status`).

Read `CLAUDE.md` and `AI_USAGE.md` first; they are the standard you review against.

Check, in this order, and cite `file:line` for every finding:

1. **Correctness**: logic errors, unhandled edge cases, wrong HTTP status codes, missing input validation.
2. **Security**: secrets or tokens in code or tests, injection, unsafe deserialisation, `subprocess` with `shell=True`, new dependencies that are unpinned or unnecessary.
3. **Tests**: is every behaviour change covered by a test? Would the tests fail if the change were reverted?
4. **Types**: missing annotations, `Any`, or `# type: ignore` without a reason.
5. **Conventions**: anything that contradicts `CLAUDE.md`.
6. **Human review required**: flag any change that `AI_USAGE.md` says needs a human (dependencies, CI, auth, data handling, `.claude/` config).

Output a short table: severity (blocker / should-fix / nit), location, finding, suggested fix. End with a one-line verdict. Do not edit files: this command only reports.
