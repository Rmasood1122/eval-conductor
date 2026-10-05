---
description: Prove your tests pass — one command turns an existing test suite into a signed, tamper-evident receipt plus a pasteable PR badge, with no registry or config
argument-hint: "[--junit report.xml] [--run \"CMD\"] [--min-pass-rate 0.95]"
---

Turn the user's existing tests into a shareable proof, zero config:

```
TOOL="evals/tools/wedge.py"; [ -f "$TOOL" ] || TOOL="${CLAUDE_PLUGIN_ROOT}/core/wedge.py"; python3 "$TOOL" $ARGUMENTS
```

(Runs zero-config straight from the installed plugin — no `/eval-init` needed. It uses a vendored `evals/tools/wedge.py` if the repo already has one, otherwise the plugin's own copy. `/eval-init` later graduates the repo to the full gate.)

What it does, in one run:

- **Detects and runs** the repo's test suite (pytest by default), or consumes a
  JUnit file you pass with `--junit`, or any command that writes JUnit via
  `--run "pytest --junitxml={junit}"`.
- **Proves the result** with the same signed, hash-chained receipt engine as the
  full gate — so a wedge proof and a gate proof verify identically. A signing key
  is generated (gitignored) on the first run, so proofs are signed by default.
- **Auto-gates (capture-then-gate)**: the FIRST run has nothing to regress
  against, so it PROMOTEs and records the measured pass-rate and test-count as the
  bar. LATER runs BLOCK if the pass-rate drops or tests disappear. The bar
  ratchets up on a clean run and never down — a BLOCK never lowers it.
- **Prints a pasteable PR badge** — a shields.io line the user drops into a pull
  request so a teammate sees the proof.

Report the result honestly:

- **Exit 0 — PROVEN.** Say what it proves and what it does not: it proves "not
  worse than the captured bar", NOT "good", and the badge shows the test COUNT so
  it never implies more coverage than exists. One run does not calibrate flakiness.
- **Exit 1 — BLOCKED.** A real regression vs the user's own captured bar
  (pass-rate dropped, or tests vanished — the oldest way to turn a gate green).
  Name which. Do NOT "fix" it by deleting the baseline file or lowering
  `--min-pass-rate` to force green — investigate the regression.
- **Exit 2 — CANNOT PROVE.** No test suite was detectable and no `--junit`/`--run`
  was given, or the run produced no JUnit. Fail-closed by design: there is no
  proof of a run that was never measured. Point the user at `--junit` or `--run`.

This is the on-ramp. When the user is ready for real thresholds, measured noise
bands, and a metric registry, graduate them to `/eval-init`.
