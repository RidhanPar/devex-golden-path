# DORA metrics: definitions, data sources and limits

`python -m dora` reads the GitHub REST API and computes the four DORA metrics per
repository, then pools them into one view. Standard library only, so it runs anywhere Python
does:

```bash
python -m dora --owner RidhanPar --days 90 --out site      # all public, non-fork repos
python -m dora --repos OWNER/a OWNER/b --days 30           # explicit list
python -m dora --from-json results/dora-2026-10-07.json --out site   # re-render, no API calls
python -m dora --owner RidhanPar --exclude '^dx-measure-'  # skip throwaway experiment repos
```

It uses `GITHUB_TOKEN`/`GH_TOKEN`, or the GitHub CLI's login. A run over 35 repositories makes
about 300 API calls. The live dashboard is rebuilt weekly by `.github/workflows/dora-dashboard.yml`
and published to GitHub Pages.

## Where "a deployment" comes from

Per repository, in order of preference:

1. **GitHub Deployments** to a production-like environment: `production`, `prod`,
   `github-pages`, or `main - <service>` (Railway's naming). Preview and staging environments are
   excluded. A deployment counts once it has a `success` status, or a `failure`/`error` status
   and no success. Queued or in-progress deployments are ignored.
2. **Published GitHub Releases** (not drafts or pre-releases), each counted as a successful
   deployment at its publish time.
3. **Nothing.** The repository is reported as *no data*. The tool deliberately does **not**
   treat pushes to `main` as deployments; that would invent the very thing being measured.

## The four metrics

| Metric | Definition used here | Aggregation |
|---|---|---|
| Deployment frequency | Successful deployments per week in the window | Sum across repos |
| Lead time for changes | For each commit a successful deployment shipped for the first time (the commits between the previous successful deployment's SHA and this one, via the compare API), the time from the commit's committer date to the deployment succeeding | Median over all shipped commits |
| Change failure rate | (Failed deployment attempts + successful deployments whose changes the *next* deployment had to revert, hotfix or roll back, detected from commit messages) ÷ all attempts | Pooled ratio |
| Time to restore | From a failed (or later-remediated) deployment to the next successful deployment of the same repository | Median |

Each definition is a pure function in `dora/metrics.py` with unit tests in
`tests/test_dora_metrics.py`. The tests are the precise specification.

## Supplementary signals (not DORA)

Shown in separate columns so they aren't mistaken for DORA metrics: merged pull requests
and their open-to-merge time, and completed default-branch workflow runs with their failure
rate and red-to-green recovery time.

## Limits

- **Small samples.** These are personal portfolio repositories. On 2026-10-07, 9 of 35
  repositories had any deployment data and 3 deployed in the 90-day window. Medians over a
  handful of events are unstable, and one active repository dominates the pooled numbers.
- **Hosting changes what "deploy" means.** Vercel, GitHub Pages and Railway deploy every push
  to `main`, which raises frequency and shortens lead time compared with a service that
  has a release process.
- **Vercel lead times are a lower bound.** Inspection showed Vercel creates the deployment
  record *and* its success status together, 14–16 seconds after the commit, so build time is
  invisible to the API.
- **Railway records one deployment per service**, so one change to a three-service app can count
  as three deployments.
- **No incident data.** Change failure rate and time to restore only see failed deploys and
  commit messages that say revert, hotfix or rollback. A bad change that was fixed forward
  with an ordinary commit message is invisible, so the true failure rate can only be higher.
- **Lead time starts at the commit**, not when work started, and uses committer date (which a
  rebase resets). For the first deployment ever recorded, only its head commit is counted.
- These are **team-level system metrics**. They describe a delivery pipeline; using them to
  rank individuals would be wrong, and would quickly distort them.
