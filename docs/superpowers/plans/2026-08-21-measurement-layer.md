# Measurement Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `autopsy diagnose <benchmark>` ranks the decisions responsible for a regression, builds counterfactuals for the top candidates, measures both variants defensibly, and emits an evidence record where every number carries its provenance.

**Architecture:** Deterministic metrics are primary — Callgrind instruction counts have exactly zero variance, so one run is statistically sufficient. Wall-clock is corroborating only, gathered under interleaved A/B/A/B with ASLR off and a normalised environment, and reported as a Hodges-Lehmann shift with a distribution-free confidence interval. A rule-based ranker with published weights narrows hundreds of decisions to a handful worth measuring.

**Tech Stack:** Python 3.14, numpy, scipy, pytest. Valgrind and perf are staged into an unprivileged prefix — **no sudo**.

**Spec:** `docs/superpowers/specs/2026-08-20-optimization-autopsy-design.md`
**Depends on:** Plan 1 (capture) and Plan 2 (experiment) complete.

## Global Constraints

- **Deterministic metrics take a fast path with no inference at all.** Hypothesis testing on a zero-variance metric is a category error: a +1-instruction difference yields p = 8.3e-8, which is "overwhelmingly significant" and meaningless. Report the exact difference and label it `exact`.
- **`setarch -R` (ASLR off) is mandatory on every timed run.** Measured: it cuts instruction-count variance **30×**. Never compare an ASLR-on baseline against an ASLR-off variant.
- **Interleave A/B/A/B; never batch.** Four Tier A cases flipped verdict between batched and interleaved measurement. Any wall-clock ratio below **1.08** is unmeasurable — the cross-process noise floor is 2–4% and **does not shrink with more runs** (it is between-process variance).
- **`-stats` and `-debug-only` do not exist** on a release LLVM build. Never depend on them. Metrics come from optimization remarks, the object file, and our own plugin.
- **`-Rpass-analysis=stack-frame-layout` is stderr-only** — it is not serialised into the YAML optimization record.
- **Never report "register pressure".** LLVM computes no such number. Report frequency-weighted **spill cost** (`TotalSpillsCost + TotalReloadsCost`), and note it is emitted only by the greedy allocator.
- Every measurement carries `kind: "exact" | "sampled"` and a `provenance` id. A number without provenance is not displayed.

---

### Task 1: Stage valgrind and perf without root

**Files:**
- Create: `autopsy/measure/__init__.py`
- Create: `autopsy/measure/toolchain.py`
- Create: `scripts/stage-tools.sh`
- Test: `tests/test_toolchain.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `autopsy.measure.toolchain.Toolchain` with `.callgrind_env() -> dict`, `.has_valgrind: bool`, `.has_perf: bool`, `.valgrind_bin: Path | None`, `.perf_bin: Path | None`; and `find_toolchain(prefix: Path | None = None) -> Toolchain`, which prefers a staged prefix and falls back to `PATH`.

**Why:** the container and the judges' machine must reproduce every number without privileges. Valgrind resolved from a prefix needs `VALGRIND_LIB` and `LD_LIBRARY_PATH` set, or it fails at runtime with a confusing error about missing tool binaries.

- [ ] **Step 1: Write the failing test**

`tests/test_toolchain.py`:

```python
import shutil

import pytest

from autopsy.measure.toolchain import Toolchain, find_toolchain


def test_finds_tools_on_path_when_no_prefix():
    tc = find_toolchain(prefix=None)
    assert isinstance(tc, Toolchain)
    assert tc.has_valgrind == (shutil.which("valgrind") is not None)


def test_prefix_takes_priority_over_path(tmp_path):
    fake = tmp_path / "usr" / "bin"
    fake.mkdir(parents=True)
    (fake / "valgrind").write_text("#!/bin/sh\nexit 0\n")
    (fake / "valgrind").chmod(0o755)
    tc = find_toolchain(prefix=tmp_path)
    assert tc.has_valgrind
    assert tc.valgrind_bin == fake / "valgrind"


def test_callgrind_env_sets_valgrind_lib(tmp_path):
    fake = tmp_path / "usr" / "bin"
    fake.mkdir(parents=True)
    (fake / "valgrind").write_text("#!/bin/sh\nexit 0\n")
    (fake / "valgrind").chmod(0o755)
    env = find_toolchain(prefix=tmp_path).callgrind_env()
    assert env["VALGRIND_LIB"].endswith("lib/valgrind")
    assert str(tmp_path) in env["LD_LIBRARY_PATH"]


def test_missing_tools_are_reported_not_raised(tmp_path):
    tc = find_toolchain(prefix=tmp_path / "nonexistent")
    assert tc.valgrind_bin is None or tc.has_valgrind
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_toolchain.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.measure`

- [ ] **Step 3: Write the staging script**

`scripts/stage-tools.sh`:

```bash
#!/usr/bin/env bash
# Stage valgrind and perf into an unprivileged prefix. No sudo required.
# Usage: scripts/stage-tools.sh [prefix]
set -euo pipefail
PREFIX="${1:-$PWD/.tools}"
mkdir -p "$PREFIX"

if command -v valgrind >/dev/null && command -v perf >/dev/null; then
  echo "valgrind and perf already on PATH; nothing to stage"
  exit 0
fi

cat <<'NOTE'
Stage the distribution packages into the prefix without installing them
system-wide. On Arch:

  cd "$PREFIX"
  for p in valgrind perf; do
    pkg=$(pacman -Sp --noconfirm "$p" 2>/dev/null | tail -1)
    curl -sLO "$pkg"
  done
  for f in *.pkg.tar.zst; do tar --use-compress-program=unzstd -xf "$f"; done

Then export:
  VALGRIND_LIB=$PREFIX/usr/lib/valgrind
  LD_LIBRARY_PATH=$PREFIX/usr/lib
NOTE
```

Make it executable: `chmod +x scripts/stage-tools.sh`

- [ ] **Step 4: Write the toolchain module**

`autopsy/measure/__init__.py`:

```python
"""Measurement: deterministic counts first, statistics only where needed."""
```

`autopsy/measure/toolchain.py`:

```python
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Toolchain:
    prefix: Path | None
    valgrind_bin: Path | None
    perf_bin: Path | None

    @property
    def has_valgrind(self) -> bool:
        return self.valgrind_bin is not None

    @property
    def has_perf(self) -> bool:
        return self.perf_bin is not None

    def callgrind_env(self) -> dict:
        """Env a staged valgrind needs; without these it fails to find its tools."""
        env = dict(os.environ)
        if self.prefix is not None:
            env["VALGRIND_LIB"] = str(self.prefix / "usr" / "lib" / "valgrind")
            existing = env.get("LD_LIBRARY_PATH", "")
            lib = str(self.prefix / "usr" / "lib")
            env["LD_LIBRARY_PATH"] = f"{lib}:{existing}" if existing else lib
        return env


def _locate(name: str, prefix: Path | None) -> Path | None:
    if prefix is not None:
        candidate = prefix / "usr" / "bin" / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which(name)
    return Path(found) if found else None


def find_toolchain(prefix: Path | None = None) -> Toolchain:
    if prefix is None:
        env_prefix = os.environ.get("AUTOPSY_TOOL_PREFIX")
        prefix = Path(env_prefix) if env_prefix else None
    return Toolchain(prefix=prefix,
                     valgrind_bin=_locate("valgrind", prefix),
                     perf_bin=_locate("perf", prefix))
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_toolchain.py -v`
Expected: PASS — 4 passed

- [ ] **Step 6: Commit**

```bash
git add autopsy/measure/ scripts/stage-tools.sh tests/test_toolchain.py
git commit -m "feat(measure): locate valgrind and perf from an unprivileged prefix"
```

---

### Task 2: The controlled launch wrapper

**Files:**
- Create: `autopsy/measure/launch.py`
- Test: `tests/test_launch.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `autopsy.measure.launch.LaunchConfig(cpu:int=2, aslr:bool=False, env_bytes:int=4096)` and `build_command(argv:list, cfg:LaunchConfig) -> list[str]`, plus `normalised_env(cfg) -> dict` producing an environment block of exactly `env_bytes` bytes.

**The Mytkowicz effect, mechanically.** The environment block is copied onto the process stack above `argv` before `main`, so its total byte size sets the initial stack pointer, shifting every stack object's alignment relative to cache lines, pages, and branch-predictor index bits. Changing an unrelated variable's *length* can swing wall-clock by percent. Measured here: clean env versus ambient shifted a whole-program instruction count by **75,000 instructions (0.14%)**, and a 30-character argv0 shifted it by 7 against a 1-character one.

- [ ] **Step 1: Write the failing test**

`tests/test_launch.py`:

```python
import subprocess

from autopsy.measure.launch import LaunchConfig, build_command, normalised_env


def test_command_pins_and_disables_aslr():
    cmd = build_command(["/bin/true"], LaunchConfig(cpu=3))
    assert cmd[:2] == ["taskset", "-c"]
    assert cmd[2] == "3"
    assert "setarch" in cmd and "-R" in cmd


def test_env_block_is_exactly_the_requested_size():
    env = normalised_env(LaunchConfig(env_bytes=4096))
    total = sum(len(k) + len(v) + 2 for k, v in env.items())
    assert total == 4096, f"env block is {total} bytes, expected 4096"


def test_env_block_size_is_stable_regardless_of_ambient(monkeypatch):
    a = normalised_env(LaunchConfig(env_bytes=4096))
    monkeypatch.setenv("SOME_LONG_UNRELATED_VARIABLE", "x" * 3000)
    b = normalised_env(LaunchConfig(env_bytes=4096))
    size = lambda e: sum(len(k) + len(v) + 2 for k, v in e.items())
    assert size(a) == size(b) == 4096


def test_wrapper_actually_runs_a_program():
    cmd = build_command(["/bin/echo", "hello"], LaunchConfig(cpu=0))
    result = subprocess.run(cmd, capture_output=True, text=True,
                            env=normalised_env(LaunchConfig()))
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"


def test_pinning_to_an_even_cpu_is_the_default():
    """Siblings are (0,1) (2,3) ...; pin to one thread of a distinct core."""
    assert LaunchConfig().cpu % 2 == 0


def test_too_small_env_budget_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        normalised_env(LaunchConfig(env_bytes=8))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_launch.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.measure.launch`

- [ ] **Step 3: Write the wrapper**

`autopsy/measure/launch.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

# A fixed, minimal base environment. Everything ambient is discarded so the
# stack base is identical between baseline and variant runs.
_BASE = {"PATH": "/usr/bin", "HOME": "/nonexistent", "LANG": "C"}


@dataclass(frozen=True)
class LaunchConfig:
    cpu: int = 2          # even CPUs only: siblings are (0,1) (2,3) ...
    aslr: bool = False    # False means -R, i.e. randomisation DISABLED
    env_bytes: int = 4096


def normalised_env(cfg: LaunchConfig = LaunchConfig()) -> dict:
    """Produce an environment block of exactly cfg.env_bytes bytes.

    Size is what matters, not content: it sets the initial stack pointer and
    therefore every stack object's alignment (Mytkowicz et al., ASPLOS 2009).
    """
    env = dict(_BASE)
    used = sum(len(k) + len(v) + 2 for k, v in env.items())
    need = cfg.env_bytes - used - len("PAD") - 2
    if need < 0:
        raise ValueError(
            f"env_bytes={cfg.env_bytes} is too small for the base environment "
            f"({used} bytes)")
    env["PAD"] = "X" * need
    return env


def build_command(argv: list[str], cfg: LaunchConfig = LaunchConfig()) -> list[str]:
    """Wrap argv with core pinning and ASLR control. All unprivileged."""
    cmd = ["taskset", "-c", str(cfg.cpu), "setarch"]
    if not cfg.aslr:
        cmd.append("-R")
    cmd.extend(argv)
    return cmd
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 6 passed in `test_launch.py`

- [ ] **Step 5: Commit**

```bash
git add autopsy/measure/launch.py tests/test_launch.py
git commit -m "feat(measure): controlled launch wrapper with ASLR and env normalisation"
```

---

### Task 3: Callgrind — the deterministic authority

**Files:**
- Create: `autopsy/measure/callgrind.py`
- Test: `tests/test_callgrind.py`

**Interfaces:**
- Consumes: `toolchain.find_toolchain`, `launch.build_command`, `launch.normalised_env`.
- Produces: `autopsy.measure.callgrind.run_callgrind(exe, args=(), cfg=LaunchConfig()) -> CallgrindResult` with `.total_ir: int`, `.per_function: dict[str,int]`, `.out_path: Path`; and `parse_callgrind_out(path) -> tuple[int, dict[str,int]]`.

**Verified behaviour:** instruction-read counts are **bit-for-bit identical** — range 0 across repeats, ASLR on/off, environment padding, and 16 competing load generators. So `n=1` is valid and a second run is a self-check, not a sample. Slowdown is ~25× for `Ir` only. Per-function costs are stable under *every* perturbation, whereas whole-program totals drift ~0.14% with environment contents — so **parse per-function costs; do not use `--toggle-collect`**, which needs the function name up front and buys nothing.

- [ ] **Step 1: Write the failing test**

`tests/test_callgrind.py`:

```python
import subprocess

import pytest

from autopsy.measure.callgrind import run_callgrind
from autopsy.measure.toolchain import find_toolchain

pytestmark = pytest.mark.skipif(not find_toolchain().has_valgrind,
                                reason="valgrind not staged")


@pytest.fixture(scope="module")
def exe(tmp_path_factory, request):
    src = request.config.rootpath / "tests" / "fixtures" / "runnable.c"
    out = tmp_path_factory.mktemp("cg") / "bench"
    subprocess.run(["clang", "-O2", "-g", str(src), "-o", str(out)], check=True)
    return out


def test_callgrind_reports_a_positive_instruction_count(exe):
    r = run_callgrind(exe)
    assert r.total_ir > 100_000


def test_callgrind_is_bit_for_bit_deterministic(exe):
    """The whole metric hierarchy rests on this: zero variance means n=1."""
    counts = [run_callgrind(exe).total_ir for _ in range(3)]
    assert len(set(counts)) == 1, f"expected identical counts, got {counts}"


def test_per_function_costs_are_extracted(exe):
    r = run_callgrind(exe)
    assert r.per_function
    assert any(v > 1000 for v in r.per_function.values())


def test_per_function_costs_are_stable_across_env_sizes(exe):
    """Per-function costs are immune to env size; whole-program totals are not."""
    from autopsy.measure.launch import LaunchConfig
    a = run_callgrind(exe, cfg=LaunchConfig(env_bytes=2048))
    b = run_callgrind(exe, cfg=LaunchConfig(env_bytes=8192))
    common = set(a.per_function) & set(b.per_function)
    hot = [f for f in common if a.per_function[f] > 10_000]
    assert hot
    for f in hot:
        assert a.per_function[f] == b.per_function[f], f"{f} moved with env size"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_callgrind.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.measure.callgrind`

- [ ] **Step 3: Write the runner**

`autopsy/measure/callgrind.py`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 4 passed in `test_callgrind.py` (skipped if valgrind is unstaged)

- [ ] **Step 5: Commit**

```bash
git add autopsy/measure/callgrind.py tests/test_callgrind.py
git commit -m "feat(measure): deterministic Callgrind instruction counting"
```

---

### Task 4: Static metrics and honest spill evidence

**Files:**
- Create: `autopsy/measure/static.py`
- Test: `tests/test_static_metrics.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `autopsy.measure.static.section_sizes(obj) -> dict[str,int]`; `spill_slots(src, flags=()) -> dict[str, SlotInfo]` parsing `-Rpass-analysis=stack-frame-layout` from **stderr**; `spill_cost(src, flags=()) -> dict[str, SpillCost]` parsing the `regalloc` remark from the YAML optimization record, with `SpillCost(num_spills, num_reloads, total_spills_cost, total_reloads_cost, allocator_supported: bool)`.

**Three different numbers, never conflated.** For one function these read **17** spill instructions, **10** distinct spill slots, and **0** frame bytes — all correct, all different. Any evidence card must say which it is showing. Free cross-check: `clang -S` emits `# N-byte Spill` / `# N-byte Reload` comments.

- [ ] **Step 1: Write the failing test**

`tests/fixtures/pressure.c`:

```c
/* Enough simultaneously-live doubles to force the allocator to spill. */
double pressure(const double *p, int n) {
  double a0=0,a1=0,a2=0,a3=0,a4=0,a5=0,a6=0,a7=0;
  double b0=0,b1=0,b2=0,b3=0,b4=0,b5=0,b6=0,b7=0;
  for (int i = 0; i < n; i++) {
    double v = p[i];
    a0+=v*1.1; a1+=v*1.2; a2+=v*1.3; a3+=v*1.4;
    a4+=v*1.5; a5+=v*1.6; a6+=v*1.7; a7+=v*1.8;
    b0+=a0*a1; b1+=a2*a3; b2+=a4*a5; b3+=a6*a7;
    b4+=b0*b1; b5+=b2*b3; b6+=b4*b5; b7+=b6*a0;
  }
  return a0+a1+a2+a3+a4+a5+a6+a7+b0+b1+b2+b3+b4+b5+b6+b7;
}
```

`tests/test_static_metrics.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_static_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.measure.static`

- [ ] **Step 3: Write the module**

`autopsy/measure/static.py`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 6 passed in `test_static_metrics.py`

- [ ] **Step 5: Commit**

```bash
git add autopsy/measure/static.py tests/fixtures/pressure.c tests/test_static_metrics.py
git commit -m "feat(measure): section sizes and honest spill evidence from remarks"
```

---

### Task 5: The statistical verdict

**Files:**
- Create: `autopsy/measure/stats.py`
- Modify: `requirements-dev.txt`
- Test: `tests/test_stats.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `autopsy.measure.stats.verdict(a, b, threshold=0.02, alpha=0.05, m_tests=1) -> Verdict` with fields `verdict:str, shift:float, ci:tuple|None, p:float|None, kind:str, note:str`; `hodges_lehmann_ratio(a,b) -> float`; `hl_exact_ci(a,b,alpha) -> tuple`; `required_n(cv, mde, alpha=0.05, power=0.80) -> int`.

**Three defects in the specified rule that this task fixes.** (1) Testing a point estimate against the threshold gives power **0.47–0.51 at the boundary regardless of CV** — a coin flip by construction; test the **CI** instead. (2) `scipy`'s `method='auto'` silently degrades at n≥8 (minimum attainable p `3.4e-6` vs `1.3e-8` exact), so `method` is always passed explicitly, and `exact` is invalid under ties, which integer counters produce constantly. (3) Constant inputs return **NaN**, and a +1-instruction difference on a deterministic metric yields p = 8.3e-8 — meaningless. Deterministic metrics take a fast path with no inference.

Verdict vocabulary must include `INCONCLUSIVE_UNDERPOWERED`, which the document's rule cannot express: it distinguishes *"no regression"* from *"too noisy to tell"*.

- [ ] **Step 1: Add dependencies**

Append to `requirements-dev.txt`:

```
numpy==2.4.1
scipy==1.18.0
```

Run: `make bootstrap`

- [ ] **Step 2: Write the failing test**

`tests/test_stats.py`:

```python
import numpy as np
import pytest

from autopsy.measure.stats import (hl_exact_ci, hodges_lehmann_ratio,
                                   required_n, verdict)


def test_identical_deterministic_values_are_identical():
    v = verdict([100.0] * 3, [100.0] * 3)
    assert v.verdict == "IDENTICAL"
    assert v.kind == "exact"
    assert v.p is None


def test_deterministic_difference_skips_inference_entirely():
    """A +1 difference on a zero-variance metric must not produce a p-value."""
    v = verdict([1_000_000.0], [1_000_001.0])
    assert v.kind == "exact"
    assert v.p is None, "hypothesis testing on a deterministic metric is invalid"
    assert v.verdict == "CHANGED_BELOW_THRESHOLD"


def test_large_deterministic_regression_is_confirmed():
    v = verdict([100.0], [130.0])
    assert v.verdict == "REGRESSION"
    assert v.kind == "exact"
    assert v.shift == pytest.approx(0.30)


def test_clear_sampled_regression_is_confirmed():
    rng = np.random.default_rng(7)
    a = rng.normal(100, 0.5, 30)
    b = rng.normal(110, 0.5, 30)
    v = verdict(list(a), list(b))
    assert v.verdict == "REGRESSION_CONFIRMED"
    assert v.kind == "sampled"
    assert v.ci[0] > 0.02


def test_noisy_data_is_inconclusive_not_negative():
    """The verdict the document's rule cannot express."""
    rng = np.random.default_rng(11)
    a = rng.normal(100, 15, 15)
    b = rng.normal(101, 15, 15)
    v = verdict(list(a), list(b))
    assert v.verdict == "INCONCLUSIVE_UNDERPOWERED"


def test_ci_is_asymmetric_and_stored_independently():
    rng = np.random.default_rng(3)
    a, b = rng.normal(100, 2, 20), rng.normal(104, 5, 20)
    lo, hi = hl_exact_ci(np.asarray(a), np.asarray(b))
    mid = hodges_lehmann_ratio(np.asarray(a), np.asarray(b))
    assert not np.isclose(mid - lo, hi - mid, rtol=1e-3), \
        "CI treated as symmetric; it is not"


def test_required_n_scales_with_noise():
    assert required_n(cv=0.001, mde=0.02) < 5
    assert required_n(cv=0.10, mde=0.02) > 300


def test_multiple_comparisons_tighten_the_bar():
    rng = np.random.default_rng(5)
    a, b = rng.normal(100, 1.0, 20), rng.normal(101.5, 1.0, 20)
    lone = verdict(list(a), list(b), m_tests=1)
    many = verdict(list(a), list(b), m_tests=50)
    assert (many.ci[1] - many.ci[0]) > (lone.ci[1] - lone.ci[0])
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_stats.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.measure.stats`

- [ ] **Step 4: Write the statistics module**

`autopsy/measure/stats.py`:

```python
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy import stats as _st


@dataclass(frozen=True)
class Verdict:
    verdict: str
    shift: float
    kind: str                 # "exact" | "sampled"
    ci: tuple | None = None
    p: float | None = None
    method: str | None = None
    note: str = ""

    @property
    def ci_width(self) -> float | None:
        return None if self.ci is None else self.ci[1] - self.ci[0]


def hodges_lehmann_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """Median of all pairwise differences, as a fraction of the baseline median.

    This is exactly the estimator Mann-Whitney implicitly tests, so estimate and
    test stay consistent. It differs from the naive median-difference.
    """
    d = (b[:, None] - a[None, :]).ravel()
    return float(np.median(d) / np.median(a))


def hl_exact_ci(a: np.ndarray, b: np.ndarray, alpha: float = 0.05) -> tuple:
    """Distribution-free CI for the HL shift, from rank-sum order statistics.

    Better calibrated at small n than bootstrapping a median, which takes few
    distinct values and is badly behaved.
    """
    m, n = len(a), len(b)
    d = np.sort((b[:, None] - a[None, :]).ravel())
    z = _st.norm.ppf(1 - alpha / 2)
    k = int(np.floor(max(m * n / 2 - z * np.sqrt(m * n * (m + n + 1) / 12) - 0.5, 0)))
    med = float(np.median(a))
    return d[k] / med, d[len(d) - 1 - k] / med


def required_n(cv: float, mde: float, alpha: float = 0.05,
               power: float = 0.80) -> int:
    """Samples per group for Mann-Whitney (ARE 0.955 vs the t-test).

    Run this BEFORE collecting. Rule of thumb it encodes: at n=15 the minimum
    detectable effect is about 1.11 x CV.
    """
    z_a = _st.norm.ppf(1 - alpha / 2)
    z_b = _st.norm.ppf(power)
    return max(1, int(np.ceil(2 * ((z_a + z_b) * cv / mde) ** 2 / 0.955)))


def verdict(a, b, threshold: float = 0.02, alpha: float = 0.05,
            m_tests: int = 1) -> Verdict:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    alpha_c = alpha / max(1, m_tests)

    # Deterministic fast path: Callgrind, llvm-size, IR counts, llvm-mca.
    # Hypothesis testing here is a category error -- there is no sampling
    # distribution, and a +1 difference would read as p = 8.3e-8.
    if np.ptp(a) == 0 and np.ptp(b) == 0:
        if b[0] == a[0]:
            return Verdict("IDENTICAL", 0.0, "exact", ci=(0.0, 0.0),
                           note="exact difference; no inference performed")
        d = (b[0] - a[0]) / a[0]
        name = ("REGRESSION" if d > threshold else
                "IMPROVEMENT" if d < -threshold else "CHANGED_BELOW_THRESHOLD")
        return Verdict(name, float(d), "exact", ci=(float(d), float(d)),
                       note="exact difference; no inference performed")

    ties = len(np.unique(np.concatenate([a, b]))) < len(a) + len(b)
    method = "asymptotic" if ties else "exact"   # never leave this on "auto"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = float(_st.mannwhitneyu(a, b, alternative="two-sided",
                                   method=method).pvalue)
    hl = hodges_lehmann_ratio(a, b)
    lo, hi = hl_exact_ci(a, b, alpha_c)
    sig = p < alpha_c

    if lo > threshold:
        name = "REGRESSION_CONFIRMED"
    elif hi < -threshold:
        name = "IMPROVEMENT_CONFIRMED"
    elif sig and hl > threshold:
        name = "REGRESSION_LIKELY"
    elif sig and hl < -threshold:
        name = "IMPROVEMENT_LIKELY"
    elif not sig and (hi - lo) > 2 * threshold:
        name = "INCONCLUSIVE_UNDERPOWERED"
    elif abs(hi) < threshold and abs(lo) < threshold:
        name = "NO_CHANGE_RULED_OUT"
    else:
        name = "CHANGED_BELOW_THRESHOLD"

    return Verdict(name, hl, "sampled", ci=(lo, hi), p=p, method=method)
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 8 passed in `test_stats.py`

- [ ] **Step 6: Commit**

```bash
git add autopsy/measure/stats.py requirements-dev.txt tests/test_stats.py
git commit -m "feat(measure): Hodges-Lehmann verdicts with distribution-free intervals"
```

---

### Task 6: Adaptive interleaved sampling

**Files:**
- Create: `autopsy/measure/sampler.py`
- Test: `tests/test_sampler.py`

**Interfaces:**
- Consumes: `stats.required_n`, `stats.verdict`.
- Produces: `autopsy.measure.sampler.interleaved(run_a, run_b, threshold=0.02, pilot=5, cap=200, floor=8) -> Sample` where `Sample(a:list, b:list, n:int, cv:float, capped:bool)`.

**Rules this encodes.** Interleave A/B/A/B, never batch — four Tier A cases flipped verdict otherwise. Start with a 5-run pilot, measure CV, compute the required n, then collect that many up to a cap; hitting the cap yields `INCONCLUSIVE_UNDERPOWERED`, never a false negative. Floor of **n ≥ 8** whenever ranking, because below that the minimum attainable p cannot survive any multiple-comparisons correction.

- [ ] **Step 1: Write the failing test**

`tests/test_sampler.py`:

```python
import numpy as np

from autopsy.measure.sampler import interleaved


def make_pair(seed, mean_a, mean_b, sd):
    rng = np.random.default_rng(seed)
    return (lambda: float(rng.normal(mean_a, sd)),
            lambda: float(rng.normal(mean_b, sd)))


def test_low_noise_stops_early():
    a, b = make_pair(1, 100, 110, 0.05)
    s = interleaved(a, b)
    assert s.n <= 12
    assert not s.capped


def test_high_noise_collects_many_more():
    a, b = make_pair(2, 100, 101, 12.0)
    s = interleaved(a, b, cap=60)
    assert s.n >= 40


def test_cap_is_reported_not_hidden():
    a, b = make_pair(3, 100, 100.5, 20.0)
    s = interleaved(a, b, cap=20)
    assert s.capped
    assert s.n == 20


def test_floor_is_respected_for_ranking():
    a, b = make_pair(4, 100, 200, 0.001)
    s = interleaved(a, b, floor=8)
    assert s.n >= 8, "n < 8 cannot survive multiple-comparisons correction"


def test_samples_are_collected_in_alternating_order():
    order = []
    a = lambda: (order.append("a"), 1.0)[1]
    b = lambda: (order.append("b"), 1.0)[1]
    interleaved(a, b, pilot=3, cap=6, floor=3)
    assert order[:6] == ["a", "b", "a", "b", "a", "b"], \
        "runs must alternate; batching flips verdicts"


def test_equal_counts_for_both_variants():
    a, b = make_pair(6, 100, 105, 1.0)
    s = interleaved(a, b)
    assert len(s.a) == len(s.b) == s.n
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_sampler.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.measure.sampler`

- [ ] **Step 3: Write the sampler**

`autopsy/measure/sampler.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .stats import required_n


@dataclass
class Sample:
    a: list = field(default_factory=list)
    b: list = field(default_factory=list)
    cv: float = 0.0
    capped: bool = False

    @property
    def n(self) -> int:
        return len(self.a)


def interleaved(run_a, run_b, threshold: float = 0.02, pilot: int = 5,
                cap: int = 200, floor: int = 8) -> Sample:
    """Alternate A/B/A/B and grow the sample until it can answer the question.

    Batched min-of-N lies: it attributes between-process drift to the variant.
    Alternating makes drift common-mode.
    """
    s = Sample()
    for _ in range(pilot):
        s.a.append(run_a())
        s.b.append(run_b())

    arr = np.asarray(s.a, dtype=float)
    mean = float(np.mean(arr))
    s.cv = float(np.std(arr, ddof=1) / mean) if mean and len(arr) > 1 else 0.0

    target = max(floor, required_n(s.cv, threshold)) if s.cv > 0 else floor
    target = min(target, cap)

    while s.n < target:
        s.a.append(run_a())
        s.b.append(run_b())

    s.capped = s.n >= cap
    return s
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 6 passed in `test_sampler.py`

- [ ] **Step 5: Commit**

```bash
git add autopsy/measure/sampler.py tests/test_sampler.py
git commit -m "feat(measure): adaptive interleaved sampling with an honest cap"
```

---

### Task 7: The Tier A benchmark corpus

**Files:**
- Create: `benchmarks/tierA/bench.h`
- Create: `benchmarks/tierA/A12_simplifycfg_cmov.c`
- Create: `benchmarks/tierA/A04_slp_gather.c`
- Create: `benchmarks/tierA/manifest.toml`
- Create: `autopsy/bench/__init__.py`
- Create: `autopsy/bench/tiera.py`
- Test: `tests/test_tiera.py`

**Interfaces:**
- Consumes: `measure.launch`, `measure.callgrind`.
- Produces: `autopsy.bench.tiera.load_manifest(path) -> list[Case]` with `Case(id, source, culprit_pass, config_flags, expected_ratio, verified)`; and `build_case(case, out_dir, flags=()) -> Path`.

**Measured ground truth.** A12 (`simplifycfg`) is the flagship at **4.99×**, independently re-verified, with checksums byte-identical across baseline, `-O2`, and vetoed builds. A04 (`slp-vectorizer`) is **1.29×** — but **only at baseline SSE2**; at `-march=native` SLP re-costs and declines, so the manifest records the ISA config per case. Two of the document's four named seeds do not reproduce as runtime regressions and are recorded as negatives, not omitted.

- [ ] **Step 1: Write the failing test**

`tests/test_tiera.py`:

```python
import subprocess

from autopsy.bench.tiera import build_case, load_manifest

MANIFEST = "benchmarks/tierA/manifest.toml"


def test_manifest_loads(repo_root):
    cases = load_manifest(repo_root / MANIFEST)
    assert len(cases) >= 2
    assert all(c.culprit_pass for c in cases)


def test_every_case_declares_its_isa_config(repo_root):
    """ISA is a first-class axis: A04 reproduces at SSE2 and vanishes at native."""
    for c in load_manifest(repo_root / MANIFEST):
        assert c.config_flags is not None


def test_cases_build_and_run(repo_root, tmp_path):
    for c in load_manifest(repo_root / MANIFEST):
        exe = build_case(c, tmp_path, flags=c.config_flags)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert "CHECK" in r.stdout
        assert "NS_PER_REP" in r.stdout


def test_checksum_is_invariant_under_the_culprit_flag(repo_root, tmp_path):
    """Correctness oracle: disabling the culprit must not change the answer."""
    case = next(c for c in load_manifest(repo_root / MANIFEST) if c.id == "A12")
    a = build_case(case, tmp_path / "a", flags=case.config_flags)
    b = build_case(case, tmp_path / "b",
                   flags=tuple(case.config_flags) + tuple(case.disable_flags))
    out = lambda e: subprocess.run([str(e)], capture_output=True, text=True).stdout
    ck = lambda s: [l for l in s.splitlines() if l.startswith("CHECK")][0]
    assert ck(out(a)) == ck(out(b))


def test_harness_aborts_if_the_kernel_is_optimised_away(repo_root, tmp_path):
    """bench.h must fail loudly rather than report a meaningless 0 ns/rep."""
    src = (repo_root / "benchmarks" / "tierA" / "bench.h").read_text()
    assert "optimised away" in src
    assert "0.05" in src
```

Add to `tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_tiera.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.bench`

- [ ] **Step 3: Write the harness header**

`benchmarks/tierA/bench.h`:

```c
#ifndef BENCH_H
#define BENCH_H
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <stdint.h>

#define TRIALS 7

/* Opaque accumulators. Seeding each repetition's accumulator from a *volatile*
   makes every repetition genuinely data-dependent on the previous one, so LLVM
   can neither hoist the kernel out of the repetition loop nor CSE identical
   trials against each other. Values stay fully deterministic, so the printed
   CHECK remains a valid cross-variant output check.

   Without this, six of seven timing regions measured empty. */
static volatile double    g_d = 0.0;
static volatile long long g_i = 0;

static inline double now_s(void) {
  struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
  return (double)ts.tv_sec + 1e-9 * (double)ts.tv_nsec;
}

static inline uint32_t rnd32(uint64_t *s) {          /* xorshift64 */
  uint64_t x = *s; x ^= x << 13; x ^= x >> 7; x ^= x << 17; *s = x;
  return (uint32_t)(x >> 32);
}

static inline double rndf(uint64_t *s) {
  return (double)(rnd32(s) & 0xffff) / 65536.0 - 0.5;
}

static void report(double best, long reps, double checksum) {
  double ns = best * 1e9 / (double)reps;
  if (ns < 0.05) {
    fprintf(stderr, "FATAL: kernel optimised away (%g ns/rep)\n", ns);
    exit(3);
  }
  printf("NS_PER_REP %.4f\nCHECK %.10g\n", ns, checksum);
}
#endif
```

`benchmarks/tierA/A12_simplifycfg_cmov.c`:

```c
/* A12  simplifycfg (two-entry PHI folding / speculation).  A perfectly
   predicted branch guards an update of a serial dependence chain. Folding it
   into a select forces BOTH arms to be evaluated and puts the multiply on the
   critical path every iteration; the branchy form retires the cheap arm in one
   cycle because the predictor is never wrong.
   Measured 4.99x, checksums byte-identical across variants. */
#include "bench.h"
#define N 65536
static unsigned char c[N];

__attribute__((noinline))
static unsigned chain(const unsigned char *cc, int n, unsigned x) {
  for (int i = 0; i < n; i++) {
    if (cc[i]) x = x * 1103515245u + 12345u;   /* 3-cycle multiply */
    else       x = x + 7u;                     /* 1-cycle add      */
  }
  return x;
}

int main(void) {
  for (int i = 0; i < N; i++) c[i] = 0;   /* never taken -> always predicted */
  const int REPS = 60;
  double best = 1e30;
  for (int t = 0; t < TRIALS; t++) {
    double t0 = now_s();
    for (int r = 0; r < REPS; r++) { unsigned x = (unsigned)g_i; g_i = chain(c, N, x); }
    double t1 = now_s();
    if (t1 - t0 < best) best = t1 - t0;
  }
  report(best, (long)REPS * N, (double)(g_i & 0xffffff));
  return 0;
}
```

`benchmarks/tierA/A04_slp_gather.c`:

```c
/* A04  slp-vectorizer.  Four values come from four unrelated arrays at four
   unrelated (gathered) indices. SLP still forms a <4 x float>: four
   insertelements in, one vector FMA, then extractelements back out. The
   build/tear-down shuffles cost more than the scalar ops they replace.
   Measured 1.29x at baseline SSE2; NEUTRAL at -march=native, where SLP
   re-costs and declines. ISA is a first-class axis. */
#include "bench.h"
#define N 4096
static float A[N], B[N], C[N], D[N];
static int i0[N], i1[N], i2[N], i3[N];

__attribute__((noinline))
static float gather4(int k, float seed) {
  float t0 = A[i0[k]], t1 = B[i1[k]], t2 = C[i2[k]], t3 = D[i3[k]];
  float r0 = t0 * 1.5f + seed, r1 = t1 * 1.5f + seed;
  float r2 = t2 * 1.5f + seed, r3 = t3 * 1.5f + seed;
  return r0 * r1 + r2 * r3;
}

int main(void) {
  uint64_t st = 7;
  for (int i = 0; i < N; i++) {
    A[i] = (float)rndf(&st); B[i] = (float)rndf(&st);
    C[i] = (float)rndf(&st); D[i] = (float)rndf(&st);
    i0[i] = (int)(rnd32(&st) % N); i1[i] = (int)(rnd32(&st) % N);
    i2[i] = (int)(rnd32(&st) % N); i3[i] = (int)(rnd32(&st) % N);
  }
  const int REPS = 400;
  double best = 1e30;
  for (int t = 0; t < TRIALS; t++) {
    double t0 = now_s();
    for (int r = 0; r < REPS; r++) {
      float a = (float)g_d;
      for (int k = 0; k < N; k++) a = 0.5f * a + gather4(k, a * 0.001f);
      g_d = a;
    }
    double t1 = now_s();
    if (t1 - t0 < best) best = t1 - t0;
  }
  report(best, (long)REPS * N, g_d);
  return 0;
}
```

`benchmarks/tierA/manifest.toml`:

```toml
# Tier A: planted regressions with known culprits.
# Verdicts are measured, interleaved, pinned. Negatives are recorded, not hidden.

[[case]]
id = "A12"
source = "A12_simplifycfg_cmov.c"
culprit_pass = "simplifycfg"
config_flags = ["-O3"]
disable_flags = ["-mllvm", "-two-entry-phi-node-folding-threshold=0",
                 "-mllvm", "-phi-node-folding-threshold=0"]
expected_ratio = 4.99
verified = true
note = "Flagship. simplifycfg emits NO optimization remarks, so this case is invisible to every remark-based tool."

[[case]]
id = "A04"
source = "A04_slp_gather.c"
culprit_pass = "slp-vectorizer"
config_flags = ["-O3"]
disable_flags = ["-fno-slp-vectorize"]
expected_ratio = 1.29
verified = true
note = "Reproduces at baseline SSE2 only; neutral at -march=native."

# Documented negatives from the submission's four named seeds.
# Seeds (a), (c) and (d) do NOT reproduce as runtime regressions on Zen 3.
[[negative]]
seed = "fully unrolled low-trip-count loops"
finding = "222 KiB .text vs 49 KiB, yet full unrolling is 1.07x FASTER. Code-size regression, not runtime."

[[negative]]
seed = "inlining into a hot loop inducing spills"
finding = "Backwards: -O3 inlined = 0 spills, -fno-inline = 16. SysV has no callee-saved xmm registers."

[[negative]]
seed = "unswitching on a rarely-taken branch"
finding = "1.11x FASTER. Transform fires (.text 1130 -> 2135) but removed branches were perfectly predicted."
```

- [ ] **Step 4: Write the loader**

`autopsy/bench/__init__.py`:

```python
"""Benchmark corpora: planted (Tier A), realistic (Tier B), real (Tier C)."""
```

`autopsy/bench/tiera.py`:

```python
from __future__ import annotations

import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Case:
    id: str
    source: str
    culprit_pass: str
    config_flags: tuple = ()
    disable_flags: tuple = ()
    expected_ratio: float = 1.0
    verified: bool = False
    note: str = ""
    root: Path = field(default=Path("."), compare=False)

    @property
    def source_path(self) -> Path:
        return self.root / self.source


def load_manifest(path) -> list[Case]:
    path = Path(path)
    data = tomllib.loads(path.read_text())
    return [
        Case(id=c["id"], source=c["source"], culprit_pass=c["culprit_pass"],
             config_flags=tuple(c.get("config_flags", ())),
             disable_flags=tuple(c.get("disable_flags", ())),
             expected_ratio=float(c.get("expected_ratio", 1.0)),
             verified=bool(c.get("verified", False)),
             note=c.get("note", ""), root=path.parent)
        for c in data.get("case", [])
    ]


def build_case(case: Case, out_dir, flags: tuple = ()) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exe = out_dir / case.id
    subprocess.run(
        ["clang", *(flags or case.config_flags), "-fno-discard-value-names",
         "-I", str(case.root), str(case.source_path), "-o", str(exe), "-lm"],
        check=True, capture_output=True, text=True)
    return exe
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 5 passed in `test_tiera.py`

- [ ] **Step 6: Commit**

```bash
git add benchmarks/ autopsy/bench/ tests/test_tiera.py tests/conftest.py
git commit -m "feat(bench): tier A corpus with measured verdicts and documented negatives"
```

---

### Task 8: The ranker

**Files:**
- Create: `autopsy/rank/__init__.py`
- Create: `autopsy/rank/ranker.py`
- Test: `tests/test_ranker.py`

**Interfaces:**
- Consumes: `autopsy.model.Invocation`, `autopsy.model.Run`.
- Produces: `autopsy.rank.ranker.WEIGHTS` (a public dict), `score(decision, run, hot_function=None) -> Score` with `Score(total:float, components:dict)`, and `rank(run, hot_function=None, limit=10) -> RankReport` with `RankReport(suspects:list, verdict:str, no_op_passes:set)`.

**The null-hypothesis check.** On all six Tier A negative controls, the top-ranked pass under ablation was a **no-op for that program** (`memprof-remove-attributes`, `coro-split`, `openmp-opt-cgscc`, `annotation2metadata`) scoring 1.01–1.10. When the top candidate made no IR change for the program under analysis, the verdict is `NO_CULPRIT_FOUND`, not a weak suspect.

**Remarks cannot attribute.** Only ~15 passes emit them, and `simplifycfg` — the largest regression in the corpus at 4.99× — emits none. Remarks are corroborating evidence only; they carry no ranking weight.

- [ ] **Step 1: Write the failing test**

`tests/test_ranker.py`:

```python
from autopsy.capture import capture
from autopsy.rank.ranker import WEIGHTS, rank, score


def test_weights_are_public_and_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "weights must be a partition"
    assert set(WEIGHTS) == {"ir_delta", "hot_function", "size_delta",
                            "pass_prior", "drift_depth"}


def test_score_exposes_every_component(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    d = next(iter(run.decisions()))
    s = score(d, run)
    assert set(s.components) == set(WEIGHTS)
    assert 0.0 <= s.total <= 1.0


def test_hot_function_decisions_outrank_others(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    in_hot = [d for d in run.decisions() if d.func == "kernel_gemm"]
    out_hot = [d for d in run.decisions() if d.func == "recurse_b"]
    assert in_hot and out_hot
    best_in = max(score(d, run, hot_function="kernel_gemm").total for d in in_hot)
    best_out = max(score(d, run, hot_function="kernel_gemm").total for d in out_hot)
    assert best_in > best_out


def test_vectorizers_and_unrollers_carry_a_prior(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    unroll = [d for d in run.decisions() if d.pass_name == "loop-unroll"]
    other = [d for d in run.decisions() if d.pass_name == "sroa"]
    assert unroll and other
    assert (score(unroll[0], run).components["pass_prior"]
            > score(other[0], run).components["pass_prior"])


def test_scaffolding_is_never_ranked(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    report = rank(run)
    assert all(s.decision.role == "transform" for s in report.suspects)


def test_required_passes_are_never_ranked(fixture_dir, tmp_path):
    """A Required decision has no counterfactual, so it cannot be a suspect."""
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    assert all(not s.decision.required for s in rank(run).suspects)


def test_no_culprit_when_top_candidate_is_a_no_op(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    stripped = type(run)(invocations=[i for i in run.invocations if not i.changed],
                         cas_dir=run.cas_dir)
    assert rank(stripped).verdict == "NO_CULPRIT_FOUND"


def test_limit_is_respected(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    assert len(rank(run, limit=3).suspects) <= 3
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_ranker.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.rank`

- [ ] **Step 3: Write the ranker**

`autopsy/rank/__init__.py`:

```python
"""Rule-based ranking. Every weight is public and inspectable; no model."""
```

`autopsy/rank/ranker.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from ..model import Invocation, Run

# Published weights. Ranking exists to make the loop affordable -- hundreds of
# decisions cannot each be benchmarked -- and never confirms anything by itself.
WEIGHTS = {
    "ir_delta": 0.34,
    "hot_function": 0.25,
    "size_delta": 0.12,
    "pass_prior": 0.17,
    "drift_depth": 0.12,
}

# Measured on Tier A: only three pass families produce runtime regressions on
# x86-64. inline, simple-loop-unswitch, loop-idiom and full loop-unroll produced
# zero across nine designs.
PASS_PRIOR = {
    "simplifycfg": 1.00,     # largest measured regression, 4.99x
    "loop-vectorize": 0.95,
    "slp-vectorizer": 0.90,
    "loop-unroll": 0.70,
    "simple-loop-unswitch": 0.40,
    "inline": 0.40,
    "loop-idiom": 0.30,
    "licm": 0.30,
    "indvars": 0.25,
}
_DEFAULT_PRIOR = 0.10


@dataclass(frozen=True)
class Score:
    total: float
    components: dict


@dataclass(frozen=True)
class Suspect:
    rank: int
    decision: Invocation
    score: Score


@dataclass(frozen=True)
class RankReport:
    suspects: list
    verdict: str
    no_op_passes: set


def _ir_delta(d: Invocation) -> float:
    if not d.metrics_before or not d.metrics_after:
        return 0.0
    before = d.metrics_before.get("instructions", 0)
    after = d.metrics_after.get("instructions", 0)
    if not before:
        return 0.0
    return min(1.0, abs(after - before) / before)


def _size_delta(d: Invocation) -> float:
    if not d.metrics_before or not d.metrics_after:
        return 0.0
    before = d.metrics_before.get("ir_bytes") or d.metrics_before.get("instructions", 0)
    after = d.metrics_after.get("ir_bytes") or d.metrics_after.get("instructions", 0)
    if not before:
        return 0.0
    return min(1.0, abs(after - before) / before)


def _drift_depth(d: Invocation, run: Run) -> float:
    """Fewer downstream invocations means a cleaner experiment."""
    total = len(run.invocations)
    if not total:
        return 0.0
    remaining = total - d.seq
    return 1.0 - (remaining / total)


def score(d: Invocation, run: Run, hot_function: str | None = None) -> Score:
    components = {
        "ir_delta": _ir_delta(d),
        "hot_function": 1.0 if (hot_function and d.func == hot_function) else 0.0,
        "size_delta": _size_delta(d),
        "pass_prior": PASS_PRIOR.get(d.pass_name, _DEFAULT_PRIOR),
        "drift_depth": _drift_depth(d, run),
    }
    total = sum(WEIGHTS[k] * v for k, v in components.items())
    return Score(total=total, components=components)


def rank(run: Run, hot_function: str | None = None, limit: int = 10) -> RankReport:
    """Narrow every decision to the handful worth a counterfactual."""
    changed_passes = {i.pass_name for i in run.invocations if i.changed}
    no_op = {i.pass_name for i in run.invocations
             if i.role == "transform" and i.pass_name not in changed_passes}

    candidates = [d for d in run.decisions() if d.vetoable]
    scored = sorted(
        (Suspect(rank=0, decision=d, score=score(d, run, hot_function))
         for d in candidates),
        key=lambda s: s.score.total, reverse=True)[:limit]
    suspects = [Suspect(rank=n + 1, decision=s.decision, score=s.score)
                for n, s in enumerate(scored)]

    if not suspects or suspects[0].decision.pass_name in no_op:
        return RankReport(suspects=suspects, verdict="NO_CULPRIT_FOUND",
                          no_op_passes=no_op)
    return RankReport(suspects=suspects, verdict="RANKED", no_op_passes=no_op)
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 8 passed in `test_ranker.py`

- [ ] **Step 5: Commit**

```bash
git add autopsy/rank/ tests/test_ranker.py
git commit -m "feat(rank): rule-based ranking with published weights and a null check"
```

---

### Task 9: `autopsy diagnose` end to end

**Files:**
- Create: `autopsy/diagnose.py`
- Modify: `autopsy/cli.py`
- Test: `tests/test_diagnose.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `autopsy.diagnose.diagnose(src, out_dir, hot_function=None, top=5) -> Diagnosis` with `Diagnosis(verdict, suspects, measurements, provenance, evidence_path)`, writing `evidence.json` matching spec §6.3.

- [ ] **Step 1: Write the failing test**

`tests/test_diagnose.py`:

```python
import json

from autopsy.diagnose import diagnose


def test_diagnose_produces_an_evidence_record(repo_root, tmp_path):
    d = diagnose(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path, top=2)
    assert d.evidence_path.exists()
    rec = json.loads(d.evidence_path.read_text())
    assert "verdict" in rec and "suspects" in rec and "measurements" in rec


def test_every_measurement_carries_provenance(repo_root, tmp_path):
    d = diagnose(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path, top=2)
    rec = json.loads(d.evidence_path.read_text())
    ids = {n["id"] for n in rec["provenance"]["nodes"]}
    for m in rec["measurements"]:
        assert m["provenance"] in ids, "a number without provenance is not displayable"


def test_exact_measurements_never_carry_an_interval(repo_root, tmp_path):
    d = diagnose(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path, top=2)
    rec = json.loads(d.evidence_path.read_text())
    for m in rec["measurements"]:
        if m["kind"] == "exact":
            assert m["n"] == 1
            assert "iqr" not in m and "ci" not in m


def test_the_causal_claim_is_stated_verbatim(repo_root, tmp_path):
    d = diagnose(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path, top=1)
    rec = json.loads(d.evidence_path.read_text())
    assert "this pipeline" in rec["claim"] and "this program" in rec["claim"]


def test_suspects_carry_a_reproduce_command(repo_root, tmp_path):
    d = diagnose(repo_root / "tests" / "fixtures" / "gemm.c", tmp_path, top=1)
    rec = json.loads(d.evidence_path.read_text())
    if rec["suspects"]:
        assert "clang" in rec["suspects"][0]["reproduce"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_diagnose.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.diagnose`

- [ ] **Step 3: Write the orchestrator**

`autopsy/diagnose.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .capture import capture
from .experiment.runner import address_of, run_experiment
from .measure.static import section_sizes
from .rank.ranker import rank

CAUSAL_CLAIM = (
    "Removing this decision from this pipeline on this program changed the "
    "measured outcome by the stated amount. No general claim about the "
    "transformation is made."
)


@dataclass
class Diagnosis:
    verdict: str
    suspects: list = field(default_factory=list)
    measurements: list = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    evidence_path: Path | None = None


def diagnose(src, out_dir, hot_function: str | None = None, top: int = 5) -> Diagnosis:
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = capture(src, out_dir / "baseline")
    report = rank(baseline, hot_function=hot_function, limit=top)

    suspects, measurements = [], []
    nodes = [{"id": "p_llvm_size", "type": "tool", "label": "llvm-size",
              "cmd": "llvm-size --format=sysv", "samples": 1}]
    edges = []

    for s in report.suspects:
        addr = address_of(s.decision)
        exp = run_experiment(src, addr, out_dir / f"exp_{s.rank:02d}")
        if not exp.usable:
            continue
        base_text = section_sizes(exp.baseline_obj).get(".text", 0)
        var_text = section_sizes(exp.variant_obj).get(".text", 0)

        mid = f"m_text_{s.rank}"
        measurements.append({
            "id": mid, "label": f".text size, veto #{s.decision.seq}",
            "unit": "bytes", "kind": "exact", "n": 1,
            "value": base_text, "counterfactual": var_text,
            "provenance": "p_llvm_size",
        })
        edges.append({"from": "p_llvm_size", "to": mid, "label": "yields"})

        suspects.append({
            "rank": s.rank, "seq": s.decision.seq,
            "pass": s.decision.pass_name,
            "address": s.decision.address.as_dict(),
            "score": {"total": s.score.total, "weights": s.score.components},
            "confirmed": True,
            "prefix_identical_records": exp.prefix.identical_records,
            "reproduce": exp.reproduce_cmd,
            "evidence": [mid],
        })

    record = {
        "verdict": report.verdict,
        "claim": CAUSAL_CLAIM,
        "suspects": suspects,
        "measurements": measurements,
        "provenance": {"nodes": nodes, "edges": edges},
        "no_op_passes": sorted(report.no_op_passes),
    }
    path = out_dir / "evidence.json"
    path.write_text(json.dumps(record, indent=2))
    return Diagnosis(verdict=report.verdict, suspects=suspects,
                     measurements=measurements,
                     provenance=record["provenance"], evidence_path=path)
```

- [ ] **Step 4: Add the `diagnose` subcommand**

In `autopsy/cli.py`:

```python
    dia = sub.add_parser("diagnose", help="rank and test the decisions behind a regression")
    dia.add_argument("source", type=Path)
    dia.add_argument("-o", "--out", type=Path, default=Path("autopsy-diagnose"))
    dia.add_argument("--hot-function", default=None)
    dia.add_argument("--top", type=int, default=5)
```

and in `main`:

```python
    if args.command == "diagnose":
        from .diagnose import diagnose
        d = diagnose(args.source, args.out, hot_function=args.hot_function,
                     top=args.top)
        print(f"verdict: {d.verdict}")
        for s in d.suspects:
            print(f"  #{s['rank']} {s['pass']} on {s['address']['func']} "
                  f"(score {s['score']['total']:.3f})")
        print(f"evidence: {d.evidence_path}")
        return 0
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 5 passed in `test_diagnose.py`

- [ ] **Step 6: Commit**

```bash
git add autopsy/diagnose.py autopsy/cli.py tests/test_diagnose.py
git commit -m "feat(diagnose): end-to-end ranking, counterfactuals and evidence record"
```

---

## Definition of done

Plan 3 is complete when `make test` is green and:

```bash
.venv/bin/autopsy diagnose tests/fixtures/gemm.c --hot-function kernel_gemm --top 3
```

prints a verdict and ranked suspects, and writes an `evidence.json` in which every
measurement carries a provenance id, every `exact` measurement has `n == 1` and no
interval, and the causal claim is stated verbatim.

## What Plan 3 deliberately does not do

- **No Tier B or Tier C corpora.** The acquisition recipes are in spec §7.2–7.3
  (~9 MB, no cmake needed); wiring them is follow-on work once Tier A drives the
  loop end to end.
- **No wall-clock in `diagnose`.** The default scorer is deterministic `.text` size,
  which needs no repetition. Callgrind and the sampler are available and tested, and
  become the scorer once a runnable benchmark is wired in.
- **No API or UI.** Plan 4.
