import json

from autopsy.diagnose import diagnose


def test_diagnose_produces_an_evidence_record(repo_root, tmp_path):
    d = diagnose(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path, top=2)
    assert d.evidence_path.exists()
    rec = json.loads(d.evidence_path.read_text())
    assert "verdict" in rec and "suspects" in rec and "measurements" in rec


def test_every_measurement_carries_provenance(repo_root, tmp_path):
    d = diagnose(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path, top=2)
    rec = json.loads(d.evidence_path.read_text())
    ids = {n["id"] for n in rec["provenance"]["nodes"]}
    for m in rec["measurements"]:
        assert m["provenance"] in ids, "a number without provenance is not displayable"


def test_exact_measurements_never_carry_an_interval(repo_root, tmp_path):
    d = diagnose(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path, top=2)
    rec = json.loads(d.evidence_path.read_text())
    for m in rec["measurements"]:
        if m["kind"] == "exact":
            assert m["n"] == 1
            assert "iqr" not in m and "ci" not in m


def test_the_causal_claim_is_stated_verbatim(repo_root, tmp_path):
    d = diagnose(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path, top=1)
    rec = json.loads(d.evidence_path.read_text())
    assert "this pipeline" in rec["claim"] and "this program" in rec["claim"]


def test_suspects_carry_a_reproduce_command(repo_root, tmp_path):
    d = diagnose(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path, top=1)
    rec = json.loads(d.evidence_path.read_text())
    if rec["suspects"]:
        assert "clang" in rec["suspects"][0]["reproduce"]
