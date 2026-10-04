---
description: Install a fail-closed eval release gate into the current repo — auto-detects pytest or a Claude Code plugin and gates real numbers on the first push
argument-hint: "[--profile auto|pytest|plugin-eval|llm] [--force] [--conductor --project NAME --archetype A1..A5]"
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

3. Read the profile it chose and act on it:

   - **pytest** — the gate already has real metrics (test pass rate, a floor
     on test count, failures). Run the two commands in NEXT STEPS so the user
     sees their first real verdict now. Then ask what the system's eval
     metrics are and help add rows + a producer for them.
   - **plugin-eval** — the repo is a Claude Code plugin. If `evals/` has no
     cases yet, offer `claude plugin eval init`. Remind them the CI step needs
     `ANTHROPIC_API_KEY` as a secret and caps cost with `--max-cost-usd`.
   - **llm** — nothing to measure was detected. Do NOT stop at the file list:
     read the user's project (tests, eval scripts, CI) and EDIT
     `evals/registry.yaml` to metrics this repository can actually produce —
     delete starter rows that don't apply, keep the comments. Identify or
     create the command that writes `evals/candidate.json` (an adapter over
     their existing output is usually enough — `/eval-import`). Fill the
     "Produce candidate" step in `.github/workflows/eval-gate.yml`.

4. Then follow the eval-gates skill in this plugin: run the gate once
   threshold-only, build the baseline with 3+ runs, and write per-hard-metric
   BLOCK fixtures. The install is not done until the gate has been SEEN to
   BLOCK on a fixture and PROMOTE on a healthy run.

Never edit a threshold to turn a red gate green — if a threshold is wrong,
change it in a reviewed commit that says why.
