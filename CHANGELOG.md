# Changelog

## 1.4.1 — 2026-10-05

Wedge hardening + an honest-limits correction, from deep adversarial testing. The
core gate was unaffected (NaN/Inf/string/bool scores, missing metrics, seal
p-hacking and receipt tampering all already BLOCK/caught); every fix below is in
the zero-config wedge path or its docs.

- **Deleting `evals/.wedge-baseline.json` no longer resets the bar.** The bar is
  reconstructed from the signed, hash-chained receipts (prior PROMOTE
  `manifest.scores`) when the local file is missing, so it can't be deleted to
  launder a regression into a "first run". Pin a lower floor deliberately with
  `--min-pass-rate`.
- **Zero collected tests → CANNOT PROVE (exit 2)**, instead of a brightgreen
  "PROVEN 0/0" badge. The scorer's "0.0 not 1.0" contract is unchanged.
- **Corrected a receipt overclaim.** "Delete or reorder a receipt and the chain
  breaks" is true for tamper/reorder/middle-deletion; removing the *latest*
  receipt leaves a shorter valid chain, caught by distribution (push) — which the
  code already enforces via the ANCHOR report. Docs now say exactly that.
- **Malformed candidate/baseline JSON → clean FAIL (exit 2)**, not a raw
  traceback.
- Tests: 254 passing (added baseline-deletion, zero-tests, and `--min-pass-rate`
  cases).

## 1.4.0 — 2026-10-04

Zero-config wedge: `/eval-prove` — one command, a signed proof of your tests.

- **`/eval-prove` (`core/wedge.py`, vendored into your repo)** turns an existing
  test suite into a tamper-evident, signed receipt **plus a pasteable PR badge**,
  with **no registry and no config**. Detects and runs pytest, or consumes a
  JUnit file (`--junit`) or any command that writes JUnit (`--run`).
- **Proof + auto-gate (capture-then-gate).** The first run has nothing to regress
  against, so it PROMOTEs and records the measured pass-rate and test-count as the
  bar (`evals/.wedge-baseline.json`). Later runs BLOCK if the pass-rate drops or
  tests disappear (the oldest way to turn a gate green). The bar ratchets up on a
  clean run and never down — a BLOCK never lowers it. A hardcoded "100% or BLOCK"
  was rejected: it would fail every flaky suite on run one.
- **Same proof engine as the full gate.** Receipts come from `eval_receipt`, so a
  wedge proof and a gate proof verify identically; a signing key is auto-generated
  (gitignored) on first run, so proofs are signed by default.
- **Fail-closed.** No detectable suite and no `--junit`/`--run` → exit 2 (no proof
  of an unmeasured run), with a one-line pointer, never a traceback. Zero executed
  tests → pass-rate 0.0.
- **Honest badge.** The badge always shows the test COUNT, and the output states
  that a green badge proves "not worse than before", not "good", and that one run
  doesn't calibrate flakiness — graduate to `/eval-init` for measured noise bands
  and real thresholds. The wedge is the on-ramp; `/eval-init` is the next room.
- 12 new tests (`tests/test_wedge.py`); vendored by `/eval-init`; wedge artifacts
  gitignored in the user repo. Dogfooded: proves eval-conductor's own 166 tests.
## 1.3.0 — 2026-10-04

Pre-registered evals: prove the bar was fixed *before* the run.

- **Pre-registration seals** (`core/prereg.py`, vendored into your repo;
  `/eval-seal`). `prereg.py seal` hashes `evals/registry.yaml` (and each metric's
  `noise_band` floor) into a signed, hash-chained seal under `evals/seals/`,
  containing **no candidate data**. At gate time the live registry is re-hashed
  against the seal; a bar that moved after sealing is flagged as drift.
- **Closes the hole the diff-lint structurally cannot.** `registry_diff_lint.py`
  proves a registry didn't get weaker than its git base — but a *brand-new* gate
  has no base ("nothing to weaken"), so a gate authored to exactly clear a score
  you already ran passes every check. That is p-hacking your own gate.
  Pre-registration is the deliberate, anchored base that makes "the bar was fixed
  before the result" a checkable fact.
- **Composes with receipts.** The gate records a `prereg` block on each receipt
  (`sealed`, `seal_id`, `registry_match`, `bands_match`, `signature_ok`), so a
  signed PROMOTE now proves not just "passed under this registry" but "passed
  under the registry that was pre-committed in seal X" — and a drifted decision
  is permanently stamped as such, inside the tamper-evident receipt itself.
- **Opt-in enforcement, never breaks an un-sealed gate.** Recording status on
  the receipt is a best-effort side effect that never changes the gate exit code.
  `prereg.py check --require-seal` is the fail-closed CI knob (exit 2 on drift or
  a missing seal); without the flag, drift is reported loudly and exits 0, so
  upgrading is non-breaking.
- **CI**: `templates/eval-gate.yml` gains a commented pre-registration check
  step. Native eval case `prereg-reseal-refuses` proves the assistant refuses to
  re-seal a weakened bar after seeing the scores (the exact laundering move).
- Honest limits carried in the README, `/eval-seal` and the seal output: a seal
  proves the bar is byte-identical to what was sealed and — via git anchoring —
  committed before the result; it does **not** prove the bar is strict *enough*
  (that's the diff-lint's and the reviewer's job), and a shared-secret key can't
  stop its own holder backdating the `sealed_at` string — so ordering rests on
  pushed git history, not the timestamp.

## 1.2.0 — 2026-10-04

Eval receipts: a provable verdict, not just an exit code.

- **Tamper-evident eval receipts** (`core/eval_receipt.py`, vendored into your
  repo; `/eval-verify`). Once a signing key exists (`/eval-init` now generates
  one, gitignored), every `/eval-gate` run appends an HMAC-signed, hash-chained
  receipt to `evals/receipts/` binding the PROMOTE/BLOCK decision to the exact
  registry, candidate and baseline **bytes** it was computed from. A deleted or
  reordered receipt breaks the chain.
- **Fused from titan-receipts.** The canonicalization (`core/canonical.py`) and
  fork-detecting chain engine (`core/chain_state.py`) are ported from the
  titan-gate plugin — stdlib-only, byte-compatible — rather than reinvented or
  taken as a runtime dependency.
- **Three verify-time tamper checks**: chain integrity (one unbroken line from
  GENESIS, every `receipt_hash` recomputed from content), signature, and an
  eval-specific **decision-vs-verdicts consistency** check — a re-signed receipt
  whose recorded decision disagrees with its own verdict table is caught.
  `--structure-only` verifies without the key; the closing `ANCHOR` line reports
  how many receipts are committed **and pushed**.
- **Fail-open emission.** Receipting is a side effect that never changes the
  gate's exit code or crashes CI: a broken chain or unwritable path warns
  (`RECEIPT:`) and skips. Enforcement lives in `/eval-verify`, not the gate.
- **CI**: `templates/eval-gate.yml` gains a commented `EVAL_RECEIPT_KEY` secret
  and a release-blocking verify step. Native eval case `receipt-tamper-blocks`
  proves the assistant treats a verify failure as blocking, never "re-sign it".
- Honest limits carried in the README and verify output: HMAC is a shared
  secret — a receipt proves the decision is unaltered under a key you control,
  not who signed it, and not that the scores were honestly produced.

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
