"""Measure developer experience on the golden path versus a hand-made service. Real runs only.

Two experiments, each writing results/dx-<experiment>.json and appending to docs/dx-measurements.md:

1. time-to-green: from a cold start to the first green CI run of a brand-new service repository.
     golden    t0 -> `copier copy` the published template -> git init/commit -> create the
               GitHub repo and push -> first CI run on main completes successfully.
     handmade  t0 -> copy measure/handmade-baseline (a typical hand-written FastAPI service
               with a basic CI workflow) -> git init/commit -> create repo and push -> first
               CI run completes successfully.
   Machine time is measured. Human authoring time cannot be measured by a script, so instead
   the script counts what a human must write by hand on each path (files and lines).

2. cache: CI duration with and without caching on one service repository, by dispatching the
   service's CI workflow with enable-cache=false / true alternately (after one warm-up run).

Usage:
    python scripts/measure_dx.py time-to-green --owner RidhanPar --runs 1
    python scripts/measure_dx.py cache --repo RidhanPar/golden-path-demo-service --runs 3

Creates public repositories named dx-measure-<kind>-<timestamp> for experiment 1; they are
left in place as evidence (delete them with `gh repo delete` when done).
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "measure" / "handmade-baseline"
TEMPLATE = "gh:RidhanPar/devex-golden-path"
COPIER = ["uvx", "copier@9.18.2"]


def run(*cmd: str, cwd: Path | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        list(cmd), cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def gh_json(*args: str) -> Any:
    return json.loads(run("gh", "api", *args))


def wait_for_run(
    repo: str, *, event: str, after: datetime, timeout_s: int = 3600
) -> dict[str, Any]:
    """The first workflow run of `event` created after `after`, once it has completed."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        runs = gh_json(f"repos/{repo}/actions/runs?event={event}&per_page=20")["workflow_runs"]
        mine = [r for r in runs if parse_time(r["created_at"]) >= after.replace(microsecond=0)]
        if mine:
            first = min(mine, key=lambda r: r["created_at"])
            if first["status"] == "completed":
                return dict(first)
        time.sleep(15)
    sys.exit(f"timed out waiting for a {event} run on {repo}")


def job_seconds(repo: str, run_id: int) -> dict[str, float]:
    jobs = gh_json(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]
    out: dict[str, float] = {}
    for j in jobs:
        if j.get("started_at") and j.get("completed_at") and j["conclusion"] != "skipped":
            out[j["name"]] = int(
                (parse_time(j["completed_at"]) - parse_time(j["started_at"])).total_seconds()
            )
    return out


def hand_written(path: Path) -> dict[str, int]:
    """Files and non-blank lines a human authored."""
    files = [p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts]
    lines = sum(
        1 for p in files for line in p.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    return {"files": len(files), "lines": lines}


def gates_in(workflow_text: str) -> list[str]:
    known = {
        "lint": ["ruff check", "reusable-python-ci"],
        "typecheck": ["mypy", "reusable-python-ci"],
        "tests": ["pytest", "reusable-python-ci"],
        "windows tests": ["windows-latest", "reusable-python-ci"],
        "SAST": ["semgrep", "codeql", "reusable-security"],
        "dependency scan": ["trivy", "dependency-review", "reusable-security"],
        "secret scan": ["gitleaks", "reusable-security"],
        "container build + scan": ["docker", "reusable-docker"],
        "deploy (OIDC)": ["id-token", "reusable-deploy"],
    }
    return [gate for gate, needles in known.items() if any(n in workflow_text for n in needles)]


def time_to_green(owner: str, kind: str) -> dict[str, Any]:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    name = f"dx-measure-{kind}-{stamp}"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / name
        t0 = datetime.now(UTC)
        start = time.monotonic()
        if kind == "golden":
            run(
                *COPIER,
                "copy",
                "--trust",
                "--defaults",
                "-d",
                f"project_name={name}",
                TEMPLATE,
                str(work),
            )
            authored = {"files": 0, "lines": 0}  # one command, answers defaulted
        else:
            shutil.copytree(BASELINE, work)
            authored = hand_written(work)
        workflow = (work / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        run("git", "init", "-q", "-b", "main", cwd=work)
        run("git", "add", "-A", cwd=work)
        run(
            "git",
            "-c",
            "user.name=dx-measure",
            "-c",
            "user.email=dx@users.noreply.github.com",
            "commit",
            "-q",
            "--no-verify",
            "-m",
            "initial service",
            cwd=work,
        )
        run(
            "gh",
            "repo",
            "create",
            f"{owner}/{name}",
            "--public",
            "--source",
            str(work),
            "--push",
            "--description",
            f"DX measurement ({kind}); created by measure_dx.py",
        )
        local_s = time.monotonic() - start

    ci = wait_for_run(f"{owner}/{name}", event="push", after=t0)
    green = ci["conclusion"] == "success"
    finished = parse_time(ci["updated_at"])
    return {
        "kind": kind,
        "repo": f"{owner}/{name}",
        "run_url": ci["html_url"],
        "first_run_conclusion": ci["conclusion"],
        "local_setup_seconds": round(local_s, 1),
        "ci_wall_seconds": (finished - parse_time(ci["run_started_at"])).seconds,
        "start_to_first_ci_result_seconds": round((finished - t0).total_seconds(), 1),
        "green": green,
        "hand_written": authored,
        "gates": gates_in(workflow),
        "jobs_seconds": job_seconds(f"{owner}/{name}", ci["id"]),
    }


def cache_experiment(repo: str, runs: int, workflow: str) -> dict[str, Any]:
    def dispatch(enable: bool) -> dict[str, Any]:
        t0 = datetime.now(UTC)
        run(
            "gh",
            "workflow",
            "run",
            workflow,
            "-R",
            repo,
            "--ref",
            "main",
            "-f",
            f"enable-cache={'true' if enable else 'false'}",
        )
        ci = wait_for_run(repo, event="workflow_dispatch", after=t0)
        jobs = job_seconds(repo, ci["id"])
        sample = {
            "enable_cache": enable,
            "run_url": ci["html_url"],
            "conclusion": ci["conclusion"],
            "wall_seconds": int(
                (parse_time(ci["updated_at"]) - parse_time(ci["run_started_at"])).total_seconds()
            ),
            "job_seconds_total": sum(jobs.values()),
            "jobs_seconds": jobs,
        }
        print(
            f"  cache={enable!s:5} wall={sample['wall_seconds']}s "
            f"jobs={sample['job_seconds_total']}s {sample['conclusion']}",
            flush=True,
        )
        return sample

    print("warm-up (cache on, populates caches)", flush=True)
    warmup = dispatch(True)
    samples = []
    for _ in range(runs):
        samples.append(dispatch(False))
        samples.append(dispatch(True))

    def med(enable: bool, key: str) -> float:
        values = [
            s[key] for s in samples if s["enable_cache"] is enable and s["conclusion"] == "success"
        ]
        return float(statistics.median(values)) if values else float("nan")

    summary = {
        f"median_{key}_{label}": med(enable, key)
        for key in ("wall_seconds", "job_seconds_total")
        for enable, label in ((False, "uncached"), (True, "cached"))
    }
    return {"repo": repo, "runs_per_arm": runs, "warmup": warmup, "samples": samples, **summary}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="experiment", required=True)
    ttg = sub.add_parser("time-to-green")
    ttg.add_argument("--owner", required=True)
    ttg.add_argument("--runs", type=int, default=1, help="repetitions per kind")
    cache = sub.add_parser("cache")
    cache.add_argument("--repo", required=True)
    cache.add_argument("--runs", type=int, default=3, help="uncached+cached pairs")
    cache.add_argument("--workflow", default="ci.yml")
    args = parser.parse_args()

    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.experiment == "time-to-green":
        results = [
            time_to_green(args.owner, k) for _ in range(args.runs) for k in ("golden", "handmade")
        ]
        for r in results:
            print(
                json.dumps(
                    {
                        k: r[k]
                        for k in (
                            "kind",
                            "green",
                            "local_setup_seconds",
                            "ci_wall_seconds",
                            "start_to_first_ci_result_seconds",
                        )
                    }
                )
            )
        payload: dict[str, Any] = {
            "experiment": "time-to-green",
            "started": started,
            "results": results,
        }
    else:
        payload = {
            "experiment": "cache",
            "started": started,
            **cache_experiment(args.repo, args.runs, args.workflow),
        }
    out = ROOT / "results" / f"dx-{args.experiment}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
