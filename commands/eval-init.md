---
description: Install a fail-closed eval release gate (registry, gate CLI, baseline runner, CI workflow) into the current repository
argument-hint: "[--force] [--conductor --project NAME --archetype A1..A5]"
allowed-tools: ["Bash", "Read", "Edit", "Write", "Glob", "Grep"]
---

Install the eval gate into the user's current repository.

1. Run the scaffolder, passing through any arguments the user gave:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/eval_init.py" $ARGUMENTS
```

If it fails because PyYAML is missing, install it (`pip install pyyaml` — add
`--break-system-packages` if pip refuses) and retry once.

2. The scaffolder never overwrites existing files without `--force`. If it
   skipped files the user expected to refresh, tell them and ask before using
   `--force`.

3. After a successful install, do NOT stop at the file list. Open the repo and
   make the gate real:
   - Read the user's project (tests, eval scripts, CI) and EDIT
     `evals/registry.yaml` to metrics this repository can actually produce —
     delete starter rows that don't apply. Keep the comments.
   - Identify or create the command that writes `evals/candidate.json`
     matching `evals/candidate.example.json` (a thin adapter over their
     existing test/eval output is usually enough — include the `manifest`
     block with real dataset/registry hashes).
   - Fill the "Produce candidate" step in `.github/workflows/eval-gate.yml`
     with that command.

4. Then follow the eval-gates skill in this plugin: run the gate once
   threshold-only, build the baseline with 3+ runs, and write per-hard-metric
   BLOCK fixtures. The install is not done until the gate has been SEEN to
   BLOCK on a fixture and PROMOTE on a healthy run.

Never edit a threshold to turn a red gate green — if a threshold is wrong,
change it in a reviewed commit that says why.
