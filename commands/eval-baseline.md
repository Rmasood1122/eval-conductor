---
description: Evals flaky, or a real regression? Run your eval several times and measure each metric's noise band, so the gate blocks real drops and lets ordinary noise through
argument-hint: "--cmd \"<eval command>\" [--runs 3] | --from \"evals/runs/*.json\""
---

Build the baseline the gate compares against:

```
TOOL="evals/tools/baseline.py"; [ -f "$TOOL" ] || TOOL="${CLAUDE_PLUGIN_ROOT}/core/baseline.py"; sh "${CLAUDE_PLUGIN_ROOT}/core/py.sh" "$TOOL" $ARGUMENTS
```

Rules to hold the user to (they exist because shortcuts here produce fake
confidence):

- The eval command must be the SAME one CI runs — a baseline from a different
  pipeline gates nothing.
- 3 runs minimum; the runner refuses fewer than 2 without `--allow-single`,
  and a single-run baseline has zero-width bands, so ordinary noise will
  BLOCK. Say so before anyone uses that flag.
- Baselines are rebuilt on main after INTENDED changes land — never rebuilt
  to make a failing candidate pass. If someone wants to "refresh the
  baseline" while the gate is red, that's the threshold-editing move wearing
  a different hat; stop and say so.
- After writing the baseline, run `/eval-gate` once: current main must
  PROMOTE against its own baseline. If it doesn't, the eval is nondeterministic
  beyond its declared bands — widen bands from more runs (data), don't guess.
