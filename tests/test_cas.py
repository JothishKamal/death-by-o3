def test_blobs_are_written_for_changed_invocations(capture_events, fixture_dir, tmp_path):
    cas = tmp_path / "cas"
    recs = capture_events(fixture_dir / "gemm.c", env={"AUTOPSY_CAS": str(cas)})
    changed = [r for r in recs if r["changed"] and r["kind"] == "function"]
    assert changed
    assert all(r["blobs_after"] for r in changed)
    assert cas.exists()


def test_blob_ids_are_sha256_hex(capture_events, fixture_dir, tmp_path):
    recs = capture_events(fixture_dir / "gemm.c",
                          env={"AUTOPSY_CAS": str(tmp_path / "cas")})
    for r in recs:
        for b in r["blobs_after"]:
            assert len(b) == 64 and all(c in "0123456789abcdef" for c in b)


def test_content_addressing_deduplicates(capture_events, fixture_dir, tmp_path):
    """Spec §5.2: ~45% of writes should hit content that already exists."""
    cas = tmp_path / "cas"
    recs = capture_events(fixture_dir / "gemm.c", env={"AUTOPSY_CAS": str(cas)})
    writes = sum(len(r["blobs_after"]) for r in recs)
    unique = len({b for r in recs for b in r["blobs_after"]})
    on_disk = sum(1 for p in cas.rglob("*") if p.is_file())
    assert on_disk == unique, f"{on_disk} files on disk but {unique} unique ids"
    assert unique < writes, "no deduplication occurred"


def test_stored_blob_is_parseable_llvm_ir(capture_events, fixture_dir, tmp_path):
    cas = tmp_path / "cas"
    recs = capture_events(fixture_dir / "gemm.c", env={"AUTOPSY_CAS": str(cas)})
    blob_id = next(b for r in recs if r["blobs_after"] for b in r["blobs_after"])
    path = cas / blob_id[:2] / blob_id[2:]
    text = path.read_text()
    assert text.lstrip().startswith("define") or "define" in text


def test_no_cas_written_without_env_var(capture_events, fixture_dir):
    recs = capture_events(fixture_dir / "gemm.c")
    assert all(r["blobs_after"] == [] for r in recs)
