---
description: Run the eval release gate — candidate vs baseline under the registry, PROMOTE or BLOCK with a per-metric verdict table
argument-hint: "[--candidate PATH] [--baseline PATH] [--registry PATH]"
---

Run the release gate in the user's repository:

```
TOOL="evals/tools/promote.py"; [ -f "$TOOL" ] || TOOL="${CLAUDE_PLUGIN_ROOT}/core/promote.py"; python3 "$TOOL" $ARGUMENTS
```

(Runs from the installed plugin, but the gate needs a registry: if `evals/registry.yaml` doesn't exist yet, run `/eval-init` first to create one, then re-run this.)

Interpret the result for the user honestly:

- **Exit 0 (PROMOTE)** — report it plainly. If the output shows WARNs, list
  them: soft-metric warnings require a human decision, not a shrug.
- **Exit 1 (BLOCK)** — show WHICH metric blocked and why (threshold breach vs
  regression-beyond-band vs non-finite score vs stale baseline). Then help
  diagnose the underlying change. NEVER "fix" a block by raising the
  threshold, widening the noise band, downgrading `hard` to `soft`, or
  deleting the metric — if the user asks for that, tell them that decision
  needs a reviewed commit with a written justification, and say what evidence
  would justify it.
- **Exit 2 (bad input)** — the candidate/registry/baseline is malformed or
  missing; fix the input, don't bypass the gate.

If there is no baseline yet, the gate runs threshold-only and says so —
recommend `/eval-baseline` before trusting regression detection.
