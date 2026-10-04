"""Pre-registered evals — seal the bar BEFORE the run, so a gate decision can
prove it was judged under a registry + bands that were committed to in advance.

The companion to two existing controls:
  - registry_diff_lint.py (IE-06b) proves the registry did not get WEAKER than
    its git base. Its blind spot, in its own words: a brand-new gate has no base
    ("nothing to weaken") — so a gate authored to exactly clear a score you have
    already seen passes every check. That is p-hacking your own gate.
  - eval_receipt.py (v1.2) proves a decision is unaltered since signing. It
    faithfully signs that post-hoc-tuned PROMOTE too — the number is real, the
    bar is fiction.

A SEAL closes the hole. It is a committed artifact that fixes the bar and
contains NO candidate data, so it cannot have been computed from scores it does
not hold. At gate time the live registry (and, optionally, the bands) are
re-hashed and compared to the seal: if the bar moved since it was sealed, the
gate knows.

What a seal proves, in increasing strength:
  1. Content binding (crypto): the registry judged against is byte-identical to
     the sealed one — no silent swap of the bar between seal and run.
  2. Candidate-independence (structural): the seal embeds no scores.
  3. Ordering (git-anchored): a seal is committed and pushed like a receipt. Its
     honest strength is not the `sealed_at` string — a key-holder can type any
     time — but that it appears in pushed git history a third party witnessed, in
     a commit that precedes the candidate's. "The bar was fixed before the
     result" becomes a fact about shared history, not the owner's word.

What it does NOT prove (stated loudly — overclaiming here is the exact sin this
tool exists to catch):
  - Not that the bar is strict ENOUGH. A pre-committed weak bar is still weak;
    this proves it was pre-committed, not that it was good. (Strictness is the
    diff-lint's and the reviewer's job.)
  - Not, by cryptography alone, that `sealed_at` is truthful — a shared-secret
    HMAC lets the key-holder backdate. Ordering rests on git anchoring, not the
    timestamp. Same "distribution, not the key" stance as receipts.
  - Not signer identity (shared-secret HMAC).

Enforcement posture mirrors the rest of the gate exactly: creating a seal and
recording its status are best-effort side effects that never change an exit
code; `check --require-seal` is the fail-closed knob a team opts into in CI.

Usage:
  python3 prereg.py seal   [--registry PATH] [--seals-dir DIR] [--receipt-key PATH]
                           [--baseline PATH] [--note TEXT]
  python3 prereg.py check  [--registry PATH] [--seals-dir DIR] [--receipt-key PATH]
                           [--baseline PATH] [--require-seal] [--structure-only]

Exit codes (check): 0 ok (or no seal, not required) · 2 drift / no seal when
required / tampered chain / usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical import canonical_bytes                      # noqa: E402
from chain_state import ChainStateError, GENESIS           # noqa: E402
import eval_receipt as _er                                 # noqa: E402

SCHEMA = "eval-seal/v1"
SIGNING = "hmac-sha256-v1"
DEFAULT_SEALS_DIR = "evals/seals"
DEFAULT_KEY_PATH = "evals/.receipt-key"

# Reuse the receipt key family — one secret, not two.
load_key_from = _er.load_key_from
_sha256_file = _er._sha256_file
_sign = _er._sign


# ------------------------------------------------------------------ seal chain
# Seals chain exactly like receipts (single genesis, no fork, no dangling prev,
# recomputed-hash match, one head), but over `seal_hash`/`prev_seal_hash`. We
# keep a dedicated walker rather than reusing chain_state's receipt-keyed one so
# a seal and a receipt can never be mistaken for links in each other's chain.
def _recomputed_seal_hash(seal: dict) -> str:
    profile = seal.get("schema_version")
    if profile != SCHEMA:
        raise ChainStateError(
            f"unknown seal schema_version {profile!r}: no canonicalization "
            f"fallback exists by design")
    body = {k: v for k, v in seal.items() if k not in ("seal_hash", "signature")}
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def latest_seal_hash(seals_root) -> str:
    """Head of the seal chain, or GENESIS for an empty tree. Any ambiguity
    (fork, double-genesis, dangling prev, hash mismatch, headless) is a hard
    error — writing on a broken chain would launder the break."""
    root = Path(seals_root)
    paths = sorted(root.rglob("*.json")) if root.exists() else []
    if not paths:
        return GENESIS

    seals = []
    for p in paths:
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise ChainStateError(f"unreadable seal {p}: {e}") from e
        stored, prev = s.get("seal_hash"), s.get("prev_seal_hash")
        if not stored or not prev:
            raise ChainStateError(f"seal {p} missing seal_hash/prev_seal_hash")
        if _recomputed_seal_hash(s) != stored:
            raise ChainStateError(
                f"seal {p}: stored seal_hash does not match recomputed hash — "
                f"refusing to trust a tampered seal")
        seals.append((p, s))

    by_hash, prev_refs = {}, {}
    for p, s in seals:
        h = s["seal_hash"]
        if h in by_hash:
            raise ChainStateError(f"duplicate seal_hash {h} ({p})")
        by_hash[h] = (p, s)
        prev_refs.setdefault(s["prev_seal_hash"], []).append(p)

    gen = prev_refs.get(GENESIS, [])
    if len(gen) == 0:
        raise ChainStateError("no GENESIS seal: chain has no root")
    if len(gen) > 1:
        raise ChainStateError(f"multiple seals claim prev=GENESIS: {gen} — forked at root")
    for prev, children in prev_refs.items():
        if len(children) > 1:
            raise ChainStateError(f"fork: {children} all claim prev={prev}")
        if prev != GENESIS and prev not in by_hash:
            raise ChainStateError(
                f"dangling prev {prev} referenced by {children[0]}: predecessor "
                f"seal is missing")
    heads = [h for h in by_hash if h not in prev_refs]
    if len(heads) != 1:
        raise ChainStateError(f"expected exactly one seal-chain head, found {len(heads)}")
    return heads[0]


def head_seal(seals_root) -> dict | None:
    """The current head seal as a dict, or None for an empty (unsealed) tree.
    Raises ChainStateError on a broken chain."""
    root = Path(seals_root)
    if not root.exists() or not any(root.rglob("*.json")):
        return None
    head = latest_seal_hash(root)
    for p in root.rglob("*.json"):
        s = json.loads(p.read_text())
        if s.get("seal_hash") == head:
            return s
    return None  # pragma: no cover - head always exists if the walk succeeded


# ------------------------------------------------------------------ bands
def bands_from_registry(registry_path) -> dict:
    """The band the gate would use from the REGISTRY ALONE (the noise_band
    floor) for each metric. Sealing this catches a later baseline re-run that
    widens a band post-hoc: the committed floor is fixed here."""
    import yaml
    try:
        rows = yaml.safe_load(Path(registry_path).read_text())
    except Exception:  # noqa: BLE001 - bands are optional; never block sealing
        return {}
    out = {}
    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and isinstance(r.get("name"), str):
                try:
                    out[r["name"]] = {"source": "registry",
                                      "value": float(r.get("noise_band", 0.0))}
                except (TypeError, ValueError):
                    out[r["name"]] = {"source": "registry", "value": None}
    return out


def _bands_hash(bands: dict | None) -> str | None:
    if not bands:
        return None
    return hashlib.sha256(canonical_bytes(bands)).hexdigest()


# ------------------------------------------------------------------ build
def build_seal(*, registry_path, seals_dir, bands=None, note="", repo=None,
               prev=None, key=None) -> dict:
    now = datetime.now(timezone.utc)
    if prev is None:
        prev = latest_seal_hash(seals_dir)
    body = {
        "schema_version": SCHEMA,
        "signing_version": SIGNING if key is not None else "unsigned",
        "seal_id": str(uuid.uuid4()),
        "sealed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root_date": now.strftime("%Y-%m-%d"),
        "repo": repo or "",
        "note": note or "",
        "registry_path": str(registry_path),
        "registry_sha256": _sha256_file(registry_path),
        "bands": bands or None,
        "bands_sha256": _bands_hash(bands),
        "commit": _er._commit_info(),
        "prev_seal_hash": prev,
    }
    body["seal_hash"] = _recomputed_seal_hash(body)
    if key is not None:
        body["signature"] = _sign(key, body["seal_hash"])
    return body


def create_seal(*, registry_path, seals_dir, bands=None, note="", key=None) -> str | None:
    """Write a seal to seals_dir/<date>/<id>.json. Returns the path, or None on
    a broken chain (refuses to extend it) / any failure, warning to stderr."""
    try:
        seals_dir = Path(seals_dir)
        seal = build_seal(registry_path=registry_path, seals_dir=seals_dir,
                          bands=bands, note=note, repo=Path.cwd().name, key=key)
        out = seals_dir / seal["root_date"] / f"{seal['seal_id']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(seal, indent=2) + "\n")
        return str(out)
    except ChainStateError as exc:
        print(f"SEAL: refusing to extend a broken seal chain ({exc}). Run "
              f"'prereg.py check' and repair before sealing again.", file=sys.stderr)
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"SEAL: not written ({type(exc).__name__}: {exc}).", file=sys.stderr)
        return None


# ------------------------------------------------------------------ drift
def check_drift(registry_path, *, seals_dir, key=None, bands=None) -> dict:
    """Compare the live registry (+ bands, if given) against the head seal.

    Returns a status dict — never raises, never exits. `sealed` is False when no
    seal exists; `registry_match`/`bands_match` are None when not applicable.
    This is the side-effect-safe form the gate records on the receipt."""
    status = {"sealed": False, "seal_id": None, "registry_match": None,
              "bands_match": None, "chain_ok": True, "signature_ok": None,
              "detail": ""}
    try:
        seal = head_seal(seals_dir)
    except ChainStateError as exc:
        status["chain_ok"] = False
        status["detail"] = f"seal chain broken: {exc}"
        return status
    if seal is None:
        status["detail"] = "no seal on record"
        return status

    status["sealed"] = True
    status["seal_id"] = seal.get("seal_id")

    if key is not None and seal.get("signing_version") != "unsigned":
        import hmac
        want = _sign(key, seal["seal_hash"])
        status["signature_ok"] = hmac.compare_digest(want, seal.get("signature", ""))

    actual_reg = _sha256_file(registry_path)
    status["registry_match"] = (actual_reg is not None
                                and actual_reg == seal.get("registry_sha256"))

    if bands is not None and seal.get("bands_sha256") is not None:
        status["bands_match"] = (_bands_hash(bands) == seal["bands_sha256"])

    bits = [f"seal {status['seal_id']}",
            "registry MATCHES" if status["registry_match"] else "registry DRIFTED"]
    if status["bands_match"] is not None:
        bits.append("bands MATCH" if status["bands_match"] else "bands DRIFTED")
    if status["signature_ok"] is False:
        bits.append("SIGNATURE INVALID")
    status["detail"] = "; ".join(bits)
    return status


def check(registry_path, *, seals_dir, key=None, bands=None, require_seal=False,
          structure_only=False) -> int:
    """CLI/CI entry. Exit 0 = ok (or no seal and not required); 2 = drift / no
    seal when required / broken chain / bad signature.

    Enforcement is opt-in: without --require-seal, drift is reported loudly but
    does not fail, so upgrading never breaks an un-sealed gate."""
    status = check_drift(registry_path, seals_dir=seals_dir,
                         key=None if structure_only else key, bands=bands)

    if not status["chain_ok"]:
        print(f"SEAL CHAIN FAIL: {status['detail']}", file=sys.stderr)
        return 2

    if not status["sealed"]:
        if require_seal:
            print("PRE-REG FAIL: no seal on record but --require-seal is set. "
                  "Seal the registry before the run: prereg.py seal.", file=sys.stderr)
            return 2
        print("pre-registration: no seal on record (not required) — skipping. "
              "Run 'prereg.py seal' to commit to this bar before your next run.")
        return 0

    hard_fail = (status["registry_match"] is False
                 or status["bands_match"] is False
                 or status["signature_ok"] is False)

    if hard_fail:
        print(f"PRE-REG DRIFT: {status['detail']} — the bar changed since it "
              f"was sealed. The decision is NOT being made under the "
              f"pre-committed registry.", file=sys.stderr)
        if status["registry_match"] is False:
            print("  registry.yaml differs byte-for-byte from the sealed copy. "
                  "If the change is legitimate, seal again BEFORE re-running the "
                  "candidate — never after seeing its scores.", file=sys.stderr)
        return 2 if require_seal else 0

    print(f"pre-registration OK: {status['detail']} — judged under the "
          f"registry sealed in {status['seal_id']}.")
    if status["signature_ok"] is None and not structure_only:
        print("SIGNATURE NOT CHECKED: no key provided (the key is gitignored by "
              "design; supply it to check the seal's signature).", file=sys.stderr)
    _er._report_anchor(Path(seals_dir))
    return 0


# ------------------------------------------------------------------ CLI
def cmd_seal(args) -> int:
    key = load_key_from(args.receipt_key)
    bands = bands_from_registry(args.registry) if not args.no_bands else None
    path = create_seal(registry_path=args.registry, seals_dir=args.seals_dir,
                       bands=bands, note=args.note, key=key)
    if path is None:
        return 2
    signed = "signed" if key is not None else "UNSIGNED (no key)"
    print(f"sealed [{signed}]: {path}")
    print("Commit and push it NOW — a local-only seal is a claim, not evidence. "
          "Its strength is appearing in pushed history before your candidate.")
    _er._report_anchor(Path(args.seals_dir))
    return 0


def cmd_check(args) -> int:
    key = None if args.structure_only else load_key_from(args.receipt_key)
    bands = bands_from_registry(args.registry) if not args.no_bands else None
    return check(args.registry, seals_dir=args.seals_dir, key=key, bands=bands,
                 require_seal=args.require_seal, structure_only=args.structure_only)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("seal", help="seal the registry + bands before the run")
    ps.add_argument("--registry", default="evals/registry.yaml")
    ps.add_argument("--seals-dir", default=DEFAULT_SEALS_DIR)
    ps.add_argument("--receipt-key", default=DEFAULT_KEY_PATH)
    ps.add_argument("--baseline", default="evals/baseline.json")
    ps.add_argument("--note", default="")
    ps.add_argument("--no-bands", action="store_true",
                    help="seal only the registry hash, not the band floors")
    ps.set_defaults(fn=cmd_seal)

    pc = sub.add_parser("check", help="verify the live bar against the seal")
    pc.add_argument("--registry", default="evals/registry.yaml")
    pc.add_argument("--seals-dir", default=DEFAULT_SEALS_DIR)
    pc.add_argument("--receipt-key", default=DEFAULT_KEY_PATH)
    pc.add_argument("--baseline", default="evals/baseline.json")
    pc.add_argument("--require-seal", action="store_true",
                    help="fail closed (exit 2) on drift or a missing seal")
    pc.add_argument("--no-bands", action="store_true")
    pc.add_argument("--structure-only", action="store_true",
                    help="check chain + content hashes without the signing key")
    pc.set_defaults(fn=cmd_check)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
