---
description: Convert scores you already produce — JUnit XML, `claude plugin eval` results, promptfoo output, or a flat JSON of numbers — into evals/candidate.json for the gate
argument-hint: "junit <report.xml> | plugin-eval <evals/results/ or aggregate-result.json> | promptfoo <out.json> | scores <file.json> [--out PATH]"
---

Turn existing eval output into a gateable candidate:

```
TOOL="evals/tools/adapters.py"; [ -f "$TOOL" ] || TOOL="${CLAUDE_PLUGIN_ROOT}/core/adapters.py"; python3 "$TOOL" $ARGUMENTS
```

(Runs from the installed plugin — no `/eval-init` needed. Prefers a vendored `evals/tools/adapters.py` if present, else the plugin's own copy.)

Which adapter:

- **junit** — any pytest/jest/go-test run with `--junitxml`. Emits
  `test_pass_rate`, `test_count`, `test_failures`. Zero executed tests scores
  0.0, so a broken test run BLOCKs instead of passing.
- **plugin-eval** — `claude plugin eval` output. Point it at `evals/results/`
  (latest run is picked) or a specific `aggregate-result.json`. Emits the
  overall score, the mean with-vs-without **delta**, the weakest case's score
  and delta, and cases passed/total. A `partial: true` result is refused
  (exit 2): a run cut short by the cost ceiling or an auth failure gates
  nothing — say so, don't score it.
- **promptfoo** — `promptfoo eval -o out.json`. Emits pass rate, total, failures.
- **scores** — a flat `{"metric": number}` file from any tool. Non-numbers
  are refused.

After writing, run `/eval-gate`. If the registry has no rows for the metrics
the adapter emitted, help the user add them (names are printed) — do not
quietly drop the metrics, and do not invent thresholds: a threshold is a
decision the user makes and commits with a reason.
