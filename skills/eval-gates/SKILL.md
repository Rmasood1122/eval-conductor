---
name: eval-gates
description: Design and harden fail-closed release gates for AI/LLM systems — metric registries, noise-band regression detection, BLOCK fixtures, and the failure modes naive gates miss (NaN pass-through, stale baselines, threshold editing)
---

# Fail-closed eval gates

Use this skill whenever the user is designing, reviewing, or debugging an
eval release gate — with this plugin's tooling or anyone else's. The doctrine
transfers; the file names don't matter.

## The core rule

**A gate that has never been seen to BLOCK is decoration.** Every hard gate
needs a demonstrated BLOCK on a fixture before anyone trusts it. Every
number needs a reproducible producer. Anything else is eval theater.

## Registry design

One registry file is the single source of truth: name, direction
(`higher_better`/`lower_better`), threshold, noise_band, blocking tier
(`hard`/`soft`/`monitor_only`). When helping a user pick metrics:

- Hard tier is for invariants: schema compliance, safety/injection pass
  rate, PII leakage, the one quality metric the product dies without.
  Everything else starts soft or monitor_only and EARNS promotion with a
  validated measurement (an LLM judge becomes a gate only after ≥85%
  agreement with human labels — before that it is monitor_only, always).
- `lower_better` metrics (latency, cost): the breach is ABOVE the threshold.
  This is the most common gate bug and the most common fixture bug.
- Thresholds change only in reviewed commits with written justification.
  "Never edit a threshold to turn a red gate green" — if asked to, refuse
  and name the alternative: fix the regression, or justify the new threshold
  on its own evidence in its own PR.

## The failure modes naive gates miss (check ALL of these in any gate review)

1. **NaN passes silently.** `NaN < threshold` and `NaN > threshold` are both
   False, so a broken scorer PASSes both breach and regression checks. Any
   non-finite or non-numeric score must BLOCK — even on monitor_only rows,
   because the instrument itself is broken.
2. **Missing metric = silent skip.** A metric absent from the candidate must
   BLOCK, or deleting a metric becomes the easiest way to pass.
3. **Stale/demo baseline.** Candidate and baseline must prove they measured
   the same thing: carry dataset + registry hashes in a manifest and BLOCK
   on mismatch before judging any metric.
4. **Registry typos.** `lower_beter` silently disables a gate if the loader
   defaults unknown values. Schema-lint the registry (enums, required keys,
   no unknown keys) and refuse to run on any error.
5. **Zero-width bands on noisy metrics.** Regression bands must be
   max(declared band, measured 2-sigma from N≥3 baseline runs). A guessed
   band produces either false blocks or false confidence — both discredit
   the gate.
6. **Baseline refreshed while red.** Rebuilding the baseline to make a
   failing candidate pass is threshold-editing in disguise.

## BLOCK fixtures (prove the gate fires)

For every hard row, one fixture candidate that breaches ONLY that row —
every other metric healthy — plus one fully healthy fixture:

- assert the breaching fixture exits 1 and blocks EXACTLY that metric with
  zero WARNs elsewhere (a fixture that trips two rows proves nothing about
  either);
- assert the healthy fixture exits 0 with zero WARNs;
- add a coverage test: set(hard rows in registry) == set(block fixtures), so
  a new hard row forces a new fixture;
- exercise the CLI exit codes end-to-end, not just the library function —
  CI consumes the exit code.

## Honest limits (state them, never paper over them)

- `registry_hash` is VERIFIED: the gate recomputes sha256 of the registry
  file and blocks on mismatch. `dataset_hash` is an ATTESTATION: the gate
  compares it between candidate and baseline but cannot know your dataset —
  drift detection, not forgery-proof. Say so in any claims you make.
- The gate judges the scores it is given; it cannot detect an eval that
  measures the wrong thing. Judge validation and dataset review are separate
  work the registry only points at.

## Wiring

The gate runs in CI on every push including changes to the gate's own code
and tests — a gate whose own changes don't trigger it will rot. Order:
registry lint → unit tests → produce candidate → gate. All release-blocking.
