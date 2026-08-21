import re

# Records emit in completion order (a parent pops after its children), so any
# check over pipeline order must sort by seq first.
REC_RE = re.compile(r"^REC seq=(\d+) ")
FIELD_RE = re.compile(
    r"(seq|parent|depth|class|pass|role|kind|name|func|status|required|occ|"
    r"bisect|guard|changed)=(.*?)(?= (?:seq|parent|depth|class|pass|role|kind|"
    r"name|func|status|required|occ|bisect|guard|changed)=|$)")


def parse(stderr):
    """Parse REC lines into dicts. Values may contain spaces (SCC names do)."""
    out = []
    for line in stderr.splitlines():
        if not REC_RE.match(line):
            continue
        fields = dict(FIELD_RE.findall(line))
        for k in ("seq", "parent", "depth", "required", "occ", "bisect", "changed"):
            fields[k] = int(fields[k])
        out.append(fields)
    return sorted(out, key=lambda f: f["seq"])


def test_occurrences_start_at_one_and_increment(run_capture, fixture_dir):
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    seen = {}
    for r in recs:
        # Spec §1.2: an occurrence is the ordinal among invocations of the same
        # Pass. Scaffolding classes have an empty pipeline name, so the class --
        # the plugin's actual counter key -- is the pass identity here.
        key = (r["class"], r["kind"], r["name"], r["func"])
        expected = seen.get(key, 0) + 1
        assert r["occ"] == expected, f"{key}: expected occ {expected}, got {r['occ']}"
        seen[key] = expected


def test_distinct_loops_get_distinct_addresses(run_capture, fixture_dir):
    """Spec C3: without -fno-discard-value-names all loops share one bucket."""
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    loop_names = {r["name"] for r in recs if r["kind"] == "loop"}
    assert len(loop_names) >= 3, f"only {len(loop_names)} distinct loop names"


def test_capture_is_deterministic(run_capture, fixture_dir):
    """The address is only stable if numbering is reproducible."""
    a = parse(run_capture(fixture_dir / "gemm.c").stderr)
    b = parse(run_capture(fixture_dir / "gemm.c").stderr)
    assert a == b


def test_guard_hash_is_stable_across_runs(run_capture, fixture_dir):
    a = {(r["seq"], r["guard"]) for r in parse(run_capture(fixture_dir / "gemm.c").stderr)}
    b = {(r["seq"], r["guard"]) for r in parse(run_capture(fixture_dir / "gemm.c").stderr)}
    assert a == b


def test_bisect_index_is_dense_over_gated_passes(run_capture, fixture_dir):
    """Required passes are not gated (-1); vetoable ones number 1..N with no gaps."""
    recs = parse(run_capture(fixture_dir / "gemm.c").stderr)
    gated = [r["bisect"] for r in recs if r["required"] == 0]
    required = [r["bisect"] for r in recs if r["required"] == 1]
    assert all(b == -1 for b in required)
    assert gated == list(range(1, len(gated) + 1)), "bisect indices are not dense"


def test_guard_hash_changes_when_input_changes(run_capture, fixture_dir, tmp_path):
    """A stale address must be detectable."""
    src = (fixture_dir / "gemm.c").read_text()
    mod = tmp_path / "gemm_mod.c"
    mod.write_text(src.replace("#define NK 64", "#define NK 65"))
    orig = {r["guard"] for r in parse(run_capture(fixture_dir / "gemm.c").stderr)}
    other = {r["guard"] for r in parse(run_capture(mod).stderr)}
    assert orig != other
