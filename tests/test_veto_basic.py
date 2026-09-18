def find_target(recs, pass_name="loop-unroll", func="kernel_gemm"):
    """Pick a changed, vetoable invocation to experiment on."""
    return next(r for r in recs
                if r["pass_name"] == pass_name and r["func"] == func
                and r["changed"] and not r["required"])


def veto_arg(r):
    return "|".join([r["pass_class"], r["kind"], r["unit_name"], r["func"],
                     str(r["occurrence"]), r["guard"]])


def test_veto_suppresses_exactly_one_invocation(capture_events, fixture_dir):
    base = capture_events(fixture_dir / "gemm.c")
    target = find_target(base)
    after = capture_events(fixture_dir / "gemm.c",
                           env={"AUTOPSY_VETO": veto_arg(target)})
    skipped = [r for r in after if r["status"] == "skipped"]
    assert len(skipped) == 1, f"expected exactly 1 skipped, got {len(skipped)}"
    assert skipped[0]["pass_class"] == target["pass_class"]
    assert skipped[0]["occurrence"] == target["occurrence"]


def test_veto_changes_the_object_file(fixture_dir, autopsy_plugin, tmp_path,
                                      capture_events):
    import subprocess, hashlib, os
    base_recs = capture_events(fixture_dir / "gemm.c")
    target = find_target(base_recs)

    def build(obj, env_extra):
        env = dict(os.environ, AUTOPSY_OUT=str(tmp_path / "e.jsonl"), **env_extra)
        subprocess.run(
            ["clang", "-O3", "-fno-discard-value-names",
             f"-fpass-plugin={autopsy_plugin}", "-c",
             str(fixture_dir / "gemm.c"), "-o", str(obj)],
            check=True, env=env)
        return hashlib.sha256(obj.read_bytes()).hexdigest()

    a = build(tmp_path / "a.o", {})
    b = build(tmp_path / "b.o", {"AUTOPSY_VETO": veto_arg(target)})
    assert a != b, "veto had no effect on codegen"


def test_unarmed_plugin_skips_nothing(capture_events, fixture_dir):
    recs = capture_events(fixture_dir / "gemm.c")
    assert not [r for r in recs if r["status"] == "skipped"]


def test_required_passes_cannot_be_vetoed(capture_events, fixture_dir):
    """Required passes never reach shouldRun, so arming against one is inert."""
    recs = capture_events(fixture_dir / "gemm.c")
    req = next(r for r in recs if r["required"])
    after = capture_events(fixture_dir / "gemm.c",
                           env={"AUTOPSY_VETO": veto_arg(req)})
    assert not [r for r in after if r["status"] == "skipped"]
