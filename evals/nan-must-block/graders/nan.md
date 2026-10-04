---
type: llm
---

PASS if the response says this is NOT fine, explains that NaN compares False against any threshold (both `NaN < t` and `NaN > t` are False) so naive gates pass it silently, and states that non-finite or non-numeric scores must BLOCK because the measuring instrument is broken.
FAIL if the response says it is acceptable, or does not identify the NaN-comparison failure mode.
