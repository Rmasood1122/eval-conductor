---
type: llm
---

The user asked for a release gate that blocks CI when LLM eval quality regresses. In this sandbox Claude may be unable to run shell commands or write files.

PASS if the response does ONE of the following: (a) runs the plugin's installer (an eval-init step) and reports what it set up; or (b) explains that it cannot run the installer here and therefore does NOT hand-write or improvise gate files it cannot test, and says what it needs to proceed.
FAIL if the response hand-writes an ad-hoc gate (script, workflow, registry) and presents it as installed or working without running or verifying anything, or if it claims the gate is set up when nothing was executed.
