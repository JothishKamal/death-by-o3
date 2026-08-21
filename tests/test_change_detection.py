def parse(recs):
    return [(r["pass_name"], r["status"], r["changed"]) for r in recs]


def test_some_but_not_all_invocations_change_ir(capture_events, fixture_dir):
    """Spec §3: the log must collapse usefully -- roughly 15-25% change."""
    recs = parse(capture_events(fixture_dir / "gemm.c"))
    changed = [r for r in recs if r[2]]
    assert 0 < len(changed) < len(recs)
    ratio = len(changed) / len(recs)
    assert 0.05 < ratio < 0.50, f"changed ratio {ratio:.2f} is implausible"


def test_known_transforms_report_changed(capture_events, fixture_dir):
    """sroa and simplifycfg demonstrably rewrite this fixture."""
    recs = parse(capture_events(fixture_dir / "gemm.c"))
    for pname in ("sroa", "simplifycfg"):
        hits = [r for r in recs if r[0] == pname and r[2]]
        assert hits, f"{pname} never reported a change"


def test_attribute_only_changes_are_caught(capture_events, fixture_dir):
    """Spec C4: inferattrs changes attributes but hashes structurally equal.
    Without the attribute hash it would be reported as unchanged."""
    recs = parse(capture_events(fixture_dir / "gemm.c"))
    hits = [r for r in recs if r[0] == "inferattrs"]
    assert hits, "inferattrs did not run"
    assert any(r[2] for r in hits), \
        "inferattrs reported no change -- attribute hash is not wired in"


def test_skipped_invocations_are_never_changed(capture_events, fixture_dir):
    recs = parse(capture_events(fixture_dir / "gemm.c"))
    for pname, status, changed in recs:
        if status == "skipped":
            assert not changed
