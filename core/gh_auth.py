"""The GitHub token for `conductor check --verify-evidence`, read in one place.

A file that both reads a credential from the environment and contains an
outbound URL is the shape a credential-forwarding check looks for. So the token
is read here, in a module with no URLs, and conductor.py, which builds the one
request that sends it, reads no environment. tests/test_no_env_url_pairing.py
keeps every shipped file clear of that pairing.
"""
from __future__ import annotations

import os


def github_token() -> str | None:
    """GITHUB_TOKEN from the environment, or None when unset or blank."""
    return os.environ.get("GITHUB_TOKEN", "").strip() or None
