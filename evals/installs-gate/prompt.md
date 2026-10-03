---
name: installs-gate
description: Natural-language request to add a release gate for LLM evals should trigger the plugin's /eval-init path rather than hand-rolled scripts.
max_turns: 8
allowed_tools: [Read, Glob, Grep, Bash, Skill]
---

I want a release gate for my LLM evals in this repo so CI blocks when quality regresses. Set that up.
