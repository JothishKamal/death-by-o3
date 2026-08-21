import pytest
from fastapi.testclient import TestClient

from autopsy.api.app import create_app
from autopsy.api.diff import char_changes, normalise_ssa
from autopsy.api.store import EvidenceStore
from autopsy.capture import capture


@pytest.fixture
def client(tmp_path, repo_root):
    store = EvidenceStore(tmp_path / "e.db")
    run = capture(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path / "cap")
    run_id = store.put_run(run, "gemm.c")
    c = TestClient(create_app(store))
    c.run_id, c.run = run_id, run
    return c


def test_ssa_normalisation_collapses_renumbering():
    a = "%1 = add i32 %0, 1\n%2 = mul i32 %1, 2\n"
    b = "%7 = add i32 %6, 1\n%8 = mul i32 %7, 2\n"
    assert normalise_ssa(a) == normalise_ssa(b)


def test_ssa_normalisation_preserves_named_values():
    text = "%acc.0 = phi double [ 0.0, %entry ]\n"
    assert "%acc.0" in normalise_ssa(text)


def test_char_changes_are_offsets_not_lines():
    before, after = "alpha\nbeta\ngamma\n", "alpha\nBETA\ngamma\n"
    changes = char_changes(before, after)
    assert changes
    for c in changes:
        assert len(c) == 4
        assert all(isinstance(v, int) for v in c)
    assert changes[0][0] >= 6


def test_identical_text_has_no_changes():
    assert char_changes("same\n", "same\n") == []


def test_common_ir_lines_are_not_discarded():
    """Guard against difflib autojunk, which drops `br label` and `}`."""
    before = "".join(f"  br label %b{i}\n}}\n" for i in range(200))
    after = before.replace("br label %b7\n", "br label %bX\n")
    assert char_changes(before, after), "diff dropped a change in a common line"


def test_invocation_detail_endpoint(client):
    target = next(d for d in client.run.decisions() if d.blobs_after)
    r = client.get(f"/api/run/{client.run_id}/inv/{target.seq}")
    assert r.status_code == 200
    body = r.json()
    assert body["seq"] == target.seq
    assert body["pass"] == target.pass_name
    assert "metrics" in body and "ir" in body


def test_ir_blob_endpoint_returns_text(client):
    target = next(d for d in client.run.decisions() if d.blobs_after)
    r = client.get(f"/api/run/{client.run_id}/ir/{target.blobs_after[0]}")
    assert r.status_code == 200
    assert "define" in r.text


def test_missing_remark_is_null_not_absent(client):
    """Only ~15 passes emit remarks; simplifycfg emits none. null is the norm."""
    target = next(d for d in client.run.decisions())
    body = client.get(f"/api/run/{client.run_id}/inv/{target.seq}").json()
    assert "remark" in body
