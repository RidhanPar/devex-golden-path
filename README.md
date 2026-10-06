# devex-golden-path

A golden path for a small engineering organisation: one command creates a new Python service
that already has tests, linting, type checking, a container, a devcontainer, identical commands
on Windows and Linux, and safe defaults for AI coding agents.

> Work in progress. Built in phases; the full README (diagram, gates table, measured results,
> limitations) arrives in phase 6.

## Create a service

Requires Python 3.12+, git, and [uv](https://docs.astral.sh/uv/) (or `pipx install copier`).

```bash
uvx copier copy --trust gh:RidhanPar/devex-golden-path my-service
cd my-service && git init
make setup && make check          # Linux / macOS
./dev.ps1 setup; ./dev.ps1 check  # Windows PowerShell
```

## What's in the template

| Path | Purpose |
|---|---|
| `src/<package>/main.py`, `tests/` | FastAPI hello service with `/health` and `/hello`, pytest tests |
| `pyproject.toml` | ruff, mypy (strict), pytest + coverage threshold config |
| `requirements*.txt` | Pinned dependencies, visible to SCA scanners |
| `Makefile` / `dev.ps1` | Same commands on Linux and Windows: `setup lint format typecheck test check run docker-build clean` |
| `.pre-commit-config.yaml` | Fast checks before each commit, including gitleaks |
| `Dockerfile` | Multi-stage, non-root, with healthcheck |
| `.devcontainer/` | Reproducible VS Code / Codespaces environment |
| `CLAUDE.md`, `.claude/` | Conventions for AI agents; denies reading secrets; `/review` and `/write-tests`; ruff hook after edits |
| `AI_USAGE.md` | Team policy for AI coding tools |
| `.copier-answers.yml` | Lets services pull template improvements with `copier update` |
