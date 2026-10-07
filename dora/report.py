"""Render DORA results as JSON and as a self-contained static HTML dashboard."""

from __future__ import annotations

import html
import json
import statistics
from typing import Any

from dora.metrics import RepoMetrics


def fmt_hours(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value < 1 / 60:
        return f"{value * 3600:.0f} s"
    if value < 1:
        return f"{value * 60:.0f} min"
    if value < 48:
        return f"{value:.1f} h"
    return f"{value / 24:.1f} days"


def fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pool all repositories that have deployment data into one organisation-level view."""
    with_data = [r for r in rows if r["metrics"]["source"] != "none"]
    lead = [h for r in with_data for h in r["metrics"]["lead_time_hours"]]
    restore = [h for r in with_data for h in r["metrics"]["restore_hours"]]
    attempts = sum(r["metrics"]["attempts"] for r in with_data)
    failures = sum(r["metrics"]["failures"] for r in with_data)
    return {
        "repos_total": len(rows),
        "repos_with_deploy_data": len(with_data),
        "repos_with_deploys_in_window": sum(1 for r in with_data if r["metrics"]["attempts"]),
        "successful_deploys": sum(r["metrics"]["successes"] for r in with_data),
        "deploy_attempts": attempts,
        "deploys_per_week": sum(r["metrics"]["deploys_per_week"] for r in with_data),
        "median_lead_time_hours": statistics.median(lead) if lead else None,
        "lead_time_samples": len(lead),
        "change_failure_rate": failures / attempts if attempts else None,
        "failures": failures,
        "median_restore_hours": statistics.median(restore) if restore else None,
        "restore_samples": len(restore),
        "unrestored_failures": sum(r["metrics"]["unrestored_failures"] for r in with_data),
    }


def metrics_dict(m: RepoMetrics) -> dict[str, Any]:
    return {
        "source": m.source,
        "window_days": m.window_days,
        "attempts": m.attempts,
        "successes": m.successes,
        "deploys_per_week": round(m.deploys_per_week, 3),
        "lead_time_hours": [round(h, 6) for h in m.lead_time_hours],
        "median_lead_time_hours": m.median_lead_time_hours,
        "failures": m.failures,
        "change_failure_rate": m.change_failure_rate,
        "restore_hours": [round(h, 6) for h in m.restore_hours],
        "median_restore_hours": m.median_restore_hours,
        "unrestored_failures": m.unrestored_failures,
    }


def _tile(label: str, value: str, note: str) -> str:
    return (
        f'<div class="tile"><div class="tile-label">{html.escape(label)}</div>'
        f'<div class="tile-value">{html.escape(value)}</div>'
        f'<div class="tile-note">{html.escape(note)}</div></div>'
    )


def render_html(report: dict[str, Any]) -> str:
    s = report["summary"]
    tiles = "".join(
        [
            _tile(
                "Deployment frequency",
                f"{s['deploys_per_week']:.1f} / week",
                f"{s['successful_deploys']} successful deploys in {report['window_days']} days",
            ),
            _tile(
                "Lead time for changes",
                fmt_hours(s["median_lead_time_hours"]),
                f"median of {s['lead_time_samples']} shipped commits",
            ),
            _tile(
                "Change failure rate",
                fmt_pct(s["change_failure_rate"]),
                f"{s['failures']} of {s['deploy_attempts']} deployment attempts",
            ),
            _tile(
                "Time to restore",
                fmt_hours(s["median_restore_hours"]),
                f"median of {s['restore_samples']} restorations"
                + (
                    f"; {s['unrestored_failures']} not restored" if s["unrestored_failures"] else ""
                ),
            ),
        ]
    )
    body_rows = []
    # Repos that deployed in the window first, then ones with any deployment data, then the rest.
    ordered = sorted(
        report["repos"],
        key=lambda r: (
            -r["metrics"]["attempts"],
            r["metrics"]["source"] == "none",
            -r["supplementary"]["ci_runs"],
            r["repo"].lower(),
        ),
    )
    for r in ordered:
        m, sup = r["metrics"], r["supplementary"]
        name = html.escape(r["repo"])
        source = {"deployments": "Deployments", "releases": "Releases", "none": "no data"}[
            m["source"]
        ]
        body_rows.append(
            "<tr>"
            f'<td><a href="https://github.com/{name}">{name.split("/", 1)[1]}</a></td>'
            f"<td>{source}</td>"
            f'<td class="num">{m["successes"]}/{m["attempts"]}</td>'
            f'<td class="num">{m["deploys_per_week"]:.2f}</td>'
            f'<td class="num">{fmt_hours(m["median_lead_time_hours"])}</td>'
            f'<td class="num">{fmt_pct(m["change_failure_rate"])}</td>'
            f'<td class="num">{fmt_hours(m["median_restore_hours"])}</td>'
            f'<td class="num">{sup["merged_prs"]}</td>'
            f'<td class="num">{fmt_hours(sup["median_pr_cycle_hours"])}</td>'
            f'<td class="num">{sup["ci_runs"]}</td>'
            f'<td class="num">{fmt_pct(sup["ci_failure_rate"])}</td>'
            "</tr>"
        )
    data_json = json.dumps(report["weekly"]).replace("</", "<\\/")
    return TEMPLATE.format(
        owner=html.escape(report["owner"]),
        generated=html.escape(report["generated_at"]),
        start=html.escape(report["window_start"][:10]),
        end=html.escape(report["window_end"][:10]),
        days=report["window_days"],
        repos_total=s["repos_total"],
        repos_with_data=s["repos_with_deploy_data"],
        repos_in_window=s["repos_with_deploys_in_window"],
        tiles=tiles,
        rows="\n".join(body_rows),
        data=data_json,
        api_calls=report["api_calls"],
    )


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DORA Metrics Dashboard</title>
<style>
:root {{
  color-scheme: light;
  --surface: #fcfcfb; --surface-2: #f3f2ef; --border: #e2e1dc;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #77756f;
  --series-1: #2a78d6; --grid: #e8e7e3; --link: #1c5cab;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --surface: #1a1a19; --surface-2: #232321; --border: #383835;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #9a998f;
    --series-1: #3987e5; --grid: #2e2e2c; --link: #86b6ef;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --surface: #1a1a19; --surface-2: #232321; --border: #383835;
  --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #9a998f;
  --series-1: #3987e5; --grid: #2e2e2c; --link: #86b6ef;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--surface); color: var(--text-primary);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 32px 16px 64px; }}
h1 {{ font-size: 28px; margin: 0 0 4px; }}
h2 {{ font-size: 19px; margin: 40px 0 12px; }}
a {{ color: var(--link); }}
.sub {{ color: var(--text-secondary); margin: 0; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px; margin-top: 24px; }}
.tile {{ background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px; }}
.tile-label {{ color: var(--text-secondary); font-size: 13px; }}
.tile-value {{ font-size: 30px; font-weight: 650; font-variant-numeric: tabular-nums;
  margin: 4px 0; }}
.tile-note {{ color: var(--text-muted); font-size: 13px; }}
.chart {{ position: relative; background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px; }}
.chart svg {{ display: block; width: 100%; height: auto; }}
.tip {{ position: absolute; pointer-events: none; background: var(--surface);
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 13px;
  box-shadow: 0 2px 8px rgb(0 0 0 / .15); display: none; white-space: nowrap; }}
.table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left;
  white-space: nowrap; }}
th {{ background: var(--surface-2); color: var(--text-secondary); font-weight: 600;
  font-size: 13px; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.group {{ text-align: center; border-left: 1px solid var(--border); }}
dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 8px 16px; }}
dt {{ font-weight: 600; }}
dd {{ margin: 0; color: var(--text-secondary); }}
ul.limits li {{ color: var(--text-secondary); margin-bottom: 6px; }}
footer {{ margin-top: 40px; color: var(--text-muted); font-size: 13px; }}
@media (max-width: 600px) {{ dl {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<main>
<h1>DORA metrics: github.com/{owner}</h1>
<p class="sub">Window {start} to {end} ({days} days). {repos_total} public repositories scanned,
{repos_with_data} have deployment data, {repos_in_window} deployed in this window.
Generated {generated} UTC.</p>

<div class="tiles">{tiles}</div>

<h2>Successful deployments per week (all repositories)</h2>
<div class="chart" id="chart"><div class="tip" id="tip"></div></div>

<h2>Per repository</h2>
<div class="table-wrap"><table>
<thead>
<tr><th></th><th></th><th class="group" colspan="5">DORA (deployment-based)</th>
<th class="group" colspan="4">Supplementary (not DORA)</th></tr>
<tr><th>Repository</th><th>Deploy source</th><th class="num">OK / attempts</th>
<th class="num">Deploys / week</th><th class="num">Median lead time</th>
<th class="num">Change failure rate</th><th class="num">Median time to restore</th>
<th class="num">Merged PRs</th><th class="num">Median PR cycle</th>
<th class="num">Main CI runs</th><th class="num">Main CI failure rate</th></tr>
</thead>
<tbody>
{rows}
</tbody></table></div>

<h2>Definitions</h2>
<dl>
<dt>Deployment</dt><dd>A GitHub Deployment to a production-like environment (production, prod,
github-pages, or "main - &lt;service&gt;") that reached <em>success</em> or <em>failure</em>. Repositories with none fall back
to published GitHub Releases. Repositories with neither show <em>no data</em>: pushes are never
counted as deployments.</dd>
<dt>Deployment frequency</dt><dd>Successful deployments per week in the window.</dd>
<dt>Lead time for changes</dt><dd>For every commit a successful deployment shipped for the first
time (commits since the previous successful deployment), the time from the commit's committer
date to the deployment succeeding. Median across commits.</dd>
<dt>Change failure rate</dt><dd>Deployment attempts that failed, plus successful deployments
whose changes the next deployment had to revert, hotfix or roll back (commit message), divided
by all deployment attempts.</dd>
<dt>Time to restore</dt><dd>From a failed (or later-remediated) deployment to the next
successful deployment of the same repository. Median.</dd>
</dl>

<h2>Limits: read before quoting these numbers</h2>
<ul class="limits">
<li>These are personal portfolio repositories, mostly maintained by one person. Small samples
make medians unstable; one busy repository can dominate the pooled numbers.</li>
<li>"Deployment" means what GitHub recorded. Many deployments here come from hosts that deploy
every push to main (Vercel, GitHub Pages, Railway), which raises frequency and shortens lead
time compared with a service that has a release process. Vercel records a deployment and its
success status together, seconds after the push, so its lead times are a lower bound
(build time is not included). Railway records one deployment per service, so one change to a
three-service app counts as up to three deployments.</li>
<li>Change failure rate and time to restore have no incident data behind them. A bad change
that was never reverted with a recognisable commit message is invisible, so the real rate
can only be higher.</li>
<li>Lead time starts at the commit's committer date, not when work began. For the first
deployment ever recorded only its head commit is counted.</li>
<li>Two repositories are themselves part of this project: <code>devex-golden-path</code>
(this dashboard's Pages deployments) and <code>golden-path-demo-service</code> (a demo service whose
deployments were driven while building it, including one real failed deploy). Throwaway
measurement repositories (<code>dx-measure-*</code>) are excluded.</li>
<li>Supplementary columns are context, not DORA metrics: merged PRs and their open-to-merge
time, and the share of completed default-branch workflow runs that failed.</li>
</ul>

<footer>Generated by <code>python -m dora</code> in
<a href="https://github.com/RidhanPar/devex-golden-path">devex-golden-path</a>
({api_calls} GitHub API calls). Raw numbers: <a href="dora.json">dora.json</a>.</footer>
</main>
<script>
(() => {{
  const data = {data};
  const root = document.getElementById("chart");
  const tip = document.getElementById("tip");
  const W = 1000, H = 260, m = {{ top: 12, right: 12, bottom: 40, left: 36 }};
  const iw = W - m.left - m.right, ih = H - m.top - m.bottom;
  const max = Math.max(1, ...data.map(d => d.count));
  const step = Math.max(1, Math.ceil(max / 4));
  const top = Math.ceil(max / step) * step;
  const bw = iw / data.length, gap = Math.min(8, bw * 0.25);
  const y = v => m.top + ih - (v / top) * ih;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${{W}} ${{H}}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Successful deployments per week; the table below has per-repository values");
  const el = (tag, attrs, text) => {{
    const e = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (text !== undefined) e.textContent = text;
    svg.appendChild(e); return e;
  }};
  for (let v = 0; v <= top; v += step) {{
    el("line", {{ x1: m.left, x2: W - m.right, y1: y(v), y2: y(v), stroke: "var(--grid)" }});
    el("text", {{ x: m.left - 6, y: y(v) + 4, "text-anchor": "end", "font-size": 12,
      fill: "var(--text-muted)" }}, v);
  }}
  data.forEach((d, i) => {{
    const x = m.left + i * bw + gap / 2, w = bw - gap, h = (d.count / top) * ih;
    if (d.count > 0) {{
      const r = Math.min(4, w / 2, h);
      el("path", {{ fill: "var(--series-1)", d:
        `M${{x}},${{y(0)}} V${{y(d.count) + r}} Q${{x}},${{y(d.count)}} ${{x + r}},${{y(d.count)}} ` +
        `H${{x + w - r}} Q${{x + w}},${{y(d.count)}} ${{x + w}},${{y(d.count) + r}} V${{y(0)}} Z` }});
    }}
    if (i % Math.ceil(data.length / 7) === 0) {{
      el("text", {{ x: x + w / 2, y: H - m.bottom + 18, "text-anchor": "middle", "font-size": 12,
        fill: "var(--text-muted)" }}, d.week.slice(5));
    }}
    const hit = el("rect", {{ x: m.left + i * bw, y: m.top, width: bw, height: ih,
      fill: "transparent" }});
    hit.addEventListener("mousemove", ev => {{
      const repos = Object.entries(d.by_repo).sort((a, b) => b[1] - a[1])
        .map(([r, n]) => `${{r}}: ${{n}}`).join("<br>");
      tip.innerHTML = `<b>Week of ${{d.week}}</b><br>${{d.count}} successful deploy(s)` +
        (repos ? `<br>${{repos}}` : "");
      tip.style.display = "block";
      const box = root.getBoundingClientRect();
      const left = Math.min(ev.clientX - box.left + 12, box.width - tip.offsetWidth - 4);
      tip.style.left = `${{Math.max(4, left)}}px`;
      tip.style.top = `${{ev.clientY - box.top + 12}}px`;
    }});
    hit.addEventListener("mouseleave", () => {{ tip.style.display = "none"; }});
  }});
  el("line", {{ x1: m.left, x2: W - m.right, y1: y(0), y2: y(0), stroke: "var(--text-muted)" }});
  root.insertBefore(svg, tip);
}})();
</script>
</body>
</html>
"""
