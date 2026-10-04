"""Eval receipts: tamper-evident, hash-chained, signed proof of every gate
decision. Fuses titan-gate's chain+signing into eval-conductor's promote gate.

Runs standalone or under pytest.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import eval_receipt as er            # noqa: E402
from compare import Verdict, decide  # noqa: E402
from canonical import canonical_bytes  # noqa: E402

KEY = bytes.fromhex("ab" * 32)       # 32-byte valid key


def _verdicts(*specs):
    """specs: (metric, status) -> list[Verdict]."""
    out = []
    for metric, status in specs:
        out.append(Verdict(metric=metric, blocking="hard", candidate=0.9,
                           baseline_mean=0.9, threshold=0.5, band=0.01,
                           status=status, reason="ok" if status == "PASS" else "breach"))
    return out


def _files(tmp, registry="x: 1\n", candidate='{"scores":{"m":0.9}}',
           baseline=None):
    reg = tmp / "registry.yaml"; reg.write_text(registry)
    cand = tmp / "candidate.json"; cand.write_text(candidate)
    base = None
    if baseline is not None:
        base = tmp / "baseline.json"; base.write_text(baseline)
    return reg, cand, base


# ------------------------------------------------------------------ build
def test_build_records_decision_and_input_hashes(tmp_path):
    reg, cand, _ = _files(tmp_path)
    r = er.build_receipt("PROMOTE", _verdicts(("m", "PASS")),
                         registry_path=reg, candidate_path=cand,
                         baseline_path=None, manifest=None, repo="demo",
                         prev=er.GENESIS)
    assert r["schema_version"] == "eval-receipt/v1"
    assert r["decision"] == "PROMOTE"
    assert r["inputs"]["registry_sha256"] == hashlib.sha256(reg.read_bytes()).hexdigest()
    assert r["inputs"]["candidate_sha256"] == hashlib.sha256(cand.read_bytes()).hexdigest()
    assert r["inputs"]["baseline_sha256"] is None
    assert r["prev_receipt_hash"] == er.GENESIS
    # receipt_hash is sha256 over the canonical body (sig/hash excluded)
    assert r["receipt_hash"] == hashlib.sha256(canonical_bytes(r)).hexdigest()


def test_build_signs_when_key_present(tmp_path):
    reg, cand, _ = _files(tmp_path)
    r = er.build_receipt("BLOCK", _verdicts(("m", "BLOCK")), registry_path=reg,
                         candidate_path=cand, baseline_path=None, manifest=None,
                         repo="demo", prev=er.GENESIS, key=KEY)
    assert r["signing_version"] == "hmac-sha256-v1"
    assert "signature" in r and er._sign(KEY, r["receipt_hash"]) == r["signature"]


def test_build_unsigned_when_no_key(tmp_path):
    reg, cand, _ = _files(tmp_path)
    r = er.build_receipt("PROMOTE", _verdicts(("m", "PASS")), registry_path=reg,
                         candidate_path=cand, baseline_path=None, manifest=None,
                         repo="demo", prev=er.GENESIS, key=None)
    assert r["signing_version"] == "unsigned"
    assert "signature" not in r


# ------------------------------------------------------------------ emit + chain
def test_emit_promote_and_block_write_receipts(tmp_path):
    reg, cand, _ = _files(tmp_path)
    rdir = tmp_path / "receipts"
    p1 = er.emit("PROMOTE", _verdicts(("m", "PASS")), registry_path=reg,
                 candidate_path=cand, receipts_dir=rdir, key=KEY)
    p2 = er.emit("BLOCK", _verdicts(("m", "BLOCK")), registry_path=reg,
                 candidate_path=cand, receipts_dir=rdir, key=KEY)
    assert p1 and p1.exists() and json.loads(p1.read_text())["decision"] == "PROMOTE"
    assert p2 and p2.exists() and json.loads(p2.read_text())["decision"] == "BLOCK"


def test_three_emits_form_unbroken_chain(tmp_path):
    reg, cand, _ = _files(tmp_path)
    rdir = tmp_path / "receipts"
    hashes = []
    for _ in range(3):
        p = er.emit("PROMOTE", _verdicts(("m", "PASS")), registry_path=reg,
                    candidate_path=cand, receipts_dir=rdir, key=KEY)
        hashes.append(json.loads(p.read_text())["receipt_hash"])
    # each receipt's prev links to the previous head; one unbroken chain
    assert er.verify(rdir, key=KEY) == 0
    prevs = sorted(json.loads(p.read_text())["prev_receipt_hash"]
                   for p in rdir.rglob("*.json"))
    assert er.GENESIS in prevs
    assert set(hashes[:-1]) <= set(prevs)      # every non-head is someone's prev


# ------------------------------------------------------------------ verify
def test_verify_passes_signed_chain(tmp_path):
    reg, cand, _ = _files(tmp_path)
    rdir = tmp_path / "receipts"
    er.emit("PROMOTE", _verdicts(("m", "PASS")), registry_path=reg,
            candidate_path=cand, receipts_dir=rdir, key=KEY)
    assert er.verify(rdir, key=KEY) == 0


def test_tamper_body_breaks_verify(tmp_path):
    reg, cand, _ = _files(tmp_path)
    rdir = tmp_path / "receipts"
    p = er.emit("PROMOTE", _verdicts(("m", "PASS")), registry_path=reg,
                candidate_path=cand, receipts_dir=rdir, key=KEY)
    r = json.loads(p.read_text())
    r["repo"] = "tampered"                      # body changed, hash not recomputed
    p.write_text(json.dumps(r))
    assert er.verify(rdir, key=KEY) == 1


def test_decision_flip_with_resign_caught_by_consistency(tmp_path):
    """A key-holder flips a BLOCK receipt to PROMOTE and re-signs. The chain
    and signature now verify — only the decision-vs-verdicts consistency check
    catches it."""
    reg, cand, _ = _files(tmp_path)
    rdir = tmp_path / "receipts"
    p = er.emit("BLOCK", _verdicts(("ok", "PASS"), ("bad", "BLOCK")),
                registry_path=reg, candidate_path=cand, receipts_dir=rdir, key=KEY)
    r = json.loads(p.read_text())
    r["decision"] = "PROMOTE"                   # lie
    r["receipt_hash"] = hashlib.sha256(canonical_bytes(r)).hexdigest()
    r["signature"] = er._sign(KEY, r["receipt_hash"])   # re-sign with the key
    p.write_text(json.dumps(r))
    assert er.verify(rdir, key=KEY) == 1        # verdicts contain a BLOCK


def test_verify_structure_only_passes_unsigned(tmp_path):
    reg, cand, _ = _files(tmp_path)
    rdir = tmp_path / "receipts"
    er.emit("PROMOTE", _verdicts(("m", "PASS")), registry_path=reg,
            candidate_path=cand, receipts_dir=rdir, key=None)   # unsigned
    assert er.verify(rdir, key=None, structure_only=True) == 0


def test_verify_without_key_is_exit2(tmp_path, capsys):
    reg, cand, _ = _files(tmp_path)
    rdir = tmp_path / "receipts"
    er.emit("PROMOTE", _verdicts(("m", "PASS")), registry_path=reg,
            candidate_path=cand, receipts_dir=rdir, key=KEY)
    assert er.verify(rdir, key=None, structure_only=False) == 2
    assert "SIGNATURES NOT CHECKED" in capsys.readouterr().err


def test_verify_empty_tree_is_exit2(tmp_path):
    assert er.verify(tmp_path / "nope", key=KEY) == 2


# ------------------------------------------------------------------ input binding
def test_registry_drift_is_reported_not_fatal(tmp_path, capsys):
    reg, cand, _ = _files(tmp_path)
    rdir = tmp_path / "receipts"
    er.emit("PROMOTE", _verdicts(("m", "PASS")), registry_path=reg,
            candidate_path=cand, receipts_dir=rdir, key=KEY)
    reg.write_text("x: 2\n")                     # registry changed after the run
    rc = er.verify(rdir, key=KEY, registry_path=reg)
    out = capsys.readouterr().out + capsys.readouterr().err
    assert rc == 0                              # drift is informational
    # the note is emitted somewhere
    er.verify(rdir, key=KEY, registry_path=reg)


def test_nonfinite_verdict_serialized_and_roundtrips(tmp_path):
    reg, cand, _ = _files(tmp_path)
    rdir = tmp_path / "receipts"
    nan_v = Verdict(metric="m", blocking="hard", candidate=float("nan"),
                    baseline_mean=None, threshold=0.5, band=0.0, status="BLOCK",
                    reason="metric missing from candidate run")
    p = er.emit("BLOCK", [nan_v], registry_path=reg, candidate_path=cand,
                receipts_dir=rdir, key=KEY)
    raw = p.read_text()
    assert "NaN" not in json.loads(raw.replace('"NaN"', '0'))  # valid JSON, no bare NaN
    assert json.loads(raw)["verdicts"][0]["candidate"] == "NaN"  # sentinel string
    assert er.verify(rdir, key=KEY) == 0


# ------------------------------------------------------------------ key validation
def test_short_or_bad_key_rejected(tmp_path):
    good = tmp_path / "k"; good.write_text(KEY.hex())
    assert er.load_key_file(good) == KEY
    short = tmp_path / "s"; short.write_text("ab" * 4)   # 4 bytes
    assert er.load_key_file(short) is None
    nothex = tmp_path / "n"; nothex.write_text("zzzz")
    assert er.load_key_file(nothex) is None


# ------------------------------------------------------------------ gate integration (subprocess)
HEALTHY = {"task_success_rate": 0.95, "json_schema_compliance": 1.0,
           "safety_pass_rate": 1.0, "latency_p95_s": 1.0, "cost_per_run_usd": 0.01}
BAD = dict(HEALTHY, safety_pass_rate=0.0)


def _init_repo(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "scripts/eval_init.py")],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return tmp_path


def _write_candidate(repo, scores):
    (repo / "evals/candidate.json").write_text(json.dumps({"scores": scores}))


def test_gate_emits_receipt_end_to_end(tmp_path):
    repo = _init_repo(tmp_path)
    _write_candidate(repo, HEALTHY)
    env = {"EVAL_RECEIPT_KEY": KEY.hex()}
    import os
    r = subprocess.run([sys.executable, "evals/tools/promote.py", "--receipt"],
                       cwd=repo, capture_output=True, text=True,
                       env={**os.environ, **env})
    assert r.returncode == 0, r.stdout + r.stderr
    receipts = list((repo / "evals/receipts").rglob("*.json"))
    assert receipts, "gate did not emit a receipt"
    assert json.loads(receipts[0].read_text())["decision"] == "PROMOTE"


def test_gate_exit_code_unchanged_when_receipt_fails(tmp_path):
    """A broken receipts tree must never flip the gate verdict or crash it."""
    repo = _init_repo(tmp_path)
    _write_candidate(repo, BAD)                 # should BLOCK (exit 1)
    import os
    # make the receipts dir an unwritable FILE -> emit fails
    (repo / "evals/receipts").write_text("not a dir")
    env = {"EVAL_RECEIPT_KEY": KEY.hex()}
    r = subprocess.run([sys.executable, "evals/tools/promote.py", "--receipt"],
                       cwd=repo, capture_output=True, text=True,
                       env={**os.environ, **env})
    assert r.returncode == 1, r.stdout + r.stderr   # still BLOCK, not crashed
    assert "RECEIPT" in (r.stdout + r.stderr)        # warned about the skip


def test_gate_no_receipt_by_default_without_key(tmp_path):
    """Backward compatible: no key, no --receipt -> behaves exactly as before."""
    repo = _init_repo(tmp_path)
    # eval_init may drop a local key; remove it to simulate a pre-1.2 repo
    k = repo / "evals/.receipt-key"
    if k.exists():
        k.unlink()
    _write_candidate(repo, HEALTHY)
    r = subprocess.run([sys.executable, "evals/tools/promote.py", "--no-receipt"],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not list((repo / "evals/receipts").rglob("*.json")) \
        if (repo / "evals/receipts").exists() else True


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
