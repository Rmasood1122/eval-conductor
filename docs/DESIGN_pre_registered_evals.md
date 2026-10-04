# Design — Pre-registered evals (100x #2)

Status: design. Pairs with the IE-06b registry diff-lint and the v1.2 eval receipts.
Target release: v1.3.0.

## The hole this closes

The diff-lint (`registry_diff_lint.py`) proves a registry **did not get weaker
than its git base**. It has one structural blind spot, stated in its own code:

```
if old_text is None:
    print("brand-new gate, nothing to weaken."); return 0
```

A brand-new gate has no base, so nothing to weaken. That is the opening for the
one attack the whole "verifiable evals" thesis exists to kill: **choosing the
bar after seeing the score.**

Concretely — p-hacking your own gate:

1. Run the candidate. Observe `task_success_rate = 0.87`.
2. Author `registry.yaml` with `threshold: 0.85` (candidate − ε).
3. Commit registry + candidate together. Gate goes green on the first push.
4. Diff-lint: "brand-new gate, nothing to weaken" → passes.
5. Receipt: faithfully records a PROMOTE under that registry → signs it.

Every existing control passes. The receipt even *proves* it passed — unaltered,
under that registry. But the registry was reverse-engineered from the result.
The number is real; the bar is fiction. No eval tool
(MLflow/LangSmith/Braintrust) catches this, because none of them treats "when
was the bar fixed, relative to the run?" as a question with an answer.

## What pre-registration proves (and what it cannot)

A **seal** is a small committed artifact that fixes the bar:

```
{
  "schema_version": "eval-seal/v1",
  "sealed_at": "2026-10-04T14:00:00Z",
  "registry_sha256": "<sha256 of registry.yaml bytes at seal time>",
  "bands": { "<metric>": {"source": "registry", "value": 0.02}, ... },   # optional
  "bands_sha256": "<sha256 of the canonical bands block>",               # optional
  "note": "pre-run commitment for release train 2026-10",
  "prev_seal_hash": "GENESIS",
  "seal_hash": "<sha256 of canonical body>",
  "signature": "<hmac — same key family as receipts>"                    # if keyed
}
```

Proven, in increasing strength:

1. **Content binding (crypto, unconditional).** At gate time the live
   `registry.yaml` is hashed and compared to `registry_sha256`. If one byte
   changed since sealing, the gate knows. No silent swap of the bar between
   seal and run.

2. **Candidate-independence (structural).** The seal contains **no candidate
   data** — only the bar. It cannot have been computed from scores it does not
   contain. (It *can* still be authored by someone who already peeked; that is
   what (3) addresses.)

3. **Ordering against the candidate (git-anchored, the real defence).** The
   seal is committed and pushed like a receipt. Its honest strength is not the
   `sealed_at` string — a key-holder can type any timestamp — but that the seal
   appears in git history, pushed to a remote a third party witnessed (GitHub,
   CI logs, a reviewer, every clone), in a commit that **precedes** the
   candidate's commit. "The bar was committed before the result existed"
   becomes a fact about shared git history, not the gate owner's word.

**What it does NOT prove — stated loudly, because overclaiming here is the exact
sin the thesis condemns:**

- Not that the bar is *correct* or *strict enough*. A pre-committed weak bar is
  still weak; pre-registration proves it was pre-committed, not that it was good.
  (Strictness is the diff-lint's and the reviewer's job.)
- Not, by cryptography alone, that `sealed_at` is truthful. A shared-secret
  HMAC lets the key-holder backdate. Ordering rests on **git anchoring**, not
  the timestamp — exactly the receipts' "distribution, not the key" stance.
- Not signer identity (shared-secret HMAC, same caveat as receipts).

This honest ceiling is the point: pre-registration converts "trust me, I didn't
move the goalposts" into "here is the goalpost I committed to, in a commit you
can see predates my result." That is a strictly smaller trust surface, and it is
the piece the diff-lint cannot supply on a new gate.

## Mechanism

### Seal (`prereg.py seal`)
- Hash `registry.yaml` bytes → `registry_sha256`.
- Optionally capture bands: for each registry metric, the band the gate would
  use **from the registry alone** (the `noise_band` floor), and, if a baseline
  exists, the measured band — sealing the *committed* band, so later baseline
  re-runs that widen a band post-hoc are caught. Bands block is canonicalized
  and hashed (`bands_sha256`).
- `prev_seal_hash` = head of the seal chain (reuse `chain_state.latest_receipt_hash`
  generalized, or a parallel seal-chain walk — seals chain exactly like
  receipts so a deleted/reordered seal breaks the chain).
- `seal_hash` = sha256 of canonical body; HMAC-sign if a key is present (reuse
  `eval_receipt.load_key_from` / `_sign` — one key family, not a second
  secret).
- Write to `evals/seals/<date>/<seal_id>.json`. Print an ANCHOR line telling the
  user to commit and push it — a local-only seal is a claim, not evidence
  (verbatim stance from receipts).

### Verify at gate (`prereg.py check`, and a hook in `promote.py`)
At gate time, given the live registry (and baseline):
1. Find the applicable seal = the latest seal on the chain. (A gate with no seal
   → the check reports "no pre-registration" and is a no-op on the exit code;
   pre-registration is opt-in, additive, never breaks an un-sealed gate.)
2. Recompute `registry_sha256` of the live registry; compare to the seal.
   Mismatch → **DRIFT**: the bar changed since it was sealed.
3. If bands were sealed, recompute and compare `bands_sha256`. Mismatch →
   **BAND DRIFT**.
4. Emit the result into the **receipt** (new `prereg` block on the receipt body:
   `{sealed: true/false, seal_id, registry_match: bool, bands_match: bool}`), so
   the receipt now records not just "passed under this registry" but "passed
   under the registry that was pre-committed in seal X". The two features
   compose: the receipt is the per-decision proof, the seal is the
   pre-commitment the decision honoured.

### Enforcement posture
Mirror the gate's existing fail-closed/side-effect split precisely:
- **Emission of the seal** and **recording prereg status on the receipt** are
  best-effort side effects — never change the gate exit code (same contract as
  receipt emission).
- **`prereg.py check` as a standalone CLI / CI step** is fail-closed: exit 2 on
  DRIFT when `--require-seal` is set. This is the knob a team turns on in CI to
  make pre-registration binding, the same way `--structure-only` vs keyed verify
  is a knob. Default without the flag: report drift loudly, exit 0 (opt-in
  enforcement, so we never break existing un-sealed users on upgrade).

This keeps one consistent rule across the product: **emission never blocks;
verification is where enforcement lives, and enforcement is a flag the team
opts into.**

## Why this scores on the 6-factor endorsement framework
1. **Mission alignment** — directly attacks result-driven goalpost-moving in
   evals; "honest evals, not-overclaiming" is the literal subject.
2. **Ecosystem gap-fit** — no eval tool records when-the-bar-was-fixed; it is a
   novel, nameable property ("pre-registered evals", borrowed from clinical-trial
   pre-registration, instantly legible to the ML-rigor audience).
3. **Form-factor fit** — ships inside the existing eval-conductor plugin; one
   new module, one command, one CI line. No rebuild.
4. **Credibility signal** — the design's strongest move is stating its own
   ceiling (can't beat a backdating key-holder by crypto; relies on git
   anchoring). That honesty is the differentiator, not a weakness.
5. **Defensibility** — composes with receipts (v1.2) and the diff-lint (IE-06b)
   into a three-part story none of the incumbents have: *the bar can't weaken
   (diff-lint), the bar was fixed before the result (pre-reg), and the decision
   is tamper-evident proof (receipt).*
6. **Ship-ability** — reuses `canonical.py`, `chain_state.py`, the key loader,
   the ANCHOR reporter. Net new surface is small.

## Non-goals / deliberately deferred
- No trusted timestamp authority / OpenTimestamps integration (would upgrade
  ordering from git-anchored to externally-witnessed — a clean future PR, named
  here so the limit is on record, not built now).
- No judging whether a sealed bar is *strict enough* (diff-lint + reviewer).
- Seal rotation / multi-train seals beyond "latest on the chain" — single active
  chain for v1.
