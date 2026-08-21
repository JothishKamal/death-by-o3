from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SIZE_ROW = re.compile(r"^(\.\S+)\s+(\d+)\s+\d+")
_SLOT = re.compile(r"^\s*Offset: \[SP([+-]\d+)\],\s+Type: (\w+),\s+"
                   r"Align: (\d+),\s+Size: (\d+)")
_FUNC = re.compile(r"^Function:\s+(\S+)")


@dataclass
class SlotInfo:
    count: int = 0
    total_bytes: int = 0


@dataclass
class SpillCost:
    num_spills: int = 0
    num_reloads: int = 0
    total_spills_cost: float = 0.0
    total_reloads_cost: float = 0.0
    allocator_supported: bool = False


def section_sizes(obj) -> dict:
    result = subprocess.run(["llvm-size", "--format=sysv", str(Path(obj))],
                            capture_output=True, text=True, check=True)
    sizes = {}
    for line in result.stdout.splitlines():
        m = _SIZE_ROW.match(line)
        if m:
            sizes[m.group(1)] = int(m.group(2))
    return sizes


def spill_slots(src, flags: tuple = ()) -> dict:
    """Parse -Rpass-analysis=stack-frame-layout. STDERR ONLY -- not in the YAML."""
    result = subprocess.run(
        ["clang", "-O2", "-Rpass-analysis=stack-frame-layout", *flags,
         "-c", str(Path(src)), "-o", "/dev/null"],
        capture_output=True, text=True)
    out: dict[str, SlotInfo] = {}
    current = None
    for line in result.stderr.splitlines():
        m = _FUNC.search(line)
        if m:
            current = m.group(1)
            out.setdefault(current, SlotInfo())
            continue
        m = _SLOT.match(line)
        if m and current and m.group(2) == "Spill":
            out[current].count += 1
            out[current].total_bytes += int(m.group(4))
    return out


def spill_cost(src, flags: tuple = ()) -> dict:
    """Parse the regalloc remark. Emitted by RegAllocGreedy ONLY.

    The Total*Cost fields are block-frequency weighted -- that is LLVM's own
    notion of spill severity, and the honest replacement for the phrase
    "register pressure", which LLVM does not compute at all.
    """
    tmp = Path(tempfile.mkdtemp())
    yaml_path = tmp / "opt.yaml"
    subprocess.run(
        ["clang", "-O2", "-fsave-optimization-record",
         f"-foptimization-record-file={yaml_path}", *flags,
         "-c", str(Path(src)), "-o", str(tmp / "o.o")],
        capture_output=True, text=True)
    if not yaml_path.exists():
        return {}

    out: dict[str, SpillCost] = {}
    func = None
    in_regalloc = False
    for line in yaml_path.read_text().splitlines():
        s = line.strip()
        if s.startswith("--- !"):
            in_regalloc = False
            func = None
        elif s.startswith("Pass:"):
            in_regalloc = s.split(":", 1)[1].strip().strip("'\"") == "regalloc"
        elif s.startswith("Function:") and in_regalloc:
            func = s.split(":", 1)[1].strip().strip("'\"")
            out.setdefault(func, SpillCost(allocator_supported=True))
        elif in_regalloc and func and "- " in s and ":" in s:
            key, _, val = s.lstrip("- ").partition(":")
            val = val.strip().strip("'\"")
            c = out[func]
            try:
                if key == "NumSpills":        c.num_spills = int(val)
                elif key == "NumReloads":     c.num_reloads = int(val)
                elif key == "TotalSpillsCost":  c.total_spills_cost = float(val)
                elif key == "TotalReloadsCost": c.total_reloads_cost = float(val)
            except ValueError:
                pass
    return out
