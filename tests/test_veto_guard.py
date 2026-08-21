from tests.test_veto_basic import find_target, veto_arg


def test_correct_guard_applies_the_veto(run_capture, capture_events, fixture_dir, tmp_path):
    target = find_target(capture_events(fixture_dir / "gemm.c"))
    result = run_capture(fixture_dir / "gemm.c",
                         env={"AUTOPSY_OUT": str(tmp_path / "e.jsonl"),
                              "AUTOPSY_VETO": veto_arg(target)})
    assert "VETO_APPLIED" in result.stderr
    assert "VETO_REFUSED" not in result.stderr


def test_wrong_guard_refuses_the_veto(run_capture, capture_events, fixture_dir, tmp_path):
    target = dict(find_target(capture_events(fixture_dir / "gemm.c")))
    target["guard"] = "0xdeadbeefdeadbeef"
    result = run_capture(fixture_dir / "gemm.c",
                         env={"AUTOPSY_OUT": str(tmp_path / "e.jsonl"),
                              "AUTOPSY_VETO": veto_arg(target)})
    assert "VETO_REFUSED" in result.stderr
    assert "VETO_APPLIED" not in result.stderr


def test_refused_veto_suppresses_nothing(capture_events, fixture_dir):
    target = dict(find_target(capture_events(fixture_dir / "gemm.c")))
    target["guard"] = "0x0000000000000000"
    recs = capture_events(fixture_dir / "gemm.c",
                          env={"AUTOPSY_VETO": veto_arg(target)})
    assert not [r for r in recs if r["status"] == "skipped"]


def test_stale_address_from_modified_source_is_refused(
        run_capture, capture_events, fixture_dir, tmp_path):
    """The guard exists to catch exactly this: an address captured against
    one program, replayed against another."""
    target = find_target(capture_events(fixture_dir / "gemm.c"))
    modified = tmp_path / "gemm_mod.c"
    modified.write_text(
        (fixture_dir / "gemm.c").read_text().replace("#define NK 64", "#define NK 65"))
    result = run_capture(modified,
                         env={"AUTOPSY_OUT": str(tmp_path / "e2.jsonl"),
                              "AUTOPSY_VETO": veto_arg(target)})
    assert "VETO_REFUSED" in result.stderr
