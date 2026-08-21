from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Equivalence:
    stdout_identical: bool
    exit_code_identical: bool
    detail: str = ""

    @property
    def diverged(self) -> bool:
        return not (self.stdout_identical and self.exit_code_identical)


def verify_module(ir_path: Path) -> bool:
    """Run LLVM's own verifier over a .ll or .bc file."""
    result = subprocess.run(
        ["opt", "-passes=verify", "-disable-output", str(ir_path)],
        capture_output=True, text=True)
    return result.returncode == 0


def verify_equivalence(baseline_exe: Path, variant_exe: Path,
                       args: tuple = ()) -> Equivalence:
    """Run both binaries and compare stdout and exit code exactly.

    Spec 5.5: a divergence is a genuine bug and is surfaced, never hidden.
    """
    a = subprocess.run([str(baseline_exe), *args], capture_output=True, text=True)
    b = subprocess.run([str(variant_exe), *args], capture_output=True, text=True)

    stdout_same = a.stdout == b.stdout
    code_same = a.returncode == b.returncode
    detail = ""
    if not stdout_same:
        detail = f"stdout differs:\n  baseline: {a.stdout[:200]!r}\n  variant:  {b.stdout[:200]!r}"
    elif not code_same:
        detail = f"exit code differs: baseline {a.returncode}, variant {b.returncode}"
    return Equivalence(stdout_identical=stdout_same,
                       exit_code_identical=code_same, detail=detail)
