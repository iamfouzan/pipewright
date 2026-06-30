# ciwright

> Keep your CI pipelines fast, cheap, secure, and reliable — and fix them with a PR.

A "wright" builds and keeps things in good repair. **Pipewright** reads a repo's
GitHub Actions setup, scores it across four areas, and proposes each fix as a
pull request you approve. It never edits your pipeline in place: every change
lands on a new branch, and `main` is never touched.

This is **v1.2** (Python-first).

## Install

```bash
# once published:
uvx ciwright analyze        # or: pipx run ciwright analyze

# from source:
pip install -e ".[dev]"
```

The CLI is `ciwright`, with a short `pw` alias.

## Use

```bash
ciwright detect        # what does ciwright see in this repo?
ciwright score         # the CI health score, per category
ciwright analyze       # the score + tier-relevant findings (read-only)
ciwright usage         # real run-history stats + rough savings estimates
ciwright fix           # preview the exact YAML changes as a diff
ciwright fix --apply   # open the changes as a pull request (new branch, never main)
```

`usage` reads run history from the GitHub CLI (`gh`) or a JSON file:

```bash
gh api repos/OWNER/NAME/actions/runs > runs.json
ciwright usage --from-file runs.json
```

## The health score

Lighthouse-style, 0–100 per category, scored only over the checks that matter at
your pipeline's tier:

```
CI health  56/100
  speed       ████████░░   75  3/4 ok
  cost        ░░░░░░░░░░    0  0/2 ok
  security    █████░░░░░   50  1/2 ok
  reliability ██████████  100  1/1 ok
```

## It meets your pipeline where it is

Pipewright sorts your pipeline into a tier from the YAML alone, and only shows
checks relevant to that tier — so a tiny workflow isn't nagged about (or graded
on) monorepo machinery.

- **Starter** — one workflow, one job. The safe basics only.
- **Growing** — several jobs, a matrix, a real test suite. Adds parallelism, job
  timeouts, double-run dedupe, and the security checks.
- **Scale** — monorepo, Docker, many jobs. Adds test splitting and Docker caching.

## What it checks (Python edition)

| Check | Area | Tier |
| --- | --- | --- |
| Cache dependencies | speed | starter |
| Cancel superseded runs | speed | starter |
| Skip docs-only changes | speed | starter |
| Replace deprecated actions/runners | reliability | starter |
| Set job timeouts | cost | growing |
| Avoid double CI runs | cost | growing |
| Run tests in parallel | speed | growing |
| Pin actions to a SHA | security | growing |
| Limit GITHUB_TOKEN scope | security | growing |
| Split tests across machines | speed | scale |
| Cache Docker layers | speed | scale |

For deep GitHub Actions *security* auditing, pair ciwright with
[zizmor](https://github.com/zizmorcore/zizmor) — it's the specialist there.
Pipewright's lane is the unified score plus one-command autofix PRs for the
speed and cost wins.

## What it deliberately will *not* do

- It will never edit your pipeline silently. `fix --apply` puts changes on a new
  branch and opens a pull request you read and approve.
- Only **safe** changes are auto-applied — caching, path filters, concurrency.
  Everything else, including all security and structural changes, is advisory.
- `usage` separates **measured facts** from **savings estimates**, and keeps the
  estimates clearly hedged. No single confident-but-wrong "saves N minutes".

## Publishing

`python -m build` produces the sdist + wheel; both pass `twine check`. The
included `.github/workflows/release.yml` publishes to PyPI via Trusted
Publishing (OIDC — no API token) when you publish a GitHub release. Before the
first publish: create the project on PyPI, add a trusted publisher for this
repo + a `pypi` environment, and pin the workflow's actions to SHAs.

## Roadmap

- [x] **v0.1–v0.3** — detect, analyze, preview, and PR-based apply
- [x] **v1.0** — rebrand, maturity tiers, four-area checks
- [x] **v1.1** — security & reliability checks + the health score
- [x] **v1.2** — usage stats + savings estimates; packaging & release workflow
- [ ] later — Node + pnpm, then GitLab CI

## Develop

```bash
pip install -e ".[dev]"
pytest          # 62 tests
ruff check .
```

## License

MIT — see [LICENSE](LICENSE).
