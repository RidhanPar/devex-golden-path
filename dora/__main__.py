"""Compute DORA metrics for GitHub repositories and write a JSON + static HTML report.

python -m dora --owner RidhanPar                      # all public, non-fork repos
python -m dora --repos RidhanPar/a RidhanPar/b --days 30
python -m dora --owner RidhanPar --out site           # site/index.html + site/dora.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dora.collect import (
    DEFAULT_ENV_PATTERN,
    collect_deployments,
    collect_supplementary,
    list_repos,
)
from dora.github import GitHub, token_from_env
from dora.metrics import Deployment, compute
from dora.report import fmt_hours, fmt_pct, metrics_dict, render_html, summarize


def weekly(deploys: list[Deployment], start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Successful deployments per week (weeks start Monday), with a per-repo breakdown."""
    first = (start - timedelta(days=start.weekday())).date()
    weeks: list[dict[str, Any]] = []
    day = first
    while day < end.date():
        weeks.append({"week": day.isoformat(), "count": 0, "by_repo": Counter()})
        day += timedelta(days=7)
    for d in deploys:
        if d.succeeded and start <= d.finished_at < end:
            idx = (d.finished_at.date() - first).days // 7
            weeks[idx]["count"] += 1
            weeks[idx]["by_repo"][d.repo.split("/", 1)[1]] += 1
    return [{**w, "by_repo": dict(w["by_repo"])} for w in weeks]


def main() -> None:
    parser = argparse.ArgumentParser(description="DORA metrics from the GitHub API")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--owner", help="all public, non-fork, non-archived repos of this user")
    group.add_argument("--repos", nargs="+", help="explicit OWNER/REPO list")
    group.add_argument(
        "--from-json", type=Path, help="re-render HTML from a saved dora.json (no API calls)"
    )
    parser.add_argument("--days", type=int, default=90, help="window length (default 90)")
    parser.add_argument("--env-pattern", default=DEFAULT_ENV_PATTERN)
    parser.add_argument("--out", type=Path, default=Path("site"), help="output directory")
    args = parser.parse_args()

    if args.from_json:
        saved = json.loads(args.from_json.read_text(encoding="utf-8"))
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "index.html").write_text(render_html(saved), encoding="utf-8")
        print(f"re-rendered {args.out / 'index.html'} from {args.from_json}")
        return

    gh = GitHub(token_from_env())
    end = datetime.now(UTC)
    start = end - timedelta(days=args.days)

    if args.owner:
        repo_meta = [(r["full_name"], r["default_branch"]) for r in list_repos(gh, args.owner)]
        owner = args.owner
    else:
        repo_meta = []
        for full_name in args.repos:
            meta = gh.get(f"repos/{full_name}")
            if meta is None:
                sys.exit(f"repository not found: {full_name}")
            repo_meta.append((full_name, meta["default_branch"]))
        owner = args.repos[0].split("/", 1)[0]

    rows: list[dict[str, Any]] = []
    all_deploys: list[Deployment] = []
    for full_name, branch in sorted(repo_meta, key=lambda r: r[0].lower()):
        source, deploys = collect_deployments(gh, full_name, args.env_pattern)
        all_deploys.extend(deploys)
        metrics = compute(full_name, source, deploys, start, end)
        sup = collect_supplementary(gh, full_name, branch, start, end)
        rows.append(
            {"repo": full_name, "metrics": metrics_dict(metrics), "supplementary": vars(sup)}
        )
        print(
            f"{full_name:55} {source:12} ok/attempts={metrics.successes}/{metrics.attempts} "
            f"lead={fmt_hours(metrics.median_lead_time_hours):>9} "
            f"cfr={fmt_pct(metrics.change_failure_rate):>4} "
            f"restore={fmt_hours(metrics.median_restore_hours):>9}",
            flush=True,
        )

    report: dict[str, Any] = {
        "owner": owner,
        "generated_at": end.strftime("%Y-%m-%d %H:%M"),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_days": args.days,
        "env_pattern": args.env_pattern,
        "summary": summarize(rows),
        "weekly": weekly(all_deploys, start, end),
        "repos": rows,
        "api_calls": gh.calls,
    }
    by_source: defaultdict[str, int] = defaultdict(int)
    for r in rows:
        by_source[r["metrics"]["source"]] += 1
    report["summary"]["repos_by_source"] = dict(by_source)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "dora.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (args.out / "index.html").write_text(render_html(report), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"wrote {args.out / 'index.html'} and {args.out / 'dora.json'} ({gh.calls} API calls)")


if __name__ == "__main__":
    main()
