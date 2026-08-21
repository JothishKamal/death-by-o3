import re

REC_RE = re.compile(r"^REC seq=(\d+) parent=(-?\d+) depth=(\d+)", re.M)


def parse(stderr):
    return [(int(a), int(b), int(c)) for a, b, c in REC_RE.findall(stderr)]


def test_records_are_emitted(run_capture, fixture_dir):
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    assert len(recs) > 300, f"expected hundreds of invocations, got {len(recs)}"


def test_dfs_preorder_invariant_parent_less_than_seq(run_capture, fixture_dir):
    """Spec §6.1: the whole client-side filter depends on parent < seq."""
    for seq, parent, _ in parse(run_capture(fixture_dir / "gemm.c").stderr):
        assert parent < seq, f"record {seq} has parent {parent}"


def test_tree_nests_deeply(run_capture, fixture_dir):
    """Spec C2: invocations nest Module -> CGSCC -> Function -> Loop."""
    depths = [d for _, _, d in parse(run_capture(fixture_dir / "gemm.c").stderr)]
    assert max(depths) >= 6, f"max depth {max(depths)}; expected deep nesting"


def test_root_records_have_no_parent(run_capture, fixture_dir):
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    roots = [r for r in recs if r[1] == -1]
    assert roots, "expected at least one root record"
    assert all(d == 0 for _, _, d in roots)
