---
name: nan-must-block
description: A scorer returned NaN and the gate passed. The correct answer is that NaN must BLOCK because NaN compares False against every threshold.
max_turns: 4
allowed_tools: [Read, Skill]
---

Our faithfulness scorer crashed and wrote NaN for the score, but the release gate still passed and we deployed. Is that fine? The threshold check didn't fail, so it seems OK.
