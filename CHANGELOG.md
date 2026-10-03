# Changelog

## 1.1.0 — 2026-10-03

Positioning: the gate for scores you already produce.

- **Adapters** (`core/adapters.py`, vendored into your repo; `/eval-import`):
  `junit` (pytest/jest/go JUnit XML), `plugin-eval` (`claude plugin eval`
  `aggregate-result.json` or results dir — latest run; `partial: true` refused),
  `promptfoo`, `scores` (flat JSON). All write a verified `registry_hash`.
- **Zero-config first run.** `/eval-init` auto-detects a profile: `pytest`
  (gates pass rate, a test-count floor measured at install, failures — CI
  producer pre-filled, green on first push), `plugin-eval` (gates overall
  score, with-vs-without delta, weakest case, case floor), or `llm` starter.
  `--profile` overrides.
- **Native eval suite**: `evals/` now holds `claude plugin eval` cases for
  this plugin (threshold-edit refusal, `/eval-init` triggering, NaN doctrine).
  Measured mean Δ +0.50 vs no plugin; threshold-edit case Δ +1.00.
- **Behaviour fix found by that suite**: the `eval-gates` skill did not
  trigger on "gate is red, bump the threshold so CI passes" — Claude agreed to
  the edit with the plugin installed. Its description now names those
  phrasings; the skill fires and refuses 2/2.
- **Template fix**: the optional conductor audit step is no longer `|| true`;
  it is a commented, release-blocking step you opt into.
- Review fixes: `test_count` floor uses pytest's *selected* count (deselected
  tests never reach JUnit) and returns unknown on collection errors; pytest
  profile requires a pytest config section or tests dir, and a 0-test repo
  falls back to `llm`; adapters refuse a missing registry instead of writing
  an unattested candidate; generated workflow installs requirements/-e .
- Self-gate thresholds raised to the new measured counts (112 tests, 23
  fail-closed tests). `run_self_eval.py` uses the shipped JUnit parser.
- README rewritten around the problem, with a real BLOCK verdict; limits
  moved to a collapsed section (unchanged in substance).

## 1.0.1

- Diff-lint and baseline-warning fixes.

## 1.0.0

- Initial release: fail-closed gate, baseline runner, registry lints,
  27-step conductor ledger, eval-gates and evidence-discipline skills.
