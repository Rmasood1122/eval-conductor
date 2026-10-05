# Security posture

Eval Conductor is a release-gate and proof tool. Its value is that you can trust
what it says, so its own attack surface is kept deliberately small. Every claim
below is enforced by the readiness battery in `tests/test_directory_readiness.py`,
which runs in CI.

## No auto-executing components
The plugin ships **commands and skills only**. It declares no hooks, no MCP
servers, no monitors, no LSP servers, and no `bin/` directory. Nothing runs
automatically: every tool executes only when you invoke a command, and Claude
runs it through the normal Bash tool where you see it.

## Network
The plugin makes **one** outbound call, and only when you explicitly run
`/conductor --verify-evidence`: a GET to the GitHub API (`api.github.com`) to
confirm that a CI run you cited is real and green. Anonymous access works for
public repos; a token is used only if you provide one. There is no telemetry, no
analytics, and no other network access. The `shields.io` badge URL that
`/eval-prove` prints is plain text for you to paste — the plugin never fetches it.

## Credentials
- The eval **signing key** is an HMAC key you control. `/eval-init` generates one
  locally and git-ignores it (`evals/.receipt-key`); it is never transmitted and
  no secret value is ever printed or logged. You may instead declare it (or a
  GitHub token) as a **sensitive `userConfig`** value, stored in Claude Code's
  secure credential store. In CI, both come from standard repository secrets
  (`EVAL_RECEIPT_KEY`, `GITHUB_TOKEN`).
- No credentials are committed to this repository. The only key-shaped strings in
  the source are obviously-fake repeated-byte test fixtures (e.g. `ab…ab`).

## Running your commands
`/eval-prove --run` and `/eval-baseline --cmd` execute a shell command **you pass
explicitly** (your test/build command). That string is never built from network
input, file contents, or any untrusted source — the same trust level as a
Makefile target you run yourself. Both calls are bounded by a timeout.

## File writes
The tools write only inside your repository: eval receipts and seals under
`evals/`, a candidate/baseline JSON, and the git-ignored key file. Nothing is
written to your home directory, `/etc`, `/tmp`, or any absolute path, and
`/eval-init` never overwrites an existing file without `--force`.

## Data handling
The plugin reads your test/eval output and your repository files. It collects no
personal data and sends none anywhere. See [PRIVACY.md](PRIVACY.md).

## Reporting
Please report security concerns via
[GitHub issues](https://github.com/Rmasood1122/eval-conductor/issues).
