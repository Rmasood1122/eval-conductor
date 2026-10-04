"""Pre-registered evals: seal the registry + bands BEFORE the run, so a gate
decision can prove it was judged under a bar that was committed to in advance —
closing the one hole the diff-lint cannot (a brand-new gate tuned to a score
already seen).

Runs standalone or under pytest. Mirrors tests/test_eval_receipt.py style.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import prereg  # noqa: E402
from canonical import canonical_bytes  # noqa: E402

KEY = bytes.fromhex("cd" * 32)

REG_V1 = (
    "- name: task_success_rate\n"
    "  direction: higher_better\n"
    "  threshold: 0.85\n"
    "  noise_band: 0.02\n"
    "  blocking: hard\n"
)
# Same metric, bar lowered 0.85 -> 0.80 (post-hoc tuning to clear a seen score)
REG_WEAKENED = REG_V1.replace("0.85", "0.80")


def _seals_dir(tmp):
    return tmp / "evals" / "seals"


# ---------------------------------------------------------------- seal body
def test_seal_binds_registry_hash(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    body = prereg.build_seal(registry_path=reg, seals_dir=_seals_dir(tmp_path),
                             bands=None, key=None)
    assert body["schema_version"] == prereg.SCHEMA
    assert body["registry_sha256"] == prereg._sha256_file(reg)
    assert body["seal_hash"] == __import__("hashlib").sha256(
        canonical_bytes({k: v for k, v in body.items() if k not in
                         ("seal_hash", "signature")})).hexdigest()


def test_seal_contains_no_candidate_data(tmp_path):
    """Candidate-independence: a seal must not embed anything scored."""
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    body = prereg.build_seal(registry_path=reg, seals_dir=_seals_dir(tmp_path),
                             bands=None, key=None)
    blob = json.dumps(body).lower()
    for forbidden in ("candidate", "scores", "0.87", "0.91"):
        assert forbidden not in blob, f"seal leaked candidate data: {forbidden}"


def test_seal_signs_when_keyed(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    body = prereg.build_seal(registry_path=reg, seals_dir=_seals_dir(tmp_path),
                             bands=None, key=KEY)
    assert body["signing_version"] == prereg.SIGNING
    assert "signature" in body and body["signature"]


# ---------------------------------------------------------------- seal chain
def test_seals_chain(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    sd = _seals_dir(tmp_path)
    p1 = prereg.create_seal(registry_path=reg, seals_dir=sd, bands=None, key=KEY)
    p2 = prereg.create_seal(registry_path=reg, seals_dir=sd, bands=None, key=KEY)
    s1 = json.loads(Path(p1).read_text())
    s2 = json.loads(Path(p2).read_text())
    assert s1["prev_seal_hash"] == prereg.GENESIS
    assert s2["prev_seal_hash"] == s1["seal_hash"]


def test_deleted_seal_breaks_chain(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    sd = _seals_dir(tmp_path)
    prereg.create_seal(registry_path=reg, seals_dir=sd, bands=None, key=KEY)
    p2 = prereg.create_seal(registry_path=reg, seals_dir=sd, bands=None, key=KEY)
    prereg.create_seal(registry_path=reg, seals_dir=sd, bands=None, key=KEY)
    Path(p2).unlink()  # remove the middle seal -> dangling prev
    rc = prereg.check(reg, seals_dir=sd, key=KEY)
    assert rc != 0, "deleting a middle seal must not verify clean"


# ---------------------------------------------------------------- the attack
def test_registry_unchanged_since_seal_passes(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    sd = _seals_dir(tmp_path)
    prereg.create_seal(registry_path=reg, seals_dir=sd, bands=None, key=KEY)
    # candidate judged under the SAME registry bytes that were sealed
    rc = prereg.check(reg, seals_dir=sd, key=KEY, require_seal=True)
    assert rc == 0


def test_registry_weakened_after_seal_is_drift(tmp_path):
    """The headline: seal strict bar, then weaken it to clear a seen score."""
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    sd = _seals_dir(tmp_path)
    prereg.create_seal(registry_path=reg, seals_dir=sd, bands=None, key=KEY)
    reg.write_text(REG_WEAKENED)  # move the goalpost AFTER sealing
    status = prereg.check_drift(reg, seals_dir=sd, key=KEY)
    assert status["registry_match"] is False
    # with enforcement on, drift must fail closed
    rc = prereg.check(reg, seals_dir=sd, key=KEY, require_seal=True)
    assert rc == 2


def test_no_seal_is_noop_without_require(tmp_path):
    """Un-sealed gates must keep working — pre-reg is opt-in, additive."""
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    sd = _seals_dir(tmp_path)  # no seals created
    rc = prereg.check(reg, seals_dir=sd, key=KEY, require_seal=False)
    assert rc == 0


def test_no_seal_but_required_fails(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    sd = _seals_dir(tmp_path)
    rc = prereg.check(reg, seals_dir=sd, key=KEY, require_seal=True)
    assert rc == 2, "--require-seal with no seal must fail closed"


# ---------------------------------------------------------------- bands
def test_bands_drift_detected(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    sd = _seals_dir(tmp_path)
    bands_sealed = {"task_success_rate": {"source": "registry", "value": 0.02}}
    prereg.create_seal(registry_path=reg, seals_dir=sd, bands=bands_sealed, key=KEY)
    bands_now = {"task_success_rate": {"source": "registry", "value": 0.20}}  # 10x wider
    status = prereg.check_drift(reg, seals_dir=sd, key=KEY, bands=bands_now)
    assert status["bands_match"] is False


# ---------------------------------------------------------------- tamper
def test_tampered_seal_hash_detected(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    sd = _seals_dir(tmp_path)
    p = prereg.create_seal(registry_path=reg, seals_dir=sd, bands=None, key=KEY)
    s = json.loads(Path(p).read_text())
    s["registry_sha256"] = "0" * 64  # lie about the sealed bar, keep old hash
    Path(p).write_text(json.dumps(s, indent=2))
    rc = prereg.check(reg, seals_dir=sd, key=KEY)
    assert rc != 0, "a tampered seal body must not verify"


# ---------------------------------------------------------------- CLI
def test_cli_seal_then_check(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(REG_V1)
    sd = _seals_dir(tmp_path)
    keyfile = tmp_path / ".receipt-key"
    keyfile.write_text("cd" * 32 + "\n")
    script = str(ROOT / "core" / "prereg.py")
    r = subprocess.run([sys.executable, script, "seal", "--registry", str(reg),
                        "--seals-dir", str(sd), "--receipt-key", str(keyfile)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([sys.executable, script, "check", "--registry", str(reg),
                        "--seals-dir", str(sd), "--receipt-key", str(keyfile),
                        "--require-seal"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # weaken + require -> fail closed
    reg.write_text(REG_WEAKENED)
    r = subprocess.run([sys.executable, script, "check", "--registry", str(reg),
                        "--seals-dir", str(sd), "--receipt-key", str(keyfile),
                        "--require-seal"], capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
