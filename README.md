# Eval Conductor

[![CI](https://github.com/Rmasood1122/eval-conductor/actions/workflows/ci.yml/badge.svg)](https://github.com/Rmasood1122/eval-conductor/actions/workflows/ci.yml)

**The integrity layer for your evals.** Your evals already produce numbers — from
`claude plugin eval`, pytest, promptfoo, or your own scripts. This proves them: that
the verdict is real, the bar was fixed before the run, and the decision is
tamper-evident. It sits next to MLflow, LangSmith or Braintrust; it doesn't replace
them. It answers the one question none of them do:

> **Can you *prove* this eval result — or do we just trust it?**

Open source, MIT. stdlib + PyYAML only. No API keys, no infrastructure, nothing
phones home. Dogfooded on its own 178 tests.

*The thesis: trust an AI verdict only by what it can prove.*

## Start in 60 seconds — no config

```
/eval-prove
```

Runs the tests you already have, emits a **signed, tamper-evident receipt** that they
passed at this commit, and prints a badge to paste in your PR:

```
PROVEN: 142/142 tests pass (100%)   receipt a1b2c3…
![evals](https://img.shields.io/badge/evals-proven%20142%2F142-brightgreen)
```

The first run captures your current pass rate and test count as the bar. A later run
that quietly drops the pass rate — or deletes tests to go green — gets **BLOCKED**.
No registry, no setup. When you outgrow it, `/eval-init` installs the full gate.

## The three things no other eval tool does

A green eval is ephemeral: nothing proves *what* passed, *under which bar*, or that a
failure was ever produced. Eval Conductor closes that with three controls that
compose into one claim the incumbents can't make.

**1. The bar can't silently weaken.** A registry diff-lint compares your gate against
its own git history. Lower a threshold, flip a direction, downgrade a blocking tier,
widen a band, or delete a metric, and CI fails unless you committed a written reason
next to the change. "Never edit a threshold to turn a red gate green" — made
mechanical.

**2. The bar was fixed before the result.** `/eval-seal` hashes your registry (and
band floors) into a signed, hash-chained seal — containing no scores — *before* you
run. At gate time the live bar is re-hashed against it; a bar that moved after sealing
is caught. This closes p-hacking your own gate: choosing the threshold after you've
seen the number. (The diff-lint can't catch that on a brand-new gate — there's no
history to diff. The seal is that history, on purpose.)

**3. The decision is tamper-evident proof.** Every PROMOTE/BLOCK emits an HMAC-signed,
hash-chained **receipt** binding the decision to the exact registry, candidate and
baseline *bytes* it was computed from — stamped with whether it honored the
pre-registered bar. Delete or reorder a receipt and the chain breaks. "It passed"
becomes cryptographic proof it passed, unaltered, under this bar, at this time.

We proved this on ourselves: **[we p-hacked our own gate on purpose, and the receipt
caught it](docs/CASE_STUDY_verifiable_evals.md).**

## Fail-closed by design

Every rule exists because a real gate was seen passing a bad run without it. Pointed
at itself during its own build, this gate caught its author closing steps on
placeholder evidence three times (preserved in the committed ledger) and found that
`NaN` scores silently passed every threshold check.

- **NaN / non-numeric score → BLOCK**, even on monitor-only metrics. A broken
  instrument is not a passing run.
- **Missing metric → BLOCK.** Deleting a metric is never the easy way to pass.
- **Stale baseline / tampered registry → BLOCK.** The registry hash is recomputed
  from disk, so editing it after the baseline can't ride a stale attestation.
- **Partial eval run → refused.** A run cut short by a cost ceiling gates nothing.
- **Zero tests executed → 0.0, not 1.0.**

```
$ /eval-gate

metric          block      cand     base    band  status  reason
test_pass_rate  hard     0.6667      -    0.0000  BLOCK   threshold breach: 0.6667 vs 1.0 (higher_better)
test_count      hard     3.0000      -    0.0000  PASS    ok
test_failures   hard     1.0000      -    0.0000  BLOCK   threshold breach: 1.0000 vs 0.0 (lower_better)

DECISION: BLOCK            (exit 1 — CI stops here)
```

## Works with what you already run

| You produce | Adapter | Gated on |
|---|---|---|
| `pytest --junitxml` (or any JUnit: jest, go test…) | `junit` | pass rate, test count, failures |
| `claude plugin eval --json` | `plugin-eval` | score, with-vs-without delta, min case, cases passed |
| `promptfoo eval -o out.json` | `promptfoo` | pass rate, total, failures |
| DeepEval, Ragas, Inspect, your own script | `scores` | any flat `{metric: number}` |

The gate judges the numbers it's given. Measuring the right thing is still your job —
the `eval-gates` skill is about how.

## Commands

| Command | What it does |
|---|---|
| `/eval-prove` | **Start here.** Zero config: prove your existing tests with a signed receipt + a pasteable PR badge. First run sets the bar; a later regression blocks. |
| `/eval-seal` | Pre-register the bar: seal the registry + band floors before a run, so a decision can prove it was judged against a bar fixed in advance. |
| `/eval-verify` | Walk the receipt chain offline: structure, every signature, every decision vs. its own verdicts. Any tamper, fork, or mismatch → exit 1 naming the receipt. |
| `/eval-init` | Install the full gate into a repo: registry, gate CLI, adapters, baseline runner, BLOCK-fixture guide, CI workflow with the producer pre-filled. |
| `/eval-gate` | Candidate vs. baseline under the registry → per-metric verdict table → **PROMOTE** (exit 0) / **BLOCK** (exit 1). |
| `/eval-baseline` | Run your eval N times (default 10) and measure noise bands per metric — mean ± 2σ, or a robust median ± MAD for `band_method: mad`. Warns on low N or a zero band. |
| `/eval-explain` | Explain a decision in plain English: which metric, breach vs. regression beyond noise, the one legitimate fix — and the theater moves named. |
| `/eval-import` | Convert scores you already have into `candidate.json`: `junit`, `plugin-eval`, `promptfoo`, `scores`. |
| `/conductor` | The 27-step evidence-gated build ledger: steps close only on a real, green CI run (GitHub API–verified); placeholder evidence refused; reversals logged, not erased. |

## What this proves — exactly, no more

Honesty is the product, so here are the limits in plain sight:

- A **receipt** proves a decision is unaltered since signing under a key your team
  controls. It does **not** identify who signed, and it does not prove the candidate
  scores were produced honestly (that's the gate's and the adapters' job). Coverage is
  only as good as the chain is distributed — commit and push your receipts; a
  local-only chain is a claim, not evidence.
- A **seal** proves the bar is byte-identical to what was sealed and — via pushed git
  history — committed before the result. It does **not** prove the bar is strict
  *enough*. A pre-committed weak bar is still weak. A shared-secret key can't stop its
  holder backdating the timestamp, which is why ordering rests on pushed history, not
  the clock.
- A **green `/eval-prove` badge** proves "not worse than before," not "good." The badge
  always shows the test count so it can't imply coverage it doesn't have.

## Install

Requires [Claude Code](https://claude.com/claude-code), Python 3.10+, and PyYAML
(`pip install pyyaml`). No API keys, no infrastructure, nothing phones home.

```
/plugin marketplace add Rmasood1122/eval-conductor
/plugin install eval-conductor@eval-conductor-marketplace
```

Or from your shell: `claude plugin marketplace add Rmasood1122/eval-conductor &&
claude plugin install eval-conductor@eval-conductor-marketplace`. Confirm with
`/plugin list`; if `/eval-prove` isn't recognized, start a fresh session — plugins
load at startup.

## Skills

- **eval-gates** — designing a registry, picking blocking tiers, writing
  per-hard-metric BLOCK fixtures, and the failure modes naive gates miss.
- **evidence-discipline** — the conductor method: evidence or it didn't happen, honest
  reversals, fake-evidence patterns to watch for in your own work.

## Provenance

The tamper-evident receipt engine (canonicalization + fork-detecting hash chain) is
fused from [titan-gate](https://github.com/Rmasood1122/titan-gate-plugin), signed
receipts for AI-assisted commits, by the same author. Same thesis, different layer.

## License

MIT.
