"""Eval receipts — a tamper-evident, hash-chained, signed proof of every gate
decision.

Fuses the titan-gate receipt engine (canonical.py + chain_state.py, ported
alongside this file) into eval-conductor's promote gate. Each PROMOTE/BLOCK
appends a receipt that binds the decision to the exact registry, candidate and
baseline BYTES it was computed from, HMAC-signs it, and links it into an
append-only chain. "It passed" becomes cryptographic proof it passed,
unaltered, at this time, under this registry — and a deleted or reordered BLOCK
breaks the chain.

Design contract:
  - Emission is a best-effort SIDE EFFECT. It never raises to the gate and never
    changes the gate's exit code: a receipt bug cannot turn a BLOCK into a
    PROMOTE or crash CI. Enforcement lives in `verify`, run by auditors/CI —
    exactly as titan's `create` never breaks a commit and `verify` is the gate.
  - HMAC is a shared secret: a receipt proves the decision is unaltered since
    signing under a key your team controls; it does not identify the signer.

Usage:
  python3 eval_receipt.py init     [--receipt-key PATH]
  python3 eval_receipt.py verify   [--receipts-dir DIR] [--receipt-key PATH]
                                   [--registry PATH] [--structure-only]

Exit codes (verify): 0 ok · 1 chain/signature/decision failure · 2 usage/no-key.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import secrets
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical import canonical_bytes                                   # noqa: E402
from chain_state import (                                               # noqa: E402
    GENESIS, ChainStateError, latest_receipt_hash,
)

SCHEMA = "eval-receipt/v1"
SIGNING = "hmac-sha256-v1"
DEFAULT_RECEIPTS_DIR = "evals/receipts"
DEFAULT_KEY_PATH = "evals/.receipt-key"
KEY_ENV = "EVAL_RECEIPT_KEY"
MIN_KEY_BYTES = 16


# ------------------------------------------------------------------ keys
def make_key() -> str:
    """A fresh 32-byte signing key as hex."""
    return secrets.token_hex(32)


def _validate_key(raw: str) -> bytes | None:
    try:
        key = bytes.fromhex(raw.strip())
    except ValueError:
        return None
    if len(key) < MIN_KEY_BYTES:
        return None
    return key


def load_key_file(path) -> bytes | None:
    """Read and validate a hex key file. A corrupt or too-short key signs
    nothing — an empty key would HMAC 'successfully' and prove nothing."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return _validate_key(p.read_text())
    except OSError:
        return None


def load_key_from(key_path: str | None = DEFAULT_KEY_PATH) -> bytes | None:
    """Resolution order: env EVAL_RECEIPT_KEY (the CI path, mirrors titan's
    secrets.TITAN_KEY), then the key file. Returns None when no usable key —
    callers then write unsigned (structure-only) receipts or none."""
    env = os.environ.get(KEY_ENV)
    if env:
        k = _validate_key(env)
        if k is not None:
            return k
        print(f"RECEIPT: {KEY_ENV} is not a valid hex key (>= {MIN_KEY_BYTES} "
              f"bytes) — ignoring it", file=sys.stderr)
    if key_path:
        return load_key_file(key_path)
    return None


def _sign(key: bytes, receipt_hash: str) -> str:
    return hmac.new(key, receipt_hash.encode(), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ body
def _sha256_file(path) -> str | None:
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(65536), b""):
            h.update(blk)
    return h.hexdigest()


def _num(x):
    """Non-finite floats (a missing metric -> NaN, a broken instrument -> inf)
    become string sentinels so receipts stay valid, portable JSON and
    canonicalize deterministically, without losing the information."""
    if x is None or isinstance(x, str):
        return x
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return x
    if math.isnan(xf):
        return "NaN"
    if math.isinf(xf):
        return "Infinity" if xf > 0 else "-Infinity"
    return xf


def _verdict_dict(v) -> dict:
    g = v.get if isinstance(v, dict) else (lambda k, d=None: getattr(v, k, d))
    return {
        "metric": g("metric"),
        "blocking": g("blocking"),
        "candidate": _num(g("candidate")),
        "baseline_mean": _num(g("baseline_mean")),
        "threshold": _num(g("threshold")),
        "band": _num(g("band")),
        "status": g("status"),
        "reason": g("reason"),
    }


def _decision_from_verdicts(verdicts: list) -> str:
    return "BLOCK" if any((v.get("status") if isinstance(v, dict) else getattr(v, "status", None))
                          == "BLOCK" for v in verdicts) else "PROMOTE"


def _commit_info() -> dict | None:
    """Best-effort {sha, branch} for the current repo; None outside git."""
    def g(*a):
        r = subprocess.run(["git", *a], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError
        return r.stdout.strip()
    try:
        return {"sha": g("rev-parse", "HEAD"),
                "branch": g("rev-parse", "--abbrev-ref", "HEAD")}
    except (RuntimeError, OSError):
        return None


def build_receipt(decision, verdicts, *, registry_path, candidate_path,
                  baseline_path=None, manifest=None, repo=None, prev=GENESIS,
                  key=None, prereg=None) -> dict:
    now = datetime.now(timezone.utc)
    body = {
        "schema_version": SCHEMA,
        "signing_version": SIGNING if key is not None else "unsigned",
        "receipt_id": str(uuid.uuid4()),
        "evaluated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root_date": now.strftime("%Y-%m-%d"),
        "repo": repo or "",
        "decision": decision,
        "inputs": {
            "registry_path": str(registry_path),
            "registry_sha256": _sha256_file(registry_path),
            "candidate_path": str(candidate_path),
            "candidate_sha256": _sha256_file(candidate_path),
            "baseline_path": str(baseline_path) if baseline_path else None,
            "baseline_sha256": _sha256_file(baseline_path),
        },
        "manifest": manifest or {},
        "verdicts": [_verdict_dict(v) for v in verdicts],
        "commit": _commit_info(),
        "prev_receipt_hash": prev,
    }
    # Pre-registration status (v1.3): added to the HASHED body only when present,
    # so a decision records that it was (or was NOT) judged under a pre-committed
    # bar. Omitted entirely when no seal applies, keeping pre-receipt receipts
    # byte-identical.
    if prereg is not None:
        body["prereg"] = prereg
    body["receipt_hash"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    if key is not None:
        body["signature"] = _sign(key, body["receipt_hash"])
    return body


def emit(decision, verdicts, *, registry_path, candidate_path,
         baseline_path=None, manifest=None, receipts_dir, key,
         prereg=None) -> Path | None:
    """Append a signed (or unsigned, if key is None) receipt for one decision.

    Best-effort: on ANY failure it warns to stderr and returns None, never
    raising to the gate. A broken/forked chain is NOT laundered — emission
    refuses and says so; `verify` is where that becomes a hard failure."""
    try:
        receipts_dir = Path(receipts_dir)
        prev = latest_receipt_hash(receipts_dir)
        receipt = build_receipt(
            decision, verdicts, registry_path=registry_path,
            candidate_path=candidate_path, baseline_path=baseline_path,
            manifest=manifest, repo=Path.cwd().name, prev=prev, key=key,
            prereg=prereg)
        out = receipts_dir / receipt["root_date"] / f"{receipt['receipt_id']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(receipt, indent=2) + "\n")
        return out
    except ChainStateError as exc:
        print(f"RECEIPT: refusing to extend a broken chain — decision NOT "
              f"receipted ({exc}). Run /eval-verify and repair before trusting "
              f"the receipt log.", file=sys.stderr)
        return None
    except Exception as exc:  # noqa: BLE001 - receipting must never break the gate
        print(f"RECEIPT: decision NOT receipted ({type(exc).__name__}: {exc}).",
              file=sys.stderr)
        return None


# ------------------------------------------------------------------ anchor
def _anchor_status(receipts_dir: Path) -> dict:
    """How much of receipts_dir exists outside this working tree. HMAC is a
    shared secret, so the only defence against a key-holder rewrite is
    DISTRIBUTION: once receipts are committed and pushed, every clone holds an
    independent copy. Never raises."""
    out = {"total": 0, "untracked": 0, "modified": 0, "unpushed": None,
           "upstream": None}
    try:
        files = list(receipts_dir.rglob("*.json"))
        out["total"] = len(files)
        if not files:
            return out
        st = subprocess.run(["git", "status", "--porcelain", "--", str(receipts_dir)],
                            capture_output=True, text=True)
        if st.returncode != 0:
            return out
        for line in st.stdout.splitlines():
            code = line[:2]
            if code == "??":
                out["untracked"] += 1
            elif code.strip():
                out["modified"] += 1
        up = subprocess.run(["git", "rev-parse", "--abbrev-ref",
                             "--symbolic-full-name", "@{u}"],
                            capture_output=True, text=True)
        if up.returncode != 0:
            return out
        out["upstream"] = up.stdout.strip()
        ahead = subprocess.run(["git", "diff", "--name-only",
                                f"{out['upstream']}...HEAD", "--", str(receipts_dir)],
                               capture_output=True, text=True)
        out["unpushed"] = len([l for l in ahead.stdout.splitlines() if l.strip()])
    except OSError:
        pass
    return out


def _report_anchor(receipts_dir: Path) -> None:
    a = _anchor_status(receipts_dir)
    if a["total"] == 0:
        return
    loose = a["untracked"] + a["modified"] + (a["unpushed"] or 0)
    if a["upstream"] is None:
        print(f"ANCHOR: {a['total']} receipt(s) exist only in this working tree "
              f"(no upstream). A local-only chain is a claim, not evidence: "
              f"commit and push {receipts_dir}/.", file=sys.stderr)
    elif loose == 0:
        print(f"ANCHOR: all {a['total']} receipt(s) committed and pushed to "
              f"{a['upstream']} — every clone holds an independent copy.")
    else:
        parts = []
        if a["untracked"]:
            parts.append(f"{a['untracked']} untracked")
        if a["modified"]:
            parts.append(f"{a['modified']} modified-uncommitted")
        if a["unpushed"]:
            parts.append(f"{a['unpushed']} committed-not-pushed")
        print(f"ANCHOR: {', '.join(parts)} of {a['total']} receipt(s) are not on "
              f"{a['upstream']}. Until pushed they are only as trustworthy as "
              f"this machine.", file=sys.stderr)


# ------------------------------------------------------------------ verify
def _report_registry_drift(receipts: list, registry_path) -> None:
    actual = _sha256_file(registry_path)
    if actual is None:
        return
    drifted = sum(1 for r in receipts
                  if (r.get("inputs") or {}).get("registry_sha256") not in (None, actual))
    if drifted:
        print(f"NOTE: {drifted} receipt(s) were decided under a registry that "
              f"differs from {registry_path} on disk now — the decision was made "
              f"under a now-changed registry.", file=sys.stderr)


def verify(receipts_dir, *, key=None, structure_only=False,
           registry_path=None) -> int:
    rdir = Path(receipts_dir)
    if not rdir.exists() or not any(rdir.rglob("*.json")):
        print(f"FAIL: no receipts under {rdir} — nothing to verify",
              file=sys.stderr)
        return 2

    # 1. structure / chain (needs no key)
    try:
        head = latest_receipt_hash(rdir)
    except ChainStateError as exc:
        print(f"CHAIN FAIL: {exc}", file=sys.stderr)
        return 1
    receipts = [json.loads(p.read_text()) for p in sorted(rdir.rglob("*.json"))]
    n = len(receipts)

    # 2. decision consistency (eval-specific: catches a re-signed verdict table
    #    whose recorded decision disagrees with its own verdicts)
    for r in receipts:
        want = _decision_from_verdicts(r.get("verdicts", []))
        if r.get("decision") != want:
            print(f"DECISION FAIL: receipt {r.get('receipt_id')} records "
                  f"{r.get('decision')!r} but its verdicts imply {want!r} — "
                  f"the decision does not match the evidence it claims to rest on",
                  file=sys.stderr)
            return 1

    # 3. registry drift (informational)
    if registry_path is not None:
        _report_registry_drift(receipts, registry_path)

    # 4. signatures
    if structure_only or key is None:
        print(f"chain structure OK: {n} receipt(s), one unbroken line from "
              f"GENESIS, every stored receipt_hash matches its content, "
              f"head {head[:12]}…")
        reason = ("--structure-only requested" if structure_only
                  else "no key provided (the key is gitignored by design; "
                       "supply it to check signatures)")
        print(f"SIGNATURES NOT CHECKED: {reason}. Structure proves the receipts "
              f"are internally consistent, not that they were signed under the "
              f"team's key.", file=sys.stderr)
        _report_anchor(rdir)
        return 0 if structure_only else 2

    bad = 0
    for r in receipts:
        if r.get("signing_version") == "unsigned":
            print(f"SIG FAIL: receipt {r.get('receipt_id')} is unsigned but a "
                  f"key was supplied — expected a signature", file=sys.stderr)
            bad += 1
            continue
        want = _sign(key, r["receipt_hash"])
        if not hmac.compare_digest(want, r.get("signature", "")):
            print(f"SIG FAIL: {r.get('receipt_id')}", file=sys.stderr)
            bad += 1
    if bad:
        print(f"VERDICT: FAIL — {bad}/{n} bad signature(s)", file=sys.stderr)
        return 1
    print(f"chain OK: {n} receipt(s), head {head[:12]}… — decisions unaltered "
          f"since signing under this shared key (the key does not identify the "
          f"signer).")
    _report_anchor(rdir)
    return 0


# ------------------------------------------------------------------ CLI
def cmd_init(args) -> int:
    kp = Path(args.receipt_key)
    if kp.exists():
        print(f"key exists: {kp} (use a new path or delete it to rotate — old "
              f"receipts then verify only with the OLD key)")
        return 0
    kp.parent.mkdir(parents=True, exist_ok=True)
    kp.write_text(make_key() + "\n")
    try:
        kp.chmod(0o600)
    except OSError:
        pass
    # fail-closed: a tracked key is a published key
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(kp)],
                             capture_output=True)
    if tracked.returncode == 0:
        kp.unlink()
        print(f"FAIL: {kp} is TRACKED by git — untrack it (git rm --cached "
              f"{kp}) and gitignore it before generating a key", file=sys.stderr)
        return 2
    print(f"key written: {kp} (never commit it; receipts are only as private "
          f"as this key). Receipts now sign automatically on every gate run.")
    return 0


def cmd_verify(args) -> int:
    key = None if args.structure_only else load_key_from(args.receipt_key)
    return verify(args.receipts_dir, key=key, structure_only=args.structure_only,
                  registry_path=args.registry)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="generate the signing key")
    pi.add_argument("--receipt-key", default=DEFAULT_KEY_PATH)
    pi.set_defaults(fn=cmd_init)

    pv = sub.add_parser("verify", help="walk + verify the receipt chain")
    pv.add_argument("--receipts-dir", default=DEFAULT_RECEIPTS_DIR)
    pv.add_argument("--receipt-key", default=DEFAULT_KEY_PATH)
    pv.add_argument("--registry", default="evals/registry.yaml")
    pv.add_argument("--structure-only", action="store_true")
    pv.set_defaults(fn=cmd_verify)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
