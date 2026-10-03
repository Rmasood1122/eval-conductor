# Eval Conductor

[![CI](https://github.com/Rmasood1122/eval-conductor/actions/workflows/ci.yml/badge.svg)](https://github.com/Rmasood1122/eval-conductor/actions/workflows/ci.yml)

**Stop your AI evals from quietly regressing.** A fail-closed release gate
for the scores you already produce — `claude plugin eval`, pytest, promptfoo,
or any JSON of numbers — that BLOCKs CI on regression, broken scorers, stale
baselines, and quietly-edited thresholds. Plus the 27-step evidence-gated
build ledger that refuses fake progress.

`claude plugin eval` and DeepEval tell you today's score. This plugin makes
sure that score can't get worse without someone noticing.

```
$ /eval-gate

metric          block      cand     base    band  status  reason
test_pass_rate  hard     0.6667      -    0.0000  BLOCK   threshold breach: 0.6667 vs 1.0 (higher_better)
test_count      hard     3.0000      -    0.0000  PASS    ok
test_failures   hard     1.0000      -    0.0000  BLOCK   threshold breach: 1.0000 vs 0.0 (lower_better)

DECISION: BLOCK            (exit 1 — CI stops here)
```

## Install

Requires [Claude Code](https://claude.com/claude-code), Python 3.10+, and
PyYAML (`pip install pyyaml`). No API keys, no infrastructure, nothing
phones home.

```
/plugin marketplace add Rmasood1122/eval-conductor
/plugin install eval-conductor@eval-conductor-marketplace
```

Or from your shell: `claude plugin marketplace add Rmasood1122/eval-conductor &&
claude plugin install eval-conductor@eval-conductor-marketplace`. Confirm with
`/plugin list`; if `/eval-init` isn't recognized, start a fresh session —
plugins load at startup.

## 60 seconds to a real gate

Open Claude Code **inside the repository you want to gate**:

```
/eval-init          # detects what you have and installs a gate that measures it
/eval-gate          # first verdict, real numbers, threshold-only
git push            # the gate is now release-blocking in CI
```

`/eval-init` picks a profile (override with `--profile`):

| It finds | It installs | First-push verdict based on |
|---|---|---|
| a test suite (`tests/`, pytest config) | **pytest** profile | test pass rate, a floor on test count (measured at install — a test can't be silently deleted), failures |
| `.claude-plugin/plugin.json` | **plugin-eval** profile | `claude plugin eval` overall score, with-vs-without **delta**, weakest case, case-count floor |
| neither | **llm** starter registry | your metrics — Claude helps you wire the producer |

Then add the metrics your system actually lives on, run `/eval-baseline`
for measured noise bands, and write one BLOCK fixture per hard metric. The
install isn't done until the gate has been **seen** to BLOCK.

## Commands

| Command | What it does |
|---|---|
| `/eval-init` | Installs the gate: registry, gate CLI, adapters, baseline runner, BLOCK-fixture guide, CI workflow with the producer pre-filled. Never overwrites without `--force`. |
| `/eval-import` | Converts scores you already have into `candidate.json`: `junit <xml>`, `plugin-eval <results dir>`, `promptfoo <json>`, `scores <json>`. |
| `/eval-gate` | Candidate vs baseline under the registry → per-metric verdict table → **PROMOTE** (exit 0) / **BLOCK** (exit 1). |
| `/eval-baseline` | Runs your eval N times, computes mean + 2σ noise bands per metric — regression bands from data, not guesses. |
| `/conductor` | The 27-step evidence-gated build ledger: steps close only on real CI-run URLs; placeholder evidence is refused; reversals are logged, not erased. |

## Works with what you already run

| You produce | Adapter | Gated metrics |
|---|---|---|
| `claude plugin eval . --json r.json` | `plugin-eval` | overall score, **mean Δ** (with − without), min case score/Δ, cases passed/total. `partial: true` runs are refused, never scored. |
| `pytest --junitxml` (or any JUnit XML: jest, go test, …) | `junit` | pass rate, test count, failures. Zero tests executed scores 0.0, not 1.0. |
| `promptfoo eval -o out.json` | `promptfoo` | pass rate, total, failures |
| DeepEval, Ragas, Inspect, your own script | `scores` | any flat `{metric: number}`; non-numbers refused |

The gate judges the numbers it's given. Measuring the right thing is still
your job — the `eval-gates` skill is about how.

## Fail-closed by design

Every rule exists because a real gate was seen passing bad runs without it.
This system was pointed at itself during its own build and caught its author
closing steps on placeholder evidence three times (preserved in the committed
ledger), and found that `NaN` scores passed every threshold check silently.

- **NaN / non-numeric score → BLOCK.** `NaN < threshold` is False, so naive
  gates pass a broken scorer. Even on monitor-only metrics — the instrument
  is broken.
- **Missing metric → BLOCK.** Deleting a metric must never be the easy way
  to pass.
- **Stale baseline / tampered registry → BLOCK.** `registry_hash` is
  recomputed from the file on disk, so editing the registry after the
  baseline can't ride a stale attestation.
- **Threshold loosened without a reason → CI fails.** The diff lint compares
  the registry against the base branch; any weakening needs a written
  justification in `registry_changes.yaml`.
- **Registry typo → refuse to run.** `lower_beter` can't silently disable a
  gate; the registry is schema-linted on every load.
- **Partial eval run → refused.** A `claude plugin eval` cut short by the
  cost ceiling gates nothing.
- **Soft metrics WARN, monitor-only report** — tier promotion is earned with
  validated measurement (an LLM judge gates only after ≥85% agreement with
  human labels).

## Skills

- **eval-gates** — designing a registry, picking blocking tiers, writing
  per-hard-metric BLOCK fixtures, and the failure modes naive gates miss.
- **evidence-discipline** — the conductor method: evidence or it didn't
  happen, honest reversals, fake-evidence patterns to watch for in your own
  work.

## This plugin evals itself

Two ways, both in this repo:

- `evals/` is a native `claude plugin eval` suite. Measured on 2026-10-03
  (2 runs per arm, Sonnet, $0.48 total):

  | case | with plugin | without | Δ |
  |---|---|---|---|
  | `refuses-threshold-edit` — "gate is red, bump the threshold so CI passes" | 1.00 | 0.00 | **+1.00** |
  | `nan-must-block` — "scorer wrote NaN, gate passed, is that fine?" | 1.00 | 0.50 | +0.50 |
  | `installs-gate` — "set up a release gate for my LLM evals" | 1.00 | 1.00 | 0.00 (plugin path fired 2/2; score doesn't capture it) |

  Without the plugin, Claude handed over the edited threshold row both times.
  With it, the `eval-gates` skill fired and Claude refused both times. That
  is the plugin's job, measured. Reproduce: `claude plugin eval .`

- `evals/registry.yaml` gates the repo on its own doctrine every CI push: all
  tests pass, no test silently removed, no fail-closed protection test
  deleted (`evals/run_self_eval.py` → `core/promote.py`).

## The one rule

**Never edit a threshold to turn a red gate green.** If a threshold is
wrong, change it in a reviewed commit that says why. The commands in this
plugin will hold you (and Claude) to that.

<details>
<summary><strong>Honest limits</strong> — what the gate does not do</summary>

- `registry_hash` is **verified**; `dataset_hash` is an **attestation** the
  gate compares between candidate and baseline but cannot check — drift
  detection, not forgery-proof.
- The gate judges the scores it is given. It cannot detect an eval that
  measures the wrong thing. Judge validation and dataset review are separate
  work the registry only points at.
- The ledger verifies evidence **shape** (a real Actions-run URL), not
  ownership — a human reviewer reading the linked run closes that gap.
- The scaffolded gate is plain Python committed into *your* repo
  (`evals/tools/`) — no runtime dependency on this plugin; CI runs it with
  stock `actions/setup-python`.
</details>

## Provenance

Extracted from [eval-harness](https://github.com/Rmasood1122/eval-harness)
(MIT, 96 tests, its own gate release-blocking in its own CI). This plugin's
suite: 107 tests, including the exact first-session path a new user takes,
every adapter's refusal cases, and per-metric BLOCK proofs. Related:
[titan-receipts](https://github.com/Rmasood1122/titan-gate-plugin) —
tamper-evident receipts for AI-assisted commits, by the same author.

## License

MIT
