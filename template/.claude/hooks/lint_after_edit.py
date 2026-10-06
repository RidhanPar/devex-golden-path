"""Claude Code PostToolUse hook: lint and format a Python file right after an AI edit.

Reads the hook payload (JSON) from stdin, runs ruff on the edited file, and
- exits 0 when the file is clean (fixes and formatting are applied silently);
- exits 2 with the remaining ruff findings on stderr, which Claude Code feeds
  back to the agent so it fixes them in its next step.

Standard library only, so it runs on Windows and Linux without extra installs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_ruff(project_dir: Path) -> str | None:
    for candidate in (
        project_dir / ".venv" / "Scripts" / "ruff.exe",
        project_dir / ".venv" / "bin" / "ruff",
    ):
        if candidate.exists():
            return str(candidate)
    return shutil.which("ruff")


def run_ruff(ruff: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    # Safe by construction: argv list (no shell), the executable is the project's own ruff,
    # and the only external value is the edited file's path, passed as a single argument.
    # nosemgrep: dangerous-subprocess-use-tainted-env-args
    return subprocess.run(  # noqa: S603
        [ruff, *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # not our business: never block the agent on a malformed payload

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    if not file_path.endswith(".py"):
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
    ruff = find_ruff(project_dir)
    if ruff is None:
        print("lint hook: ruff not found; run `make setup` or `./dev.ps1 setup`", file=sys.stderr)
        return 0

    # Fix first, then format, so the formatter tidies up after removed imports.
    result = run_ruff(ruff, ["check", "--fix", "--quiet", file_path], project_dir)
    run_ruff(ruff, ["format", "--quiet", file_path], project_dir)
    if result.returncode != 0:
        print(f"ruff found issues in {file_path} that need a manual fix:", file=sys.stderr)
        print(result.stdout or result.stderr, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
