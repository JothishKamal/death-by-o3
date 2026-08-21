import re

REC_RE = re.compile(
    r"^REC .*?class=(\S+) pass=(\S*) role=(\S+) .*?required=(\d)", re.M)


def parse(stderr):
    return REC_RE.findall(stderr)


def test_pipeline_names_are_resolved(run_capture, fixture_dir):
    """Spec C7: users see pipeline names, never class names."""
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    names = {p for _, p, _, _ in recs if p}
    assert "simplifycfg" in names
    assert "sroa" in names
    assert "loop-unroll" in names


def test_adaptors_have_no_pipeline_name_and_are_scaffolding(run_capture, fixture_dir):
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    adaptors = [r for r in recs
                if "Adaptor" in r[0] or r[0].startswith("PassManager<")]
    assert adaptors, "expected adaptor/PassManager nodes in the tree"
    for cls, pass_name, role, _ in adaptors:
        assert pass_name == "", f"{cls} unexpectedly has pipeline name {pass_name}"
        assert role == "scaffolding"


def test_extra_loop_pass_manager_wrapper_is_required(run_capture, fixture_dir):
    """Measured on 22.1.8: ExtraLoopPassManager<ShouldRunExtraSimpleLoopUnswitch>
    resolves to 'extra-simple-loop-unswitch-passes' -- the one PassManager-shaped
    class with a pipeline name. It is Required, so it can never be vetoed or
    ranked; recording its real name beats blanking it."""
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    wrappers = [r for r in recs if r[0].startswith("ExtraLoopPassManager<")]
    assert wrappers, "expected the extra-unswitch wrapper in the tree"
    for cls, pass_name, role, required in wrappers:
        assert pass_name == "extra-simple-loop-unswitch-passes"
        assert required == "1", f"{cls} must be Required"


def test_required_passes_are_detected(run_capture, fixture_dir):
    """Required passes never reach shouldRun, so they are never vetoable."""
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    required = [r for r in recs if r[3] == "1"]
    assert len(required) > 20, f"expected many required passes, got {len(required)}"
    classes = {r[0] for r in required}
    assert any("PassManager" in c for c in classes)


def test_both_vetoable_and_required_exist(run_capture, fixture_dir):
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    flags = {r[3] for r in recs}
    assert flags == {"0", "1"}, f"expected both vetoable and required, got {flags}"
