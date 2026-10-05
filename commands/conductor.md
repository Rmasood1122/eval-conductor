---
description: Evidence-gated 27-step build ledger — init, status, check off steps with CI evidence, audit; refuses placeholder proof and step-skipping
argument-hint: "init --project NAME --archetype A1..A5 | status | next | guide | check --evidence URL | defer N --trigger ... | na N --justify ... | reopen N | audit"
---

Operate the conductor — the 27-step eval build method as an enforcing CLI.
State lives in `evals/conductor_state.json` and is committed like code.

```
TOOL="evals/tools/conductor.py"; [ -f "$TOOL" ] || TOOL="${CLAUDE_PLUGIN_ROOT}/core/conductor.py"; python3 "$TOOL" $ARGUMENTS
```

(Runs from the installed plugin. `conductor init` (or `/eval-init --conductor --project NAME --archetype A2`) creates the ledger state in `evals/conductor_state.json` if it doesn't exist yet.)

Doctrine the CLI enforces — explain, don't work around:

- **D1 week-one integrity**: steps 1–6 (plus archetype promotions) close
  before any later step can.
- **D2 evidence or it didn't happen**: `check` requires evidence; CI-kind
  steps require a real `https://github.com/<org>/<repo>/actions/runs/<id>`
  URL — placeholders, pasted command text, and angle-bracket tokens are
  refused by design. Get the real run URL from the repo's Actions API or
  page, never fabricate one.
- **D6 disposition, never omission**: all 27 rows always exist; `defer`
  needs `--trigger`, `na` needs `--justify`; T05 and T27 can never be N/A.
- **Reversals are recorded**: `reopen` voids evidence and logs it. Caught
  fakes stay in the ledger — the audit trail is the feature, do not offer to
  clean it.

`audit` exits 1 on any violation — wire it into CI as a release-blocking
step. When the user asks "what's next", run `next` and relay its exit
criteria verbatim rather than paraphrasing them softer.
