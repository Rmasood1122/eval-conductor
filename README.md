# Eval Conductor

**Release gates for AI systems that actually block — plus an evidence-gated
build ledger that refuses fake progress.**

Most eval setups are theater: gates that have never been seen to fire,
thresholds quietly edited until CI goes green, "done" steps with no proof
behind them. This plugin installs the opposite into any repository, in one
command, with no API keys and no infrastructure — Python 3.10+ and PyYAML
are the only requirements.

It was extracted from a working system that was pointed at itself during its
own build — and caught its own author closing steps on placeholder evidence
(three times, preserved in the committed ledger) and found that `NaN` scores
passed every threshold check silently. Every rule in this plugin exists
because a real gate was seen passing bad runs without it.

## Commands

| Command | What it does |
|---|---|
| `/eval-init` | Installs the gate into the current repo: starter metric registry, gate CLI, baseline runner, BLOCK-fixture guide, CI workflow. Never overwrites without `--force`. |
| `/eval-gate` | Runs the gate: candidate vs baseline under the registry → per-metric verdict table → **PROMOTE** (exit 0) / **BLOCK** (exit 1). |
| `/eval-baseline` | Runs your eval N times and computes mean + 2σ noise bands per metric — regression bands from data, not guesses. |
| `/conductor` | The 27-step evidence-gated build ledger: steps close only on real CI-run URLs; placeholder evidence is refused; reversals are logged, not erased. |

## Fail-closed by design

- **NaN / non-numeric score → BLOCK.** `NaN < threshold` is False, so naive
  gates pass a broken scorer silently. Not this one — even on
  monitor-only metrics, because the instrument itself is broken.
- **Missing metric → BLOCK.** Deleting a metric must never be the easy way
  to pass.
- **Stale baseline → BLOCK.** Candidate and baseline carry dataset/registry
  hashes; a mismatch blocks before any metric is judged.
- **Registry typo → refuse to run.** `lower_beter` cannot silently disable
  a gate: the registry is schema-linted (enums, required keys, no unknown
  keys) on every load.
- **Soft metrics WARN, monitor-only metrics report** — tier promotion is
  earned with validated measurement, not granted by default.

## Skills

- **eval-gates** — how to design a registry, pick blocking tiers, and write
  per-hard-metric BLOCK fixtures ("a gate never seen firing is theater").
- **evidence-discipline** — the conductor method: evidence or it didn't
  happen, honest reversals, and the fake-evidence patterns to watch for in
  your own work.

## Quickstart

```
/eval-init
# edit evals/registry.yaml to YOUR metrics
# make your eval run write evals/candidate.json
/eval-gate                       # first run, threshold-only
/eval-baseline --cmd "make eval" --runs 3
/eval-gate                       # now with measured regression bands
```

The scaffolded gate is plain Python committed into *your* repo
(`evals/tools/`) — no dependency on this plugin at runtime, nothing phones
home, CI runs it with stock `actions/setup-python`.

## The one rule

**Never edit a threshold to turn a red gate green.** If a threshold is
wrong, change it in a reviewed commit that says why. The commands in this
plugin will hold you (and Claude) to that.

## Provenance

Extracted from [eval-harness](https://github.com/Rmasood1122/eval-harness)
(MIT, 96 tests, its own gate runs release-blocking in its own CI). This
plugin's suite: 50 tests, including the exact first-session path a new user
takes and per-metric BLOCK proofs. Related:
[titan-gate](https://github.com/Rmasood1122/titan-gate) — tamper-evident
receipts for AI-assisted code changes.

## License

MIT
