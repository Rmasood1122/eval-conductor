---
name: evidence-discipline
description: Run evidence-gated project execution with the 27-step conductor ledger — closing steps only on verifiable CI proof, recording reversals, and recognizing fake-evidence patterns in your own work
---

# Evidence discipline (the conductor method)

Use this skill when the user works with the conductor ledger, asks how to
prove progress, or when YOU are about to claim a step of work is done.

## Why it exists

The ledger's design assumption is that the most likely source of fake
evidence is the person (or model) doing the work, under schedule pressure —
not an attacker. During its own development this system closed steps on a
literal `<PASTE-REAL-RUN-ID>` placeholder and on pasted command text, twice,
before the evidence check was hardened. Every caught fake is preserved in
the committed state log as a caught-and-voided entry. **The audit trail is
the feature.** Never offer to clean, squash, or rewrite it.

## Operating rules

- A step closes with `check --evidence <proof>`. For CI-kind steps, proof is
  a real `https://github.com/<org>/<repo>/actions/runs/<id>` URL. Obtain it
  programmatically (Actions API or page) AFTER the run finishes green.
  Never construct the URL from memory, never paste the command that WOULD
  produce evidence as if it were evidence.
- If the run is red, the step stays open. Report the failure; don't shop
  for an older green run of different code — evidence must match the work
  it claims to prove.
- Deferrals need a written trigger ("fires when ..."); N/A needs an
  architectural justification. T05 (instrument governance) and T27 (audit
  the eval system itself) can never be N/A.
- Mistakes are handled with `reopen`, which voids the evidence and logs the
  reversal. That log entry is not embarrassing; it is the point.
- `audit` runs in CI, release-blocking. A ledger that only the author reads
  is a diary, not a control.

## For Claude specifically

When you complete work tracked by a ledger: run the verification, capture
the real evidence, and only then check the step. If you cannot obtain real
evidence (network down, CI not finished), say exactly that and leave the
step open — an honest open step costs a little time; a fake closed one
costs the whole ledger's credibility. These rules apply to any
evidence-tracked workflow, not only this plugin's files.
