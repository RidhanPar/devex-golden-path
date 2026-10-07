"""Prove the CI gates work by opening pull requests that deliberately break things.

For each scenario this script branches from the service's main, applies one deliberate
breakage, pushes it, opens a PR, waits for CI, and records which checks failed. A control
scenario (harmless change) proves the pipeline is not simply always red. PRs are closed
afterwards (never merged); their pages stay on GitHub as evidence.

Usage:
    python scripts/prove_gates.py RidhanPar/golden-path-demo-service
    python scripts/prove_gates.py OWNER/REPO --scenarios leaked-secret type-error

Writes results/gate-proof.json and docs/gate-proof.md. Needs git and an authenticated gh CLI.
Commits are made with --no-verify: this simulates a developer skipping the local pre-commit
hooks, so the test is of the CI gates (the server-side safety net), not of local hooks.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import string
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGGREGATE_CHECK = "CI passed"


@dataclass
class Scenario:
    name: str
    description: str
    expected_gates: list[str]  # check names expected to fail; empty = everything passes
    apply: Callable[[Path, str], None]


@dataclass
class Result:
    scenario: str
    description: str
    expected_gates: list[str]
    pr_url: str
    head_sha: str
    failed_checks: list[str] = field(default_factory=list)
    passed_checks: list[str] = field(default_factory=list)
    skipped_checks: list[str] = field(default_factory=list)
    merge_blocked: bool | None = None
    verdict: str = "pending"


# --- the deliberate breakages -------------------------------------------------------------


def control(repo: Path, pkg: str) -> None:
    with (repo / "README.md").open("a", encoding="utf-8") as f:
        f.write("\n<!-- gate proof control: harmless docs change -->\n")


def leaked_secret(repo: Path, pkg: str) -> None:
    # Random every run, so it is unique, obviously fake, and never a real credential.
    alphabet = string.ascii_letters + string.digits
    fake = "".join(secrets.choice(alphabet) for _ in range(40))
    (repo / "src" / pkg / "payment_client.py").write_text(
        f'"""Client for the payment provider."""\n\nPAYMENT_API_KEY = "{fake}"\n',
        encoding="utf-8",
    )


def vulnerable_dependency(repo: Path, pkg: str) -> None:
    # urllib3 1.24.1 has published HIGH-severity advisories with fixed versions
    # (e.g. CVE-2019-11324, CVE-2021-33503). Pure Python, so it installs fine and does not
    # break the other gates: only the dependency scanners should object.
    with (repo / "requirements.txt").open("a", encoding="utf-8") as f:
        f.write("urllib3==1.24.1\n")


def failing_test(repo: Path, pkg: str) -> None:
    main = repo / "src" / pkg / "main.py"
    text = main.read_text(encoding="utf-8")
    main.write_text(text.replace('f"Hello, {name}!"', 'f"Hi, {name}!"'), encoding="utf-8")


def type_error(repo: Path, pkg: str) -> None:
    # Classic bug: missing call parentheses. Runs fine until someone calls it; mypy catches it.
    with (repo / "src" / pkg / "main.py").open("a", encoding="utf-8") as f:
        f.write(
            "\n\ndef shout(name: str) -> str:\n"
            '    """Upper-case greeting."""\n'
            "    return hello(name).message.upper\n"
        )


def insecure_code(repo: Path, pkg: str) -> None:
    # Shell injection: user input goes into a shell command. Three statements, so the
    # coverage threshold still passes and only security-aware gates should object.
    (repo / "src" / pkg / "diagnostics.py").write_text(
        "import subprocess\n\n\n"
        "def ping(host: str) -> str:\n"
        '    return subprocess.run(f"ping -c 1 {host}", shell=True, text=True).stdout\n',
        encoding="utf-8",
    )


SCENARIOS = [
    Scenario("control", "Harmless README change", [], control),
    Scenario(
        "leaked-secret",
        "Hard-coded API key in a new module",
        ["security / secrets (gitleaks)"],
        leaked_secret,
    ),
    Scenario(
        "vulnerable-dependency",
        "Adds urllib3==1.24.1 (known HIGH CVEs)",
        ["security / sca (trivy)", "security / dependency-review"],
        vulnerable_dependency,
    ),
    Scenario(
        "insecure-code",
        "Shell injection: user input passed to subprocess with shell=True",
        ["security / sast (semgrep)"],
        insecure_code,
    ),
    Scenario(
        "failing-test",
        "Changes behaviour so an existing test fails",
        ["quality / test (ubuntu-latest)", "quality / test (windows-latest)"],
        failing_test,
    ),
    Scenario(
        "type-error",
        "Function returns a method instead of a str",
        ["quality / typecheck"],
        type_error,
    ),
]


# --- helpers ------------------------------------------------------------------------------


def run(*cmd: str, cwd: Path | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        list(cmd), cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def package_name(repo: Path) -> str:
    answers = (repo / ".copier-answers.yml").read_text(encoding="utf-8")
    match = re.search(r"^package_name:\s*(\S+)", answers, re.MULTILINE)
    if not match:
        sys.exit("could not find package_name in .copier-answers.yml")
    return match.group(1)


def open_pr(repo_dir: Path, slug: str, scenario: Scenario, stamp: str) -> Result:
    branch = f"gate-proof/{scenario.name}-{stamp}"
    run("git", "checkout", "-q", "-B", branch, "origin/main", cwd=repo_dir)
    scenario.apply(repo_dir, package_name(repo_dir))
    run("git", "add", "-A", cwd=repo_dir)
    run(
        "git", "commit", "-q", "--no-verify",
        "-m", f"gate proof: {scenario.name}",
        "-m", "Deliberate breakage to prove the CI gates; never merge.",
        cwd=repo_dir,
    )  # fmt: skip
    run("git", "push", "-q", "-u", "origin", branch, cwd=repo_dir)
    body = (
        f"**Deliberate breakage: do not merge.**\n\n{scenario.description}.\n\n"
        f"Expected to be caught by: {', '.join(scenario.expected_gates) or 'nothing (control)'}.\n"
        "Opened by `scripts/prove_gates.py` in devex-golden-path."
    )
    url = run(
        "gh", "pr", "create", "-R", slug, "--head", branch, "--base", "main",
        "--title", f"[gate proof] {scenario.name}", "--body", body,
        cwd=repo_dir,
    )  # fmt: skip
    sha = run("git", "rev-parse", "HEAD", cwd=repo_dir)
    return Result(scenario.name, scenario.description, scenario.expected_gates, url, sha)


def check_runs(slug: str, sha: str) -> list[dict[str, str]]:
    out = run(
        "gh", "api", "--paginate", f"repos/{slug}/commits/{sha}/check-runs?per_page=100",
        "--jq", ".check_runs[] | {name, status, conclusion}",
    )  # fmt: skip
    return [json.loads(line) for line in out.splitlines() if line]


def wait_for_ci(slug: str, result: Result, timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        runs = check_runs(slug, result.head_sha)
        aggregate = [r for r in runs if r["name"] == AGGREGATE_CHECK]
        if aggregate and aggregate[0]["status"] == "completed":
            for r in sorted(runs, key=lambda r: r["name"]):
                if r["name"] == AGGREGATE_CHECK:
                    continue
                bucket = {
                    "failure": result.failed_checks,
                    "success": result.passed_checks,
                }.get(r["conclusion"] or "", result.skipped_checks)
                bucket.append(r["name"])
            return
        time.sleep(20)
    result.verdict = "timeout"


def judge(result: Result) -> None:
    if result.verdict == "timeout":
        return
    expected, failed = set(result.expected_gates), set(result.failed_checks)
    if not expected:
        result.verdict = "PASS: nothing blocked" if not failed else "UNEXPECTED: control failed"
    elif expected <= failed:
        result.verdict = "CAUGHT by all expected gates"
    elif expected & failed:
        result.verdict = "CAUGHT by some expected gates"
    elif failed:
        result.verdict = "CAUGHT, but by other gates"
    else:
        result.verdict = "MISSED"


def write_reports(slug: str, results: list[Result], started: str) -> None:
    (ROOT / "results").mkdir(exist_ok=True)
    payload = {
        "repository": slug,
        "run_started_utc": started,
        "results": [asdict(r) for r in results],
    }
    (ROOT / "results" / "gate-proof.json").write_text(json.dumps(payload, indent=2) + "\n")

    lines = [
        "# Gate proof: deliberately breaking a golden-path service",
        "",
        f"Generated by `python scripts/prove_gates.py {slug}` (run started {started} UTC).",
        "Raw data: [`results/gate-proof.json`](../results/gate-proof.json).",
        "Each row is a real pull request; follow the link to see the checks on GitHub.",
        "",
        "| Breakage | PR | Checks that failed | Merge blocked | Verdict |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        failed = "<br>".join(f"`{c}`" for c in r.failed_checks) or "none"
        blocked = {True: "yes", False: "no", None: "n/a"}[r.merge_blocked]
        number = r.pr_url.rsplit("/", 1)[-1]
        lines.append(
            f"| **{r.scenario}**: {r.description} | [#{number}]({r.pr_url}) | {failed} "
            f"| {blocked} | {r.verdict} |"
        )
    lines += [
        "",
        "Merge blocked = GitHub reported the PR as not mergeable because the required check",
        f"`{AGGREGATE_CHECK}` failed (see docs/branch-protection.md).",
        "",
    ]
    (ROOT / "docs" / "gate-proof.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", help="OWNER/REPO of a service generated from the template")
    parser.add_argument("--scenarios", nargs="*", default=[s.name for s in SCENARIOS])
    parser.add_argument("--timeout", type=int, default=45 * 60, help="seconds to wait for CI")
    parser.add_argument("--keep-open", action="store_true", help="leave the PRs open")
    args = parser.parse_args()

    chosen = [s for s in SCENARIOS if s.name in args.scenarios]
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")

    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / "service"
        run("gh", "repo", "clone", args.repo, str(repo_dir), "--", "-q")
        run("git", "config", "user.name", "gate-proof", cwd=repo_dir)
        run("git", "config", "user.email", "gate-proof@users.noreply.github.com", cwd=repo_dir)

        results = []
        for scenario in chosen:
            result = open_pr(repo_dir, args.repo, scenario, stamp)
            print(f"opened {result.pr_url} ({scenario.name})", flush=True)
            results.append(result)

    for result in results:
        wait_for_ci(args.repo, result, args.timeout)
        state = run(
            "gh",
            "pr",
            "view",
            result.pr_url,
            "--json",
            "mergeStateStatus",
            "--jq",
            ".mergeStateStatus",
        )
        result.merge_blocked = state in {"BLOCKED", "DIRTY"} if state != "UNKNOWN" else None
        judge(result)
        print(f"{result.scenario:24} {result.verdict}  failed={result.failed_checks}", flush=True)
        if not args.keep_open:
            run("gh", "pr", "close", result.pr_url, "--delete-branch", "--comment",
                f"Gate proof complete: {result.verdict}. Closed without merging.")  # fmt: skip

    write_reports(args.repo, results, started)
    print("wrote results/gate-proof.json and docs/gate-proof.md")


if __name__ == "__main__":
    main()
