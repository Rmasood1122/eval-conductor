---
description: Explain a gate decision in plain English — which metric failed, how far past the line, breach vs regression, the one legitimate fix, and the moves that are theater
argument-hint: "[--candidate PATH] [--baseline PATH] [--registry PATH]"
---

Explain the most recent gate decision in the user's repository:

```
python3 evals/tools/explain.py $ARGUMENTS
```

(If `evals/tools/explain.py` doesn't exist, the gate isn't installed or is an
older install — offer `/eval-init --force` to refresh the vendored tools.)

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
