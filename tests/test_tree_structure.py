def test_records_are_emitted(capture_events, fixture_dir):
    recs = capture_events(fixture_dir / "gemm.c")
    assert len(recs) > 300, f"expected hundreds of invocations, got {len(recs)}"


def test_dfs_preorder_invariant_parent_less_than_seq(capture_events, fixture_dir):
    """Spec §6.1: the whole client-side filter depends on parent < seq."""
    for r in capture_events(fixture_dir / "gemm.c"):
        assert r["parent_seq"] < r["seq"]


def test_tree_nests_deeply(capture_events, fixture_dir):
    """Spec C2: invocations nest Module -> CGSCC -> Function -> Loop."""
    depths = [r["depth"] for r in capture_events(fixture_dir / "gemm.c")]
    assert max(depths) >= 6, f"max depth {max(depths)}; expected deep nesting"


def test_root_records_have_no_parent(capture_events, fixture_dir):
    recs = capture_events(fixture_dir / "gemm.c")
    roots = [r for r in recs if r["parent_seq"] == -1]
    assert roots, "expected at least one root record"
    assert all(r["depth"] == 0 for r in roots)
