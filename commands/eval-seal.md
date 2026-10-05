---
description: Pre-register the eval bar — seal the registry (and band floors) BEFORE a run, so a later decision can prove it was judged under a bar committed to in advance
argument-hint: "[--registry PATH] [--seals-dir DIR] [--note TEXT] [--no-bands]"
---

Seal the current eval bar in the user's repository, as a pre-registration:

```
TOOL="evals/tools/prereg.py"; [ -f "$TOOL" ] || TOOL="${CLAUDE_PLUGIN_ROOT}/core/prereg.py"; python3 "$TOOL" seal $ARGUMENTS
```

(Runs from the installed plugin, but sealing needs a registry: if `evals/registry.yaml` doesn't exist yet, run `/eval-init` first, then re-run this.)

What this does and why it matters:

- A seal hashes `evals/registry.yaml` (and, unless `--no-bands`, each metric's
  `noise_band` floor) and writes a signed, hash-chained record under
  `evals/seals/`. It contains **no candidate data** — only the bar.
- The diff-lint proves the registry didn't get *weaker than its git base*. It
  cannot judge a **brand-new** gate, which is the opening for the one move the
  whole tool exists to stop: authoring a bar to clear a score you already ran
  (p-hacking your own gate). The seal closes that — at gate time the live
  registry is re-hashed against the seal, so a bar that moved after sealing is
  caught.

**Order matters — this is the entire point:**

1. Run `/eval-seal` to commit to the bar.
2. **Commit and push the seal** (`evals/seals/`). A local-only seal is a claim,
   not evidence — its strength is appearing in pushed git history, witnessed by
   the remote, in a commit that *precedes* your candidate. Read back the
   `ANCHOR` line the command prints.
3. THEN produce the candidate and run the gate.

Never seal *after* seeing the candidate's scores — a seal written to fit a
result it was built around proves nothing. If the bar legitimately needs to
change, seal again **before** re-running the candidate, and say why in
`evals/registry_changes.yaml` (the diff-lint still applies).

Honest limits (state them; do not oversell):

- The seal proves the bar is byte-identical to what was sealed, and — via git
  anchoring — that it was committed before the result. It does **not** prove the
  bar is strict *enough* (that's the diff-lint's and the reviewer's job), and a
  shared-secret key cannot stop its own holder backdating the `sealed_at` string
  — which is why ordering rests on pushed history, not the timestamp.

To enforce in CI, add the drift check as a release-blocking step:

```
TOOL="evals/tools/prereg.py"; [ -f "$TOOL" ] || TOOL="${CLAUDE_PLUGIN_ROOT}/core/prereg.py"; python3 "$TOOL" check --require-seal
```
