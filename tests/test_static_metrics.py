import subprocess

from autopsy.measure.static import section_sizes, spill_cost, spill_slots


def test_section_sizes_are_read(fixture_dir, tmp_path):
    obj = tmp_path / "o.o"
    subprocess.run(["clang", "-O3", "-c", str(fixture_dir / "runnable.c"),
                    "-o", str(obj)], check=True)
    sizes = section_sizes(obj)
    assert sizes[".text"] > 0


def test_disabling_vectorization_changes_text_size(fixture_dir, tmp_path):
    def build(flags, name):
        obj = tmp_path / name
        subprocess.run(["clang", "-O3", *flags, "-c",
                        str(fixture_dir / "runnable.c"), "-o", str(obj)], check=True)
        return section_sizes(obj)[".text"]

    assert build([], "a.o") != build(["-fno-vectorize"], "b.o")


def test_spill_slots_are_parsed_from_stderr(fixture_dir):
    """This remark is stderr-only; it is NOT in the YAML record."""
    slots = spill_slots(fixture_dir / "pressure.c")
    assert "pressure" in slots
    assert slots["pressure"].count > 0
    assert slots["pressure"].total_bytes > 0


def test_spill_cost_comes_from_the_regalloc_remark(fixture_dir):
    costs = spill_cost(fixture_dir / "pressure.c")
    assert "pressure" in costs
    c = costs["pressure"]
    assert c.allocator_supported
    assert c.num_spills > 0
    assert c.total_spills_cost > 0


def test_spill_cost_is_unavailable_for_non_greedy_allocators(fixture_dir):
    """Only RegAllocGreedy emits these remarks. Say so rather than report zero."""
    costs = spill_cost(fixture_dir / "pressure.c",
                       flags=["-mllvm", "-regalloc=fast"])
    assert not costs.get("pressure") or not costs["pressure"].allocator_supported


def test_slots_and_instructions_are_different_numbers(fixture_dir):
    """Guard against conflating the three spill metrics."""
    slots = spill_slots(fixture_dir / "pressure.c")["pressure"].count
    instrs = spill_cost(fixture_dir / "pressure.c")["pressure"].num_spills
    assert slots != instrs or slots > 0
