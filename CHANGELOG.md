# Changelog

## 1.2.0
- `usage` command: real CI run-history stats (runs, minutes, cadence) with
  clearly-hedged savings estimates. Reads from `--from-file` or the GitHub CLI.

## 1.1.0
- Security & reliability checks: action pinning, GITHUB_TOKEN permissions,
  deprecated actions/runners. Added the per-category health score and `score`.

## 1.0.0
- Renamed to pipewright. Maturity tiers (Starter/Growing/Scale) and a
  four-category model (speed, cost, security, reliability). New checks: job
  timeouts, double-run dedupe, Docker layer cache.

## 0.1.0 – 0.3.0
- detect, analyze, fix preview, and PR-based `fix --apply`.
