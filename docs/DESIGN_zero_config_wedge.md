# Design — zero-config wedge (`/eval-prove`), BUILD 1

Status: design. Branch `feat/zero-config-wedge`, base `main` (v1.2.0, receipts).
Independent of the open pre-registration PR #5.

## Why this exists (the panel's binding verdict)
The endorsement gate is USAGE, and `/eval-init`'s registry-authoring is a config
cliff before any payoff. This command removes the cliff: **install → one command →
a shareable signed proof in ~60 seconds, no registry, no editing.** It is the
"install it, run it, show a teammate" loop that manufactures the first real usage.

Scope (Rehan's call): **proof + auto-gate** — the first run also establishes a
real regression bar, so a later run BLOCKs on a genuine regression.

## The command: `/eval-prove`  (core/wedge.py)
```
python3 evals/tools/wedge.py [--junit PATH] [--run CMD] [--dir DIR]
                             [--receipts-dir DIR] [--receipt-key PATH]
                             [--baseline-file PATH] [--min-pass-rate FLOAT]
```
Zero required args. Exit 0 = PROMOTE, 1 = BLOCK, 2 = can't measure (fail-closed).

### Flow
1. **Detect** the test suite (reuse `eval_init.detect_profile` / `count_tests`):
   pytest markers/config, or `test_*.py`. If `--junit` is given, skip running and
   consume it. If nothing is detectable and no `--junit`, exit 2 with a one-line
   "point me at a JUnit file or a test command" message — never a stack trace.
2. **Run** → JUnit XML. Default: `pytest -q --junitxml=<tmp>`. Override with
   `--run "CMD"` (any command that writes JUnit to a known path) or `--junit`.
   A run that cannot produce JUnit → exit 2 (can't prove what you can't measure).
3. **Score** (reuse `adapters.parse_junit`/`junit_scores`): `test_pass_rate`,
   `test_count`, `test_failures`. Zero executed tests → pass_rate 0.0 (fail-closed,
   inherited).
4. **Auto-gate — capture-then-gate (the honest trivial gate):**
   - **First run** (no baseline file): the measured `test_pass_rate` and
     `test_count` BECOME the bar, written to `evals/.wedge-baseline.json`.
     Decision = PROMOTE (you can't regress against nothing). A hardcoded
     `pass_rate >= 1.0` is rejected: it BLOCKs any flaky suite on run one and
     kills the wedge. The honest bar is "don't get worse than you are now."
   - **Later runs**: build an in-memory registry from the baseline —
     `test_pass_rate` **hard**, floor = baseline rate (direction higher_better);
     `test_count` **hard**, floor = baseline count (losing tests is the classic
     silent weakening); `test_failures` **monitor_only**. Run `compare.decide`.
     BLOCK if pass-rate dropped or tests vanished.
   - `--min-pass-rate X` overrides the captured floor (opt-in strictness).
   - The baseline file updates to the new (non-regressing) numbers on PROMOTE,
     so the bar ratchets forward, never backward. A BLOCK never lowers the bar.
5. **Receipt** (reuse `eval_receipt.emit`, the exact v1.2 engine): emit a signed,
   hash-chained receipt for this PROMOTE/BLOCK. Auto-generate a gitignored key on
   first run if none exists (same move as `/eval-init`), so proofs are signed by
   default. The receipt binds to the JUnit bytes + the in-memory gate.
6. **Badge + summary (the shareable unit):** print
   - a one-line human summary (`PROVEN: 142/142 tests pass (100%), receipt
     a1b2c3…, chain head …`), and
   - a **pasteable PR badge**: a shields.io static-badge Markdown line
     `![evals](https://img.shields.io/badge/evals-proven%20142%2F142-brightgreen)`
     plus the short receipt hash, ready to drop in a PR description. On BLOCK the
     badge is red and names the regression.
   The badge is the thing a user pastes where a teammate sees it — the growth loop.

### What it deliberately does NOT do
- No registry file, no bands math, no baseline-runner — that's the `/eval-init`
  path for teams who outgrow the wedge. The wedge is the on-ramp; `/eval-init` is
  the next room. The wedge README line points there.
- No network calls (the shields URL is just text in the output; nothing is fetched).
- No pre-registration (that's PR #5; the wedge composes with it later for free).

## Honesty about the auto-gate (stated in output + README)
- A capture-then-gate bar proves "not worse than the first run," NOT "good." A
  green badge on a suite of 3 trivial tests is honest about what it is: 3 tests,
  proven. The badge shows the count so it can't imply more coverage than exists.
- `test_pass_rate` from a flaky suite can still cause a later false BLOCK — the
  summary says so and points to `--min-pass-rate` / the full `/eval-init` bands
  path for measured noise. We don't pretend one run calibrates noise.

## Reuse map (this is orchestration, not new logic)
- detect: `scripts/eval_init.detect_profile`, `count_tests`
- score: `core/adapters.parse_junit`, `junit_scores`
- gate: `core/compare.decide`
- proof: `core/eval_receipt.emit` + `load_key_from` + `cmd_init` key-gen pattern
New code = detection glue, the capture-then-gate baseline file, and the badge
formatter. Everything load-bearing is the already-tested engine.

## Tests (tests/test_wedge.py, red first)
1. first run, all pass → PROMOTE, baseline file written, receipt emitted, badge printed
2. first run captures rate<1.0 (a failing test) → PROMOTE at that rate (no false BLOCK)
3. second run, pass-rate drops → BLOCK
4. second run, test_count drops (a test deleted) → BLOCK
5. second run, same or better → PROMOTE, baseline ratchets up, never down
6. emitted receipt verifies (chain OK) and records the decision
7. no registry file anywhere in the flow (zero-config invariant)
8. auto-key generated when absent; receipts signed
9. undetectable suite + no --junit → exit 2 with guidance, no traceback
10. CLI smoke: `wedge.py --junit <xml>` end to end

## Versioning
Bump to **1.3.0 on this branch** is a conflict risk with PR #5 (also 1.3.0).
Resolution: this branch targets **1.4.0**; whichever merges first, the other
rebases its single version line. Keep the version bump to one line to make that
trivial.
