def parse(recs):
    return [(r["pass_class"], r["pass_name"], r["role"], r["required"])
            for r in recs]


def test_pipeline_names_are_resolved(capture_events, fixture_dir):
    """Spec C7: users see pipeline names, never class names."""
    recs = parse(capture_events(fixture_dir / "gemm.c"))
    names = {p for _, p, _, _ in recs if p}
    assert "simplifycfg" in names
    assert "sroa" in names
    assert "loop-unroll" in names


def test_adaptors_have_no_pipeline_name_and_are_scaffolding(capture_events,
                                                            fixture_dir):
    recs = parse(capture_events(fixture_dir / "gemm.c"))
    adaptors = [r for r in recs
                if "Adaptor" in r[0] or r[0].startswith("PassManager<")]
    assert adaptors, "expected adaptor/PassManager nodes in the tree"
    for cls, pass_name, role, _ in adaptors:
        assert pass_name == "", f"{cls} unexpectedly has pipeline name {pass_name}"
        assert role == "scaffolding"


def test_extra_loop_pass_manager_wrapper_is_required(capture_events, fixture_dir):
    """Measured on 22.1.8: ExtraLoopPassManager<ShouldRunExtraSimpleLoopUnswitch>
    resolves to 'extra-simple-loop-unswitch-passes' -- the one PassManager-shaped
    class with a pipeline name. It is Required, so it can never be vetoed or
    ranked; recording its real name beats blanking it."""
    recs = parse(capture_events(fixture_dir / "gemm.c"))
    wrappers = [r for r in recs if r[0].startswith("ExtraLoopPassManager<")]
    assert wrappers, "expected the extra-unswitch wrapper in the tree"
    for cls, pass_name, role, required in wrappers:
        assert pass_name == "extra-simple-loop-unswitch-passes"
        assert required is True, f"{cls} must be Required"


def test_required_passes_are_detected(capture_events, fixture_dir):
    """Required passes never reach shouldRun, so they are never vetoable."""
    recs = parse(capture_events(fixture_dir / "gemm.c"))
    required = [r for r in recs if r[3] is True]
    assert len(required) > 20, f"expected many required passes, got {len(required)}"
    classes = {r[0] for r in required}
    assert any("PassManager" in c for c in classes)


def test_both_vetoable_and_required_exist(capture_events, fixture_dir):
    recs = parse(capture_events(fixture_dir / "gemm.c"))
    flags = {r[3] for r in recs}
    assert flags == {True, False}, f"expected both vetoable and required, got {flags}"
