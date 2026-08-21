from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .launch import LaunchConfig, build_command, normalised_env
from .toolchain import find_toolchain

_FN = re.compile(r"^fn=\(\d+\)(?:\s+(.*))?$")
_SUMMARY = re.compile(r"^summary:\s+(\d+)")


@dataclass
class CallgrindResult:
    total_ir: int
    per_function: dict = field(default_factory=dict)
    out_path: Path | None = None

    @property
    def kind(self) -> str:
        return "exact"      # zero variance: never sampled


def parse_callgrind_out(path) -> tuple[int, dict]:
    """Parse callgrind.out directly. callgrind_annotate is not needed."""
    total = 0
    per_function: dict[str, int] = {}
    current = None
    names: dict[str, str] = {}
    for line in Path(path).read_text(errors="replace").splitlines():
        m = _SUMMARY.match(line)
        if m:
            total = int(m.group(1))
            continue
        m = _FN.match(line)
        if m:
            # Callgrind compresses names: "fn=(3) name" defines, "fn=(3)" refers.
            ident = line.split(")")[0][4:]
            if m.group(1):
                names[ident] = m.group(1)
            current = names.get(ident, f"fn{ident}")
            per_function.setdefault(current, 0)
            continue
        if current and line and line[0].isdigit():
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                per_function[current] += int(parts[1])
    return total, per_function


def run_callgrind(exe, args: tuple = (), cfg: LaunchConfig = LaunchConfig()
                  ) -> CallgrindResult:
    """Measure instruction reads exactly. One run is statistically sufficient."""
    tc = find_toolchain()
    if not tc.has_valgrind:
        raise RuntimeError("valgrind not available; run scripts/stage-tools.sh")

    out = Path(tempfile.mkdtemp()) / "callgrind.out"
    argv = [str(tc.valgrind_bin), "--tool=callgrind",
            f"--callgrind-out-file={out}", "--quiet", str(exe), *args]

    env = normalised_env(cfg)
    env.update(tc.callgrind_env())
    subprocess.run(build_command(argv, cfg), capture_output=True, text=True,
                   env=env, check=True)

    total, per_function = parse_callgrind_out(out)
    return CallgrindResult(total_ir=total, per_function=per_function, out_path=out)
