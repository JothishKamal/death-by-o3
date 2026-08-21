import pytest
from fastapi.testclient import TestClient

from autopsy.api.app import create_app
from autopsy.api.store import EvidenceStore
from autopsy.capture import capture


@pytest.fixture
def store(tmp_path, repo_root):
    s = EvidenceStore(tmp_path / "evidence.db")
    run = capture(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path / "cap")
    s.run_id = s.put_run(run, "gemm.c")
    return s


def test_run_round_trips(store):
    got = store.get_run(store.run_id)
    assert len(got.invocations) > 300
    assert got.invocations[0].seq == 1


def test_dfs_invariant_survives_the_round_trip(store):
    for inv in store.get_run(store.run_id).invocations:
        assert inv.parent_seq < inv.seq


def test_listing_reports_counts(store):
    rows = store.list_runs()
    assert len(rows) == 1
    assert rows[0]["source"] == "gemm.c"
    assert rows[0]["invocations"] > 300
    assert rows[0]["decisions"] > 0


def test_evidence_round_trips(store):
    store.put_evidence(store.run_id, {"verdict": "RANKED", "suspects": []})
    assert store.get_evidence(store.run_id)["verdict"] == "RANKED"


def test_api_lists_runs(store):
    client = TestClient(create_app(store))
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert r.json()[0]["source"] == "gemm.c"


def test_unknown_run_is_404(store):
    client = TestClient(create_app(store))
    assert client.get("/api/run/nope/tree").status_code == 404
