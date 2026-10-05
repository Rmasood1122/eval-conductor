---
description: Verify the eval receipt chain — every PROMOTE/BLOCK is signed, unaltered, chained, and its decision matches its own verdicts
argument-hint: "[--receipts-dir DIR] [--registry PATH] [--structure-only]"
---

Verify the tamper-evident eval receipt log in the user's repository:

```
TOOL="evals/tools/eval_receipt.py"; [ -f "$TOOL" ] || TOOL="${CLAUDE_PLUGIN_ROOT}/core/eval_receipt.py"; python3 "$TOOL" verify $ARGUMENTS
```

(Runs from the installed plugin — no `/eval-init` needed. Verifies whatever receipts exist under `evals/receipts/` (e.g. from `/eval-prove`); says so if none do.)

Interpret the result honestly:

- **Exit 0** — the chain is intact: one unbroken line from GENESIS, every
  `receipt_hash` recomputed from content, every signature valid under the key,
  and every recorded decision matches its own verdicts. Read back the `ANCHOR`
  line: receipts that verify but are not committed-and-pushed are a claim, not
  evidence.
- **Exit 1** — a hard failure. Report exactly which: `CHAIN FAIL` (a receipt was
  altered, deleted, reordered, or the chain forked), `SIG FAIL` (a signature
  doesn't match the key), or `DECISION FAIL` (a receipt's recorded
  PROMOTE/BLOCK disagrees with its own verdict table). NEVER "fix" this by
  re-signing, deleting the offending receipt, or regenerating the chain — a
  verify failure is evidence of tampering or corruption and must be
  investigated, not papered over.
- **Exit 2** — no key available (signatures not checked) or no receipts to
  verify. Supply the key out-of-band (`--receipt-key`, or the `EVAL_RECEIPT_KEY`
  secret in CI), or run `--structure-only` to check chain + content hashes
  without it (it will say signatures were not checked).

The key is a shared secret: a passing verify proves the decisions are unaltered
since signing under a key the team controls — it does not identify who signed.
