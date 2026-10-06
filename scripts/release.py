"""Release the golden path: tag an immutable version and fast-forward the v1 release branch.

Usage:
    python scripts/release.py 1.2.0            # release main's HEAD as v1.2.0
    python scripts/release.py 1.2.0 --dry-run

Refuses unless main's HEAD has a successful template-ci run. See docs/releasing.md.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

REPO = "RidhanPar/devex-golden-path"
RELEASE_BRANCH = "v1"


def run(*cmd: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        list(cmd), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="MAJOR.MINOR.PATCH, e.g. 1.2.0")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not re.fullmatch(r"1\.\d+\.\d+", args.version):
        sys.exit("version must be 1.x.y (a 2.x needs a new v2 release branch: a breaking change)")
    tag = f"v{args.version}"

    run("git", "fetch", "-q", "origin", "--tags")
    sha = run("git", "rev-parse", "origin/main")
    runs = json.loads(
        run(
            "gh",
            "run",
            "list",
            "-R",
            REPO,
            "-w",
            "template-ci.yml",
            "-c",
            sha,
            "--json",
            "conclusion,url",
        )  # fmt: skip
    )
    green = [r for r in runs if r["conclusion"] == "success"]
    if not green:
        sys.exit(f"refusing: no successful template-ci run for origin/main ({sha[:7]})")
    if run("git", "tag", "--list", tag):
        sys.exit(f"refusing: {tag} already exists (released versions are immutable)")

    print(f"releasing {sha[:7]} as {tag}; template-ci: {green[0]['url']}")
    if args.dry_run:
        return
    run("git", "tag", "-a", tag, sha, "-m", f"devex-golden-path {tag}")
    run("git", "push", "-q", "origin", tag)
    # A plain push: the v1 ruleset rejects anything that is not a fast-forward.
    run("git", "push", "-q", "origin", f"{sha}:refs/heads/{RELEASE_BRANCH}")
    print(f"done: services on @{RELEASE_BRANCH} pick up {tag} on their next CI run;")
    print(f"      template changes reach them via `copier update --trust --vcs-ref {tag}`")


if __name__ == "__main__":
    main()
