"""Canonical serialization for eval receipts — the ONE definition.

Ported from the titan-gate plugin (core/canonical.py), whose hash-chained,
offline-verifiable receipt engine eval receipts are fused from. Kept
byte-compatible with that engine on purpose: the same canonicalization means a
receipt written here hashes identically everywhere, and the writer and verifier
below share this one module so they can never drift (the classic
duplicated-canonicalizer bug).

TRS-1 semantics: sorted-keys compact JSON, UTF-8, with signature-adjacent
fields excluded from the signed/hashed body. Eval receipts carry floats
(scores, bands, thresholds), so they use this float-safe path — never the JCS
path, which admits only integers.
"""
import json
from typing import Any, Dict

EXCLUSION_FIELDS = {"signature", "receipt_hash", "prev_receipt_hash_verified",
                    "_debug", "_meta"}


def canonical_bytes(receipt: Dict[str, Any]) -> bytes:
    filtered = {k: v for k, v in receipt.items() if k not in EXCLUSION_FIELDS}
    return json.dumps(
        filtered, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
