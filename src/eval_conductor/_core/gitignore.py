"""Keep the plugin's local-only files out of git.

Shared by /eval-init and /eval-prove: both write a signing key and other
per-machine state into the user's repository, and `git add -A` must never stage
the key. Receipts and seals are deliberately NOT ignored — committing and pushing
them is what anchors them.
"""
from __future__ import annotations

from pathlib import Path

# Where the tools write local-only state, relative to the repo root.
LOCAL_ARTIFACTS = ("evals/.receipt-key", "evals/.wedge-baseline.json",
                   ".eval-prove-junit.xml")


def ensure_gitignore(repo: Path, lines) -> None:
    """Append each line not already in repo/.gitignore. Idempotent."""
    gi = Path(repo) / ".gitignore"
    text = gi.read_text() if gi.exists() else ""
    existing = set(text.splitlines())
    add = [ln for ln in lines if ln not in existing]
    if not add:
        return
    body = (text.rstrip("\n") + "\n" if text else "") + "\n".join(add) + "\n"
    gi.write_text(body)
    for ln in add:
        print(f"  gitignore: added {ln}")
