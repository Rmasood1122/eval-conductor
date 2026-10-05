---
description: Explain a gate decision in plain English — which metric, breach vs regression, how far past the line, the legitimate fix, and the theater moves named
argument-hint: "[--candidate PATH] [--baseline PATH] [--registry PATH]"
---

Explain the most recent gate decision in the user's repository:

```
TOOL="evals/tools/explain.py"; [ -f "$TOOL" ] || TOOL="${CLAUDE_PLUGIN_ROOT}/core/explain.py"; python3 "$TOOL" $ARGUMENTS
```

(Runs from the installed plugin — no `/eval-init` needed. Explains the latest gate decision if one exists; prefers a vendored copy, else the plugin's own.)

This runs the SAME decision logic as `/eval-gate`, so it can never disagree
with the gate — it only adds the diagnosis. Relay it faithfully:

- For each non-PASS metric it states what the metric measures, whether this
  is an **absolute threshold breach** or a **regression beyond the measured
  noise band**, and how far past the line in the metric's own units.
- It names the one legitimate fix (find and repair the change that made the
  system worse; or, if the bar itself is wrong, a reviewed registry change
  with a justification in `evals/registry_changes.yaml`).
- It lists the theater moves by name: threshold edit, band widening, tier
  downgrade, metric deletion, baseline refresh while red. If the user asks
  for any of these, say plainly that it is on the list and why.
- On "can I refresh the baseline?": only after an INTENDED change has landed
  on main and been reviewed. Never because this run is red.

Use this when someone asks "why did it block?", "what do I do now?", or is
about to argue with the gate. Exit code mirrors the gate (0/1/2), so it can
replace `promote.py` in a CI step that wants the explanation in the log.
