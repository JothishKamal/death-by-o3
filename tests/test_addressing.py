import json


def parse(recs):
    return [(r["seq"], r["pass_class"], r["pass_name"], r["kind"],
             r["unit_name"], r["func"], r["occurrence"], r["guard"])
            for r in recs]


def test_occurrences_start_at_one_and_increment(capture_events, fixture_dir):
    recs = parse(capture_events(fixture_dir / "gemm.c"))
    seen = {}
    for _, cls, pname, kind, name, func, occ, _ in recs:
        # Spec §1.2: an occurrence is the ordinal among invocations of the same
        # Pass. Scaffolding classes have an empty pipeline name, so the class --
        # the plugin's actual counter key -- is the pass identity here.
        key = (cls, kind, name, func)
        expected = seen.get(key, 0) + 1
        assert occ == expected, f"{key}: expected occ {expected}, got {occ}"
        seen[key] = expected


def test_distinct_loops_get_distinct_addresses(capture_events, fixture_dir):
    """Spec C3: without -fno-discard-value-names all loops share one bucket."""
    recs = parse(capture_events(fixture_dir / "gemm.c"))
    loop_names = {name for _, _, _, kind, name, _, _, _ in recs if kind == "loop"}
    assert len(loop_names) >= 3, f"only {len(loop_names)} distinct loop names"


def test_capture_is_deterministic(capture_events, fixture_dir):
    """The address is only stable if numbering is reproducible."""
    a = parse(capture_events(fixture_dir / "gemm.c"))
    b = parse(capture_events(fixture_dir / "gemm.c"))
    assert a == b


def test_guard_hash_is_stable_across_runs(capture_events, fixture_dir):
    a = {(s, g) for s, _, _, _, _, _, _, g in
         parse(capture_events(fixture_dir / "gemm.c"))}
    b = {(s, g) for s, _, _, _, _, _, _, g in
         parse(capture_events(fixture_dir / "gemm.c"))}
    assert a == b


def test_bisect_index_is_dense_over_gated_passes(capture_events, fixture_dir):
    """Required passes are not gated (-1); vetoable ones number 1..N with no gaps."""
    recs = capture_events(fixture_dir / "gemm.c")
    gated = [r["bisect_index"] for r in recs if not r["required"]]
    required = [r["bisect_index"] for r in recs if r["required"]]
    assert all(b == -1 for b in required)
    assert gated == list(range(1, len(gated) + 1)), "bisect indices are not dense"


def test_guard_hash_changes_when_input_changes(capture_events, run_capture,
                                               fixture_dir, tmp_path):
    """A stale address must be detectable."""
    src = (fixture_dir / "gemm.c").read_text()
    mod = tmp_path / "gemm_mod.c"
    mod.write_text(src.replace("#define NK 64", "#define NK 65"))
    orig = {r["guard"] for r in capture_events(fixture_dir / "gemm.c")}
    out = tmp_path / "mod.jsonl"
    result = run_capture(mod, env={"AUTOPSY_OUT": str(out)})
    assert result.returncode == 0
    other = {json.loads(l)["guard"]
             for l in out.read_text().splitlines() if l.strip()}
    assert orig != other
