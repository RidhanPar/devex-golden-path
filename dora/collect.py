"""Turn GitHub API data into Deployment records (with the commits each one shipped).

Deployment source, per repository, in order of preference:
1. GitHub Deployments to a production-like environment (from Actions environments, Vercel,
   GitHub Pages, ...), with their status history.
2. Published GitHub Releases (not drafts or pre-releases), each treated as a successful deploy.
3. None: the repository is reported as having no deployment data. We deliberately do NOT
   fall back to "every push to main is a deploy", because that would invent deployments.

Supplementary signals (not DORA metrics, shown separately): merged pull requests and
default-branch CI runs.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dora.github import GitHub
from dora.metrics import Commit, Deployment

# Production-like environment names: "production"/"prod" (Actions, Vercel), "github-pages",
# and "main - <service>" (Railway names environments after the branch they deploy from).
# Preview/staging environments are excluded.
DEFAULT_ENV_PATTERN = r"(?i)^(prod|production|github-pages)$|^main - "


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class Supplementary:
    merged_prs: int = 0
    median_pr_cycle_hours: float | None = None
    ci_runs: int = 0
    ci_failure_rate: float | None = None
    median_ci_recovery_hours: float | None = None


def list_repos(gh: GitHub, owner: str) -> list[dict[str, Any]]:
    repos = gh.paginate(f"users/{owner}/repos?type=owner&sort=pushed")
    return [r for r in repos if not r["fork"] and not r["private"] and not r["archived"]]


def _deployment_from_api(gh: GitHub, repo: str, raw: dict[str, Any]) -> Deployment | None:
    statuses = gh.paginate(f"repos/{repo}/deployments/{raw['id']}/statuses", limit=100)
    states: dict[str, datetime] = {}
    for status in reversed(statuses):  # API returns newest first; keep each state's first time
        states.setdefault(status["state"], parse_time(status["created_at"]))
    if "success" in states:
        succeeded, finished = True, states["success"]
    elif "failure" in states or "error" in states:
        succeeded = False
        finished = min(t for k, t in states.items() if k in ("failure", "error"))
    else:
        return None  # queued / in progress / never reported: not a completed attempt
    return Deployment(
        repo=repo,
        sha=raw["sha"],
        environment=raw["environment"],
        created_at=parse_time(raw["created_at"]),
        finished_at=finished,
        succeeded=succeeded,
        source="deployments",
    )


def _deployments(gh: GitHub, repo: str, env_pattern: str) -> list[Deployment]:
    pattern = re.compile(env_pattern)
    raw = [d for d in gh.paginate(f"repos/{repo}/deployments") if pattern.search(d["environment"])]
    deploys = [d for r in raw if (d := _deployment_from_api(gh, repo, r)) is not None]
    return sorted(deploys, key=lambda d: d.finished_at)


def _releases(gh: GitHub, repo: str) -> list[Deployment]:
    deploys = []
    for rel in gh.paginate(f"repos/{repo}/releases"):
        if rel["draft"] or rel["prerelease"] or not rel.get("published_at"):
            continue
        commit = gh.get(f"repos/{repo}/commits/{rel['tag_name']}")
        if not commit:
            continue
        published = parse_time(rel["published_at"])
        deploys.append(
            Deployment(repo, commit["sha"], "release", published, published, True, "releases")
        )
    return sorted(deploys, key=lambda d: d.finished_at)


def _commit(raw: dict[str, Any]) -> Commit:
    return Commit(
        sha=raw["sha"],
        committed_at=parse_time(raw["commit"]["committer"]["date"]),
        message=raw["commit"]["message"],
    )


def attach_commits(gh: GitHub, repo: str, deploys: list[Deployment]) -> list[Deployment]:
    """Give each successful deployment the commits it shipped for the first time.

    Commits between the previous successful deployment's sha and this one (compare API).
    For the first known deployment only its own head commit is counted, since we cannot
    know which earlier commits it shipped.
    """
    out: list[Deployment] = []
    previous_sha: str | None = None
    for d in deploys:
        commits: tuple[Commit, ...] = ()
        if d.succeeded:
            if previous_sha is None:
                head = gh.get(f"repos/{repo}/commits/{d.sha}")
                commits = (_commit(head),) if head else ()
            elif previous_sha != d.sha:
                cmp = gh.get(f"repos/{repo}/compare/{previous_sha}...{d.sha}")
                # status "diverged"/"behind" (e.g. a rollback to an older sha) ships nothing new
                if cmp and cmp["status"] in ("ahead", "identical"):
                    commits = tuple(_commit(c) for c in cmp["commits"])
            previous_sha = d.sha
        out.append(
            Deployment(
                d.repo,
                d.sha,
                d.environment,
                d.created_at,
                d.finished_at,
                d.succeeded,
                d.source,
                commits,
            )  # fmt: skip
        )
    return out


def collect_deployments(gh: GitHub, repo: str, env_pattern: str) -> tuple[str, list[Deployment]]:
    deploys = _deployments(gh, repo, env_pattern)
    source = "deployments"
    if not deploys:
        deploys, source = _releases(gh, repo), "releases"
    if not deploys:
        return "none", []
    return source, attach_commits(gh, repo, deploys)


def collect_supplementary(
    gh: GitHub, repo: str, default_branch: str, start: datetime, end: datetime
) -> Supplementary:
    sup = Supplementary()
    prs = gh.paginate(f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc", limit=300)
    cycle = [
        (parse_time(p["merged_at"]) - parse_time(p["created_at"])).total_seconds() / 3600
        for p in prs
        if p.get("merged_at") and start <= parse_time(p["merged_at"]) < end
    ]
    sup.merged_prs = len(cycle)
    sup.median_pr_cycle_hours = statistics.median(cycle) if cycle else None

    since = start.strftime("%Y-%m-%d")
    runs = gh.paginate(
        f"repos/{repo}/actions/runs?branch={default_branch}&status=completed&created=%3E%3D{since}",
        key="workflow_runs",
        limit=500,
    )
    runs = [
        r for r in runs if r["conclusion"] in ("success", "failure")
        and start <= parse_time(r["created_at"]) < end
    ]  # fmt: skip
    sup.ci_runs = len(runs)
    if runs:
        sup.ci_failure_rate = sum(r["conclusion"] == "failure" for r in runs) / len(runs)
    recoveries: list[float] = []
    by_workflow: dict[int, list[dict[str, Any]]] = {}
    for r in runs:
        by_workflow.setdefault(r["workflow_id"], []).append(r)
    for wf_runs in by_workflow.values():
        wf_runs.sort(key=lambda r: parse_time(r["created_at"]))
        red_since: datetime | None = None
        for r in wf_runs:
            if r["conclusion"] == "failure" and red_since is None:
                red_since = parse_time(r["created_at"])
            elif r["conclusion"] == "success" and red_since is not None:
                recoveries.append((parse_time(r["updated_at"]) - red_since).total_seconds() / 3600)
                red_since = None
    sup.median_ci_recovery_hours = statistics.median(recoveries) if recoveries else None
    return sup
