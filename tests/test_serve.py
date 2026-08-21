from fastapi.testclient import TestClient

from autopsy.api.serve import build_server


def test_serve_captures_and_exposes_a_run(repo_root, tmp_path):
    app, run_id = build_server(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path)
    client = TestClient(app)
    assert client.get("/api/runs").json()[0]["id"] == run_id


def test_tree_endpoint_serves_the_captured_run(repo_root, tmp_path):
    app, run_id = build_server(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path)
    body = TestClient(app).get(f"/api/run/{run_id}/tree").json()
    assert body["nodeCount"] > 300
    assert body["order"] == "dfs-preorder"


def test_evidence_endpoint_serves_a_record(repo_root, tmp_path):
    app, run_id = build_server(repo_root / "tests" / "fixtures" / "gemm.c",
                               tmp_path, top=1)
    rec = TestClient(app).get(f"/api/run/{run_id}/evidence").json()
    assert "verdict" in rec and "claim" in rec


def test_every_served_measurement_has_provenance(repo_root, tmp_path):
    app, run_id = build_server(repo_root / "tests" / "fixtures" / "gemm.c",
                               tmp_path, top=1)
    rec = TestClient(app).get(f"/api/run/{run_id}/evidence").json()
    ids = {n["id"] for n in rec["provenance"]["nodes"]}
    assert all(m["provenance"] in ids for m in rec["measurements"])
