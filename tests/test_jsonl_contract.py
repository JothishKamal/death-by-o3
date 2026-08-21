import json

FIELDS = {
    "seq", "parent_seq", "depth", "pass_class", "pass_name", "role", "kind",
    "unit_name", "func", "occurrence", "required", "status", "changed",
    "hash_before", "hash_after", "attr_hash_before", "attr_hash_after",
    "guard", "bisect_index", "wall_ns", "blobs_after",
}


def load(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


OPTIONAL = {"metrics_before", "metrics_after"}


def test_jsonl_is_written_and_parses(run_capture, fixture_dir, tmp_path):
    out = tmp_path / "events.jsonl"
    result = run_capture(fixture_dir / "gemm.c", env={"AUTOPSY_OUT": str(out)})
    assert result.returncode == 0, result.stderr
    recs = load(out)
    assert len(recs) > 300


def test_every_record_has_the_full_field_set(run_capture, fixture_dir, tmp_path):
    out = tmp_path / "events.jsonl"
    run_capture(fixture_dir / "gemm.c", env={"AUTOPSY_OUT": str(out)})
    for r in load(out):
        assert set(r) - OPTIONAL == FIELDS, f"field mismatch: {set(r) ^ FIELDS}"


def test_records_are_in_dfs_preorder(run_capture, fixture_dir, tmp_path):
    out = tmp_path / "events.jsonl"
    run_capture(fixture_dir / "gemm.c", env={"AUTOPSY_OUT": str(out)})
    recs = load(out)
    assert [r["seq"] for r in recs] == sorted(r["seq"] for r in recs)
    for r in recs:
        assert r["parent_seq"] < r["seq"]


def test_hashes_are_hex_strings(run_capture, fixture_dir, tmp_path):
    out = tmp_path / "events.jsonl"
    run_capture(fixture_dir / "gemm.c", env={"AUTOPSY_OUT": str(out)})
    for r in load(out):
        for f in ("hash_before", "hash_after", "guard"):
            assert isinstance(r[f], str) and r[f].startswith("0x")
            int(r[f], 16)


def test_wall_time_is_recorded_for_ran_invocations(run_capture, fixture_dir, tmp_path):
    out = tmp_path / "events.jsonl"
    run_capture(fixture_dir / "gemm.c", env={"AUTOPSY_OUT": str(out)})
    ran = [r for r in load(out) if r["status"] == "ran"]
    assert any(r["wall_ns"] > 0 for r in ran)


def test_nothing_is_written_without_the_env_var(run_capture, fixture_dir):
    """The plugin must be inert when not asked to capture."""
    result = run_capture(fixture_dir / "gemm.c")
    assert result.returncode == 0
    assert "REC seq=" not in result.stderr
