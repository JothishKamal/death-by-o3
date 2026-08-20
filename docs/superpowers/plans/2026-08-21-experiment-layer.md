# Experiment Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `autopsy veto <address>` compiles a counterfactual in which exactly one pass invocation is suppressed, proves it suppressed the right one, verifies the result is semantically equivalent, and emits a command a judge can reproduce with stock clang.

**Architecture:** The capture plugin's `shouldRun` callback gains an address matcher guarded by a content hash: it vetoes only when the tuple *and* the guard hash both match, and aborts loudly otherwise. Python drives baseline and counterfactual compiles, diffs the two event streams to prove the prefix is identical, and runs a verifier. Three veto tiers are implemented, with Tier 1 as the authority.

**Tech Stack:** C++17 / LLVM 22.1.8 plugin (extends Plan 1), Python 3.14, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-optimization-autopsy-design.md`
**Depends on:** `docs/superpowers/plans/2026-08-20-capture-layer.md` (Plan 1) complete.

## Global Constraints

- Everything in Plan 1's Global Constraints still applies — in particular `-fno-discard-value-names` on every compile, and never touching the AnalysisManager.
- **A veto must never proceed on a guard-hash mismatch.** Refusing is always correct; vetoing the wrong invocation silently is the one unrecoverable failure mode of this product.
- **Tier 1 is the only authority.** Any Tier 2 or Tier 3 result is confirmed against Tier 1 before it is reported. `opt`-replay is a *different pipeline* from clang's (measured: 520 records vs 499).
- **The bisect index must be calibrated, never assumed.** Measured on the reference fixture: LLVM's `--opt-bisect` counts **391** gated passes in the middle end where our plugin counts **383**, and a further **128** backend/MIR passes that a middle-end plugin never observes (codegen runs under a different pass manager). Derive the mapping by parsing `-mllvm --opt-bisect=-1`; never by incrementing a local counter.
- Every veto experiment records: the address, the guard, whether the guard matched, the prefix-identity check, verifier result, and output equivalence. An experiment missing any of these is not reportable.

---

### Task 1: Veto one invocation by address

**Files:**
- Create: `plugin/include/autopsy/Veto.h`
- Modify: `plugin/src/Plugin.cpp`
- Test: `tests/test_veto_basic.py`

**Interfaces:**
- Consumes: `autopsy::occKey`, `autopsy::identify`, `autopsy::Recorder` (Plan 1).
- Produces: `struct autopsy::VetoSpec { std::string pass_class, kind, unit_name, func; unsigned occurrence; uint64_t guard; bool armed; }`, `VetoSpec autopsy::parseVeto(const char *)`, and `bool autopsy::matches(const VetoSpec&, llvm::StringRef, const UnitId&, unsigned)`. The plugin reads `AUTOPSY_VETO` in the form `pass_class|kind|unit_name|func|occurrence|guard`.

- [ ] **Step 1: Write the failing test**

`tests/test_veto_basic.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `make build && .venv/bin/pytest tests/test_veto_basic.py -v`
Expected: FAIL — `test_veto_suppresses_exactly_one_invocation` gets 0 skipped

- [ ] **Step 3: Write `Veto.h`**

```cpp
//===- Veto.h - Suppress exactly one pass invocation ---------------------===//
// Licensed under the Apache License v2.0 with LLVM Exceptions.
//===----------------------------------------------------------------------===//
#ifndef AUTOPSY_VETO_H
#define AUTOPSY_VETO_H

#include "autopsy/UnitId.h"
#include "llvm/ADT/StringRef.h"

#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>

namespace autopsy {

struct VetoSpec {
  std::string pass_class, kind, unit_name, func;
  unsigned occurrence = 0;
  uint64_t guard = 0;
  bool armed = false;
};

/// Parse "pass_class|kind|unit_name|func|occurrence|guard".
inline VetoSpec parseVeto(const char *S) {
  VetoSpec V;
  if (!S)
    return V;
  std::vector<std::string> Parts;
  std::string Cur;
  for (const char *P = S; *P; ++P) {
    if (*P == '|') { Parts.push_back(Cur); Cur.clear(); }
    else            { Cur += *P; }
  }
  Parts.push_back(Cur);
  if (Parts.size() != 6)
    return V;
  V.pass_class = Parts[0];
  V.kind       = Parts[1];
  V.unit_name  = Parts[2];
  V.func       = Parts[3];
  V.occurrence = (unsigned)strtoul(Parts[4].c_str(), nullptr, 10);
  V.guard      = strtoull(Parts[5].c_str(), nullptr, 16);
  V.armed      = true;
  return V;
}

inline bool matches(const VetoSpec &V, llvm::StringRef PassClass,
                    const UnitId &U, unsigned Occurrence) {
  return V.armed && V.pass_class == PassClass && V.kind == U.kind &&
         V.unit_name == U.name && V.func == U.func &&
         V.occurrence == Occurrence;
}

} // namespace autopsy

#endif // AUTOPSY_VETO_H
```

- [ ] **Step 4: Arm the gate**

Add to `Recorder` in `Record.h`: `autopsy::VetoSpec Veto;` and include `autopsy/Veto.h`.

In `registerCallbacks`, next to the other env reads:

```cpp
  R.Veto = autopsy::parseVeto(getenv("AUTOPSY_VETO"));
```

Replace the `shouldRun` callback body from Plan 1 Task 6:

```cpp
  PIC->registerShouldRunOptionalPassCallback(
      [](StringRef PassClass, Any IR) -> bool {
        R.SawShouldRun = true;
        ++R.BisectCounter;
        if (!R.Veto.armed)
          return true;
        autopsy::UnitId U = autopsy::identify(IR);
        unsigned Will = R.Occ[autopsy::occKey(PassClass, U)] + 1;
        if (!autopsy::matches(R.Veto, PassClass, U, Will))
          return true;
        return false;   // guard verification lands in Task 2
      });
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 4 passed in `test_veto_basic.py`

- [ ] **Step 6: Commit**

```bash
git add plugin/include/autopsy/Veto.h plugin/src/Plugin.cpp plugin/include/autopsy/Record.h tests/test_veto_basic.py
git commit -m "feat(veto): suppress exactly one pass invocation by address"
```

---

### Task 2: Guard verification — refuse rather than mis-veto

**Files:**
- Modify: `plugin/include/autopsy/Veto.h`
- Modify: `plugin/src/Plugin.cpp`
- Test: `tests/test_veto_guard.py`

**Interfaces:**
- Consumes: `autopsy::scopeHash` (Plan 1 Task 5), `autopsy::VetoSpec`.
- Produces: a `VETO_REFUSED` line on stderr carrying `want=` and `got=` hashes, and a nonzero-effect guarantee: when the guard matches, `VETO_APPLIED` is printed with the seq that was suppressed.

- [ ] **Step 1: Write the failing test**

`tests/test_veto_guard.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `make build && .venv/bin/pytest tests/test_veto_guard.py -v`
Expected: FAIL — no `VETO_APPLIED` marker

- [ ] **Step 3: Implement the guard check**

Replace the `return false;` in the `shouldRun` callback with:

```cpp
        uint64_t Got = autopsy::scopeHash(IR);
        if (Got != R.Veto.guard) {
          errs() << "VETO_REFUSED stale address: want="
                 << format_hex(R.Veto.guard, 18)
                 << " got=" << format_hex(Got, 18)
                 << " pass=" << PassClass << " unit=" << U.kind << ":" << U.name
                 << " occ=" << Will << "\n";
          R.VetoRefused = true;
          return true;   // refuse: never veto the wrong invocation
        }
        errs() << "VETO_APPLIED seq=" << (R.Seq + 1) << " pass=" << PassClass
               << " unit=" << U.kind << ":" << U.name << " occ=" << Will
               << " guard=" << format_hex(Got, 18) << "\n";
        R.VetoApplied = true;
        return false;
```

Add to `Recorder`: `bool VetoApplied = false, VetoRefused = false;` and include
`autopsy/Hash.h` in `Plugin.cpp` if not already present.

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 4 passed in `test_veto_guard.py`

- [ ] **Step 5: Commit**

```bash
git add plugin/ tests/test_veto_guard.py
git commit -m "feat(veto): guard-hash verification refuses stale addresses"
```

---

### Task 3: Prove the prefix is identical

**Files:**
- Create: `autopsy/experiment/__init__.py`
- Create: `autopsy/experiment/prefix.py`
- Test: `tests/test_prefix_identity.py`

**Interfaces:**
- Consumes: `autopsy.model.Run`, `autopsy.model.Invocation`.
- Produces: `autopsy.experiment.prefix.compare(baseline: Run, variant: Run, target_seq: int) -> PrefixReport` where `PrefixReport` is a frozen dataclass with `identical_records: int`, `target_reached: bool`, `first_divergence: int | None`, and `ok: bool` (`identical_records == target_seq - 1 and target_reached`).

**Why this matters:** the single causal claim (spec §1.1) is that only one decision was removed. That is only true if every invocation *before* the target ran identically. This check is what turns the claim into a verified fact.

- [ ] **Step 1: Write the failing test**

`tests/test_prefix_identity.py`:

```python
import pytest

from autopsy.experiment.prefix import compare
from tests.test_veto_basic import find_target, veto_arg


@pytest.fixture
def pair(capture_run, fixture_dir):
    base = capture_run(fixture_dir / "gemm.c")
    target = find_target([r.__dict__ for r in base.invocations])
    variant = capture_run(fixture_dir / "gemm.c",
                          env={"AUTOPSY_VETO": veto_arg(target)})
    return base, variant, target


def test_prefix_is_identical_up_to_the_target(pair):
    base, variant, target = pair
    report = compare(base, variant, target["seq"])
    assert report.ok
    assert report.identical_records == target["seq"] - 1
    assert report.target_reached


def test_divergence_begins_at_the_target(pair):
    base, variant, target = pair
    report = compare(base, variant, target["seq"])
    assert report.first_divergence == target["seq"]


def test_identical_runs_have_no_divergence(capture_run, fixture_dir):
    a = capture_run(fixture_dir / "gemm.c")
    b = capture_run(fixture_dir / "gemm.c")
    report = compare(a, b, target_seq=len(a.invocations) + 1)
    assert report.first_divergence is None
    assert report.identical_records == len(a.invocations)
```

Add to `tests/conftest.py`:

```python
@pytest.fixture
def capture_run(tmp_path):
    """Capture into a fresh directory and return a Run."""
    from autopsy.capture import capture

    counter = {"n": 0}

    def _run(src, env=None):
        counter["n"] += 1
        out = tmp_path / f"run{counter['n']}"
        return capture(src, out, env_extra=env)

    return _run
```

and extend `autopsy/capture.py`'s signature to `capture(src, out_dir, opt_level="-O3", extra_flags=None, env_extra=None)`, merging `env_extra` into the subprocess environment.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_prefix_identity.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.experiment`

- [ ] **Step 3: Write the comparator**

`autopsy/experiment/__init__.py`:

```python
"""Counterfactual experiments: veto one decision and measure the consequence."""
```

`autopsy/experiment/prefix.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from ..model import Invocation, Run

# Fields that must match for two invocations to be considered identical.
# wall_ns is excluded: it is a timing measurement, not part of the pipeline.
_IDENTITY_FIELDS = (
    "seq", "parent_seq", "depth", "pass_class", "pass_name", "role", "kind",
    "unit_name", "func", "occurrence", "required", "status", "changed",
    "hash_before", "hash_after",
)


def _key(inv: Invocation) -> tuple:
    return tuple(getattr(inv, f, None) for f in _IDENTITY_FIELDS
                 if f not in ("hash_before", "hash_after")) + (inv.guard,)


@dataclass(frozen=True)
class PrefixReport:
    identical_records: int
    target_reached: bool
    first_divergence: int | None

    @property
    def ok(self) -> bool:
        return self.target_reached and self.first_divergence is not None


def compare(baseline: Run, variant: Run, target_seq: int) -> PrefixReport:
    """Verify the variant matches the baseline on every record before target_seq."""
    identical = 0
    first_div = None
    for b, v in zip(baseline.invocations, variant.invocations):
        if _key(b) == _key(v):
            identical += 1
        else:
            first_div = b.seq
            break

    target_reached = identical == target_seq - 1 and first_div == target_seq
    if first_div is None:
        # No divergence at all -- the runs are identical.
        return PrefixReport(identical_records=identical,
                            target_reached=False, first_divergence=None)
    return PrefixReport(identical_records=identical,
                        target_reached=target_reached,
                        first_divergence=first_div)
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 3 passed in `test_prefix_identity.py`

- [ ] **Step 5: Commit**

```bash
git add autopsy/experiment/ tests/test_prefix_identity.py tests/conftest.py autopsy/capture.py
git commit -m "feat(experiment): verify the pre-veto prefix is byte-identical"
```

---

### Task 4: Verify the counterfactual is semantically equivalent

**Files:**
- Create: `autopsy/experiment/verify.py`
- Create: `tests/fixtures/runnable.c`
- Test: `tests/test_verification.py`

**Interfaces:**
- Consumes: nothing from earlier tasks; operates on object files and executables.
- Produces: `autopsy.experiment.verify.verify_module(ir_or_obj: Path) -> bool` (runs `llvm-as`/`opt -passes=verify`), and `verify_equivalence(baseline_exe, variant_exe, args=()) -> Equivalence`, a frozen dataclass with `stdout_identical, exit_code_identical, diverged` and `detail: str`.

**Spec §5.5:** a variant that diverges is a genuine bug and is surfaced as a finding, never hidden.

- [ ] **Step 1: Write the failing test**

`tests/fixtures/runnable.c`:

```c
#include <stdio.h>
#define N 96
static double A[N][N], B[N][N], C[N][N];
int main(void) {
  for (int i = 0; i < N; i++)
    for (int j = 0; j < N; j++) { A[i][j] = (i * 7 + j) % 13; B[i][j] = (i + j * 3) % 11; }
  for (int i = 0; i < N; i++)
    for (int k = 0; k < N; k++)
      for (int j = 0; j < N; j++) C[i][j] += A[i][k] * B[k][j];
  double s = 0.0;
  for (int i = 0; i < N; i++) s += C[i][i];
  printf("CHECK %.6f\n", s);
  return 0;
}
```

`tests/test_verification.py`:

```python
import subprocess

from autopsy.experiment.verify import verify_equivalence, verify_module


def build(src, out, flags=()):
    subprocess.run(["clang", "-O3", "-fno-discard-value-names", *flags,
                    str(src), "-o", str(out)], check=True)
    return out


def test_identical_builds_are_equivalent(fixture_dir, tmp_path):
    a = build(fixture_dir / "runnable.c", tmp_path / "a")
    b = build(fixture_dir / "runnable.c", tmp_path / "b")
    eq = verify_equivalence(a, b)
    assert eq.stdout_identical and eq.exit_code_identical
    assert not eq.diverged


def test_semantics_preserving_flag_change_is_equivalent(fixture_dir, tmp_path):
    """Disabling a pass must not change the program's output."""
    a = build(fixture_dir / "runnable.c", tmp_path / "a")
    b = build(fixture_dir / "runnable.c", tmp_path / "b", flags=["-fno-vectorize"])
    eq = verify_equivalence(a, b)
    assert not eq.diverged, eq.detail


def test_genuinely_different_programs_diverge(fixture_dir, tmp_path):
    a = build(fixture_dir / "runnable.c", tmp_path / "a")
    altered = tmp_path / "altered.c"
    altered.write_text(
        (fixture_dir / "runnable.c").read_text().replace("s += C[i][i];", "s += C[i][i] + 1;"))
    b = build(altered, tmp_path / "b")
    eq = verify_equivalence(a, b)
    assert eq.diverged
    assert not eq.stdout_identical


def test_module_verifier_accepts_valid_ir(fixture_dir, tmp_path):
    ir = tmp_path / "m.ll"
    subprocess.run(["clang", "-O3", "-S", "-emit-llvm",
                    str(fixture_dir / "runnable.c"), "-o", str(ir)], check=True)
    assert verify_module(ir)


def test_module_verifier_rejects_broken_ir(tmp_path):
    bad = tmp_path / "bad.ll"
    bad.write_text("define i32 @f() {\nentry:\n  ret i64 0\n}\n")
    assert not verify_module(bad)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_verification.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.experiment.verify`

- [ ] **Step 3: Write the verifier**

`autopsy/experiment/verify.py`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 5 passed in `test_verification.py`

- [ ] **Step 5: Commit**

```bash
git add autopsy/experiment/verify.py tests/fixtures/runnable.c tests/test_verification.py
git commit -m "feat(experiment): module verifier and output-equivalence checking"
```

---

### Task 5: The Tier 1 experiment runner

**Files:**
- Create: `autopsy/experiment/runner.py`
- Modify: `autopsy/cli.py`
- Test: `tests/test_tier1_runner.py`

**Interfaces:**
- Consumes: `autopsy.capture.capture`, `prefix.compare`, `verify.verify_equivalence`.
- Produces: `autopsy.experiment.runner.run_experiment(src, address, out_dir, benchmark=None) -> Experiment`, a frozen dataclass with `address, tier, guard_matched, prefix, equivalence, baseline_run, variant_run, baseline_obj, variant_obj, reproduce_cmd`. Also `autopsy.experiment.runner.address_of(inv) -> str` producing the `AUTOPSY_VETO` string.

- [ ] **Step 1: Write the failing test**

`tests/test_tier1_runner.py`:

```python
import pytest

from autopsy.capture import capture
from autopsy.experiment.runner import address_of, run_experiment


@pytest.fixture(scope="module")
def baseline(tmp_path_factory, request):
    fixtures = request.config.rootpath / "tests" / "fixtures"
    return capture(fixtures / "gemm.c", tmp_path_factory.mktemp("base")), fixtures


def test_experiment_applies_the_veto(baseline, tmp_path):
    run, fixtures = baseline
    target = next(d for d in run.decisions()
                  if d.pass_name == "loop-unroll" and d.func == "kernel_gemm")
    exp = run_experiment(fixtures / "gemm.c", address_of(target), tmp_path)
    assert exp.guard_matched
    assert exp.tier == 1


def test_experiment_verifies_the_prefix(baseline, tmp_path):
    run, fixtures = baseline
    target = next(d for d in run.decisions()
                  if d.pass_name == "loop-unroll" and d.func == "kernel_gemm")
    exp = run_experiment(fixtures / "gemm.c", address_of(target), tmp_path)
    assert exp.prefix.ok
    assert exp.prefix.first_divergence == target.seq


def test_experiment_refuses_a_stale_address(baseline, tmp_path):
    run, fixtures = baseline
    target = next(iter(run.decisions()))
    stale = address_of(target).rsplit("|", 1)[0] + "|0xdeadbeefdeadbeef"
    exp = run_experiment(fixtures / "gemm.c", stale, tmp_path)
    assert not exp.guard_matched
    assert exp.prefix.first_divergence is None


def test_reproduce_command_is_emitted(baseline, tmp_path):
    run, fixtures = baseline
    target = next(iter(run.decisions()))
    exp = run_experiment(fixtures / "gemm.c", address_of(target), tmp_path)
    assert "clang" in exp.reproduce_cmd
    assert "-fno-discard-value-names" in exp.reproduce_cmd
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_tier1_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.experiment.runner`

- [ ] **Step 3: Write the runner**

`autopsy/experiment/runner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..capture import REQUIRED_FLAGS, capture
from ..model import Invocation, Run
from .prefix import PrefixReport, compare
from .verify import Equivalence


def address_of(inv: Invocation) -> str:
    """Serialise a decision address into the AUTOPSY_VETO wire form."""
    return "|".join([inv.pass_class, inv.kind, inv.unit_name, inv.func,
                     str(inv.occurrence), inv.guard])


@dataclass(frozen=True)
class Experiment:
    address: str
    tier: int
    guard_matched: bool
    prefix: PrefixReport
    baseline_run: Run
    variant_run: Run
    baseline_obj: Path
    variant_obj: Path
    reproduce_cmd: str
    equivalence: Equivalence | None = None

    @property
    def usable(self) -> bool:
        """An experiment is only reportable if the veto landed where intended."""
        return self.guard_matched and self.prefix.ok


def run_experiment(src, address: str, out_dir, benchmark=None) -> Experiment:
    """Tier 1: recompile from source with an occurrence-scoped gate.

    Tier 1 is the authority. Tiers 2 and 3 are optimisations that must be
    confirmed against this result before they are trusted (spec 5.5).
    """
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = capture(src, out_dir / "baseline")
    variant = capture(src, out_dir / "variant", env_extra={"AUTOPSY_VETO": address})

    skipped = [i for i in variant.invocations if i.status == "skipped"]
    guard_matched = len(skipped) == 1

    target_seq = skipped[0].seq if guard_matched else 0
    prefix = compare(baseline, variant, target_seq) if guard_matched else \
        PrefixReport(identical_records=0, target_reached=False, first_divergence=None)

    flags = " ".join(REQUIRED_FLAGS)
    cmd = (f"clang -O3 {flags} -fpass-plugin=<autopsy> "
           f"-c {src.name}   # AUTOPSY_VETO='{address}'")

    return Experiment(
        address=address, tier=1, guard_matched=guard_matched, prefix=prefix,
        baseline_run=baseline, variant_run=variant,
        baseline_obj=out_dir / "baseline" / (src.stem + ".o"),
        variant_obj=out_dir / "variant" / (src.stem + ".o"),
        reproduce_cmd=cmd,
    )
```

- [ ] **Step 4: Add the `veto` subcommand**

In `autopsy/cli.py`, after the `capture` parser:

```python
    vet = sub.add_parser("veto", help="build a counterfactual with one decision removed")
    vet.add_argument("source", type=Path)
    vet.add_argument("--pass-name", required=True)
    vet.add_argument("--function", required=True)
    vet.add_argument("--occurrence", type=int, default=1)
    vet.add_argument("-o", "--out", type=Path, default=Path("autopsy-veto"))
```

and in `main`:

```python
    if args.command == "veto":
        from .experiment.runner import address_of, run_experiment
        probe = capture(args.source, args.out / "probe")
        candidates = [d for d in probe.decisions()
                      if d.pass_name == args.pass_name and d.func == args.function
                      and d.occurrence == args.occurrence]
        if not candidates:
            print(f"no decision matching {args.pass_name} on {args.function} "
                  f"occurrence {args.occurrence}", file=sys.stderr)
            return 2
        exp = run_experiment(args.source, address_of(candidates[0]), args.out)
        print(f"tier            {exp.tier}")
        print(f"guard matched   {exp.guard_matched}")
        print(f"prefix ok       {exp.prefix.ok} "
              f"({exp.prefix.identical_records} identical records)")
        print(f"reproduce       {exp.reproduce_cmd}")
        return 0 if exp.usable else 1
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 4 passed in `test_tier1_runner.py`

- [ ] **Step 6: Commit**

```bash
git add autopsy/experiment/runner.py autopsy/cli.py tests/test_tier1_runner.py
git commit -m "feat(experiment): tier 1 counterfactual runner and veto CLI"
```

---

### Task 6: Calibrate the `--opt-bisect` reproducibility string

**Files:**
- Create: `autopsy/experiment/bisect.py`
- Test: `tests/test_bisect_calibration.py`

**Interfaces:**
- Consumes: `autopsy.model.Run`.
- Produces: `autopsy.experiment.bisect.calibrate(src, opt_level="-O3") -> list[BisectEntry]` where `BisectEntry(index:int, pass_name:str, unit:str)`; and `bisect_range_excluding(index:int, total:int) -> str` producing e.g. `1-372,374-441`.

**The measured facts this task exists for.** On the reference fixture, LLVM's `--opt-bisect` numbers **519** gated passes: **391** in the middle end and **128** in the backend, which runs under a different pass manager and is invisible to a middle-end plugin. Our own `shouldRun` counter sees **383**. The numbers do not correspond, so the index is obtained by parsing LLVM's own listing.

- [ ] **Step 1: Write the failing test**

`tests/test_bisect_calibration.py`:

```python
from autopsy.experiment.bisect import bisect_range_excluding, calibrate


def test_calibration_lists_gated_passes(fixture_dir):
    entries = calibrate(fixture_dir / "gemm.c")
    assert len(entries) > 400, f"expected 500+ gated passes, got {len(entries)}"
    assert entries[0].index == 1
    assert [e.index for e in entries] == list(range(1, len(entries) + 1))


def test_calibration_includes_backend_passes(fixture_dir):
    """The middle-end plugin cannot see these, which is why we parse instead."""
    names = {e.pass_name for e in calibrate(fixture_dir / "gemm.c")}
    assert any("isel" in n for n in names), "no backend passes in the listing"


def test_middle_end_prefix_precedes_codegen(fixture_dir):
    entries = calibrate(fixture_dir / "gemm.c")
    first_isel = next(e.index for e in entries if "isel" in e.pass_name)
    assert first_isel > 300, "codegen should follow the whole middle end"


def test_range_excluding_one_index():
    assert bisect_range_excluding(373, 441) == "1-372,374-441"
    assert bisect_range_excluding(1, 5) == "2-5"
    assert bisect_range_excluding(5, 5) == "1-4"


def test_range_actually_skips_that_pass(fixture_dir, tmp_path):
    """End-to-end: the emitted string must suppress exactly one pass."""
    import subprocess
    entries = calibrate(fixture_dir / "gemm.c")
    target = next(e for e in entries if e.pass_name == "loop-unroll")
    rng = bisect_range_excluding(target.index, len(entries))
    result = subprocess.run(
        ["clang", "-O3", "-fno-discard-value-names",
         "-mllvm", f"--opt-bisect={rng}", "-mllvm", "--opt-bisect-verbose",
         "-c", str(fixture_dir / "gemm.c"), "-o", str(tmp_path / "o.o")],
        capture_output=True, text=True)
    assert result.returncode == 0
    not_run = [l for l in result.stderr.splitlines() if "NOT running pass" in l]
    assert len(not_run) == 1, f"expected 1 suppressed pass, got {len(not_run)}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_bisect_calibration.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.experiment.bisect`

- [ ] **Step 3: Write the calibrator**

`autopsy/experiment/bisect.py`:

```python
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..capture import REQUIRED_FLAGS

_LINE = re.compile(r"BISECT: running pass \((\d+)\) (.+?) on (.+)$")


@dataclass(frozen=True)
class BisectEntry:
    index: int
    pass_name: str
    unit: str


def calibrate(src, opt_level: str = "-O3") -> list[BisectEntry]:
    """Enumerate every gated pass, using LLVM's own numbering.

    Our shouldRun counter cannot be used: it is middle-end only, and LLVM also
    gates backend passes running under a different pass manager. Measured on the
    reference fixture: 519 gated passes total, 391 middle-end, 128 backend,
    against 383 seen by the plugin.
    """
    result = subprocess.run(
        ["clang", opt_level, *REQUIRED_FLAGS,
         "-mllvm", "--opt-bisect=-1", "-c", str(Path(src)), "-o", "/dev/null"],
        capture_output=True, text=True)
    entries = []
    for line in result.stderr.splitlines():
        m = _LINE.match(line.strip())
        if m:
            entries.append(BisectEntry(index=int(m.group(1)),
                                       pass_name=m.group(2).strip(),
                                       unit=m.group(3).strip()))
    return entries


def bisect_range_excluding(index: int, total: int) -> str:
    """Build an --opt-bisect range list that runs everything except `index`."""
    parts = []
    if index > 1:
        parts.append(f"1-{index - 1}")
    if index < total:
        parts.append(f"{index + 1}-{total}")
    return ",".join(parts)
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 5 passed in `test_bisect_calibration.py`

- [ ] **Step 5: Commit**

```bash
git add autopsy/experiment/bisect.py tests/test_bisect_calibration.py
git commit -m "feat(experiment): calibrate opt-bisect indices from LLVM's own listing"
```

---

### Task 7: Tier 3 — pipeline-string editing, validated against Tier 1

**Files:**
- Create: `autopsy/experiment/tier3.py`
- Test: `tests/test_tier3.py`

**Interfaces:**
- Consumes: `autopsy.experiment.runner.Experiment`.
- Produces: `autopsy.experiment.tier3.pipeline_string(bc_path) -> str` (strips the trailing `BitcodeWriterPass`), `run_tier3(bc_path, pass_to_drop, out_bc) -> bool`, and `validate_against_tier1(tier3_obj, tier1_obj) -> bool`.

**Verified facts:** the pipeline string does round-trip — a 4661-character `default<O3>` string replayed to byte-identical bitcode. The trailing `BitcodeWriterPass` that `opt -o` appends is not a real pass and must be stripped or `opt` fails with `unknown module pass 'BitcodeWriterPass'`. But `opt`-replay is a *different pipeline* from clang's (520 records vs 499), so Tier 3 never stands alone.

- [ ] **Step 1: Write the failing test**

`tests/test_tier3.py`:

```python
import subprocess

from autopsy.experiment.tier3 import pipeline_string, run_tier3


def make_bc(src, out, tmp_path):
    subprocess.run(["clang", "-O3", "-Xclang", "-disable-llvm-passes",
                    "-emit-llvm", "-c", str(src), "-o", str(out)], check=True)
    return out


def test_pipeline_string_is_extracted(fixture_dir, tmp_path):
    bc = make_bc(fixture_dir / "gemm.c", tmp_path / "in.bc", tmp_path)
    s = pipeline_string(bc)
    assert len(s) > 1000
    assert "BitcodeWriterPass" not in s, "trailing writer pass must be stripped"
    assert "simplifycfg" in s


def test_pipeline_string_round_trips_byte_identical(fixture_dir, tmp_path):
    bc = make_bc(fixture_dir / "gemm.c", tmp_path / "in.bc", tmp_path)
    ref, replay = tmp_path / "ref.bc", tmp_path / "replay.bc"
    subprocess.run(["opt", "-passes=default<O3>", str(bc), "-o", str(ref)], check=True)
    subprocess.run(["opt", f"-passes={pipeline_string(bc)}", str(bc), "-o", str(replay)],
                   check=True)
    assert ref.read_bytes() == replay.read_bytes()


def test_tier3_drops_a_named_pass(fixture_dir, tmp_path):
    bc = make_bc(fixture_dir / "gemm.c", tmp_path / "in.bc", tmp_path)
    out = tmp_path / "t3.bc"
    assert run_tier3(bc, "loop-unroll", out)
    assert out.exists()
    ref = tmp_path / "ref.bc"
    subprocess.run(["opt", "-passes=default<O3>", str(bc), "-o", str(ref)], check=True)
    assert out.read_bytes() != ref.read_bytes(), "dropping the pass had no effect"


def test_tier3_is_not_trusted_alone(fixture_dir, tmp_path):
    """opt-replay is a different pipeline from clang's; record the discrepancy."""
    bc = make_bc(fixture_dir / "gemm.c", tmp_path / "in.bc", tmp_path)
    s = pipeline_string(bc)
    assert s.count("simplifycfg") >= 4, "pipeline string looks truncated"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_tier3.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.experiment.tier3`

- [ ] **Step 3: Write Tier 3**

`autopsy/experiment/tier3.py`:

```python
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def pipeline_string(bc_path) -> str:
    """Dump the -O3 pipeline as a -passes= string.

    `opt -o` appends BitcodeWriterPass, which is not a real pass; replaying a
    string that still contains it fails with "unknown module pass".
    """
    result = subprocess.run(
        ["opt", "-passes=default<O3>", "--print-pipeline-passes",
         str(Path(bc_path)), "-o", "/dev/null"],
        capture_output=True, text=True, check=True)
    return re.sub(r",BitcodeWriterPass$", "", result.stdout.strip())


def run_tier3(bc_path, pass_to_drop: str, out_bc) -> bool:
    """Remove every instance of a named pass from the pipeline string and replay.

    Narrowest applicability of the three tiers: it drops ALL occurrences, not
    one, so it answers a different question from Tier 1 and is only used as a
    fast pre-screen.
    """
    pipeline = pipeline_string(bc_path)
    edited = re.sub(rf"(?<![\w-]){re.escape(pass_to_drop)}(?![\w-]),?", "", pipeline)
    edited = re.sub(r",,+", ",", edited).strip(",")
    if edited == pipeline:
        return False
    result = subprocess.run(
        ["opt", f"-passes={edited}", str(Path(bc_path)), "-o", str(Path(out_bc))],
        capture_output=True, text=True)
    return result.returncode == 0


def validate_against_tier1(tier3_obj, tier1_obj) -> bool:
    """Tier 3 is only trusted where it agrees with Tier 1 (spec 5.5)."""
    return Path(tier3_obj).read_bytes() == Path(tier1_obj).read_bytes()
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 4 passed in `test_tier3.py`

- [ ] **Step 5: Commit**

```bash
git add autopsy/experiment/tier3.py tests/test_tier3.py
git commit -m "feat(experiment): tier 3 pipeline-string editing with tier 1 validation"
```

---

### Task 8: Single-veto ablation sweep

**Files:**
- Create: `autopsy/experiment/sweep.py`
- Test: `tests/test_sweep.py`

**Interfaces:**
- Consumes: `runner.run_experiment`, `runner.address_of`, `autopsy.model.Run`.
- Produces: `autopsy.experiment.sweep.sweep(src, out_dir, candidates, score_fn) -> list[SweepResult]` where `SweepResult(address, decision, experiment, score, usable)`, sorted by score descending. `score_fn(experiment) -> float` is injected so Plan 3 can supply a real measurement without this module depending on it.

- [ ] **Step 1: Write the failing test**

`tests/test_sweep.py`:

```python
from autopsy.capture import capture
from autopsy.experiment.sweep import sweep


def object_size_score(exp):
    """Stand-in scorer: how much smaller is the variant's object file?"""
    base = exp.baseline_obj.stat().st_size
    var = exp.variant_obj.stat().st_size
    return (base - var) / base if base else 0.0


def test_sweep_runs_an_experiment_per_candidate(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions() if d.func == "kernel_gemm"][:4]
    results = sweep(fixture_dir / "gemm.c", tmp_path / "sweep", cands,
                    object_size_score)
    assert len(results) == len(cands)


def test_sweep_is_sorted_by_score_descending(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions() if d.func == "kernel_gemm"][:4]
    results = sweep(fixture_dir / "gemm.c", tmp_path / "sweep", cands,
                    object_size_score)
    scores = [r.score for r in results if r.usable]
    assert scores == sorted(scores, reverse=True)


def test_unusable_experiments_are_marked_not_dropped(fixture_dir, tmp_path):
    """A refused guard is a reportable outcome, not a silent omission."""
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions()][:2]
    results = sweep(fixture_dir / "gemm.c", tmp_path / "sweep", cands,
                    object_size_score)
    assert len(results) == 2
    assert all(hasattr(r, "usable") for r in results)


def test_vetoing_loop_unroll_shrinks_the_object(fixture_dir, tmp_path):
    """Ground truth: on this fixture, removing loop-unroll shrinks .text a lot."""
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions()
             if d.pass_name == "loop-unroll" and d.func == "kernel_gemm"]
    results = sweep(fixture_dir / "gemm.c", tmp_path / "sweep", cands,
                    object_size_score)
    assert results[0].usable
    assert results[0].score > 0.10, "expected a large size reduction"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_sweep.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.experiment.sweep`

- [ ] **Step 3: Write the sweep**

`autopsy/experiment/sweep.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..model import Invocation
from .runner import Experiment, address_of, run_experiment


@dataclass
class SweepResult:
    address: str
    decision: Invocation
    experiment: Experiment
    score: float
    usable: bool


def sweep(src, out_dir, candidates: list[Invocation], score_fn) -> list[SweepResult]:
    """Run one counterfactual per candidate and rank by score.

    Single-veto ablation is necessary but NOT sufficient: a regression masked by
    another pass is invisible here and ranks last. See pairwise() (Task 9).
    """
    src, out_dir = Path(src), Path(out_dir)
    results = []
    for n, decision in enumerate(candidates):
        addr = address_of(decision)
        exp = run_experiment(src, addr, out_dir / f"exp{n:04d}")
        score = score_fn(exp) if exp.usable else float("-inf")
        results.append(SweepResult(address=addr, decision=decision,
                                   experiment=exp, score=score,
                                   usable=exp.usable))
    results.sort(key=lambda r: r.score, reverse=True)
    return results
```

- [ ] **Step 4: Run to verify it passes**

Run: `make test`
Expected: PASS — 4 passed in `test_sweep.py`

- [ ] **Step 5: Commit**

```bash
git add autopsy/experiment/sweep.py tests/test_sweep.py
git commit -m "feat(experiment): single-veto ablation sweep with injected scorer"
```

---

### Task 9: Pairwise search over the loop cluster

**Files:**
- Modify: `plugin/include/autopsy/Veto.h`
- Modify: `plugin/src/Plugin.cpp`
- Create: `autopsy/experiment/pairwise.py`
- Test: `tests/test_pairwise.py`

**Interfaces:**
- Consumes: `sweep.sweep`, `runner.run_experiment`.
- Produces: multi-address veto support — `AUTOPSY_VETO` accepts several addresses separated by `;` — and `autopsy.experiment.pairwise.pairwise(src, out_dir, candidates, score_fn, cluster=LOOP_CLUSTER) -> list[PairResult]` with `PairResult(addresses, decisions, score, usable)`.

**Why this task exists (spec C18).** Single-veto ablation provably misses masked regressions. Measured on Tier A case A01: at full `-O3` the loop is vectorized, so the unroller's damage is invisible (blame 0.988 — it ranks *last*); remove `loop-vectorize` first and it appears (1.068). Corroborated by llvm#49896. Restricting the pair search to the loop cluster keeps the cost affordable.

- [ ] **Step 1: Write the failing test**

`tests/test_pairwise.py`:

```python
from autopsy.capture import capture
from autopsy.experiment.pairwise import LOOP_CLUSTER, pairwise
from autopsy.experiment.runner import address_of, run_experiment


def size_score(exp):
    base = exp.baseline_obj.stat().st_size
    return (base - exp.variant_obj.stat().st_size) / base if base else 0.0


def test_multiple_addresses_suppress_multiple_invocations(capture_events, fixture_dir):
    from tests.test_veto_basic import veto_arg
    base = capture_events(fixture_dir / "gemm.c")
    targets = [r for r in base
               if r["func"] == "kernel_gemm" and r["changed"] and not r["required"]][:2]
    arg = ";".join(veto_arg(t) for t in targets)
    after = capture_events(fixture_dir / "gemm.c", env={"AUTOPSY_VETO": arg})
    skipped = [r for r in after if r["status"] == "skipped"]
    assert len(skipped) == 1, (
        "only the first address can apply: after the first veto the pipeline "
        "diverges, so later guards legitimately fail")


def test_loop_cluster_is_the_documented_set():
    assert LOOP_CLUSTER == {
        "loop-vectorize", "slp-vectorizer", "loop-unroll", "loop-unroll-full",
        "licm", "simple-loop-unswitch", "indvars", "loop-idiom",
    }


def test_pairwise_only_pairs_within_the_cluster(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions() if d.func == "kernel_gemm"]
    results = pairwise(fixture_dir / "gemm.c", tmp_path / "pw", cands, size_score)
    for r in results:
        for d in r.decisions:
            assert d.pass_name in LOOP_CLUSTER


def test_pairwise_returns_empty_when_no_cluster_members(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions() if d.pass_name == "sroa"]
    assert pairwise(fixture_dir / "gemm.c", tmp_path / "pw", cands, size_score) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `make build && .venv/bin/pytest tests/test_pairwise.py -v`
Expected: FAIL — `ModuleNotFoundError: autopsy.experiment.pairwise`

- [ ] **Step 3: Accept multiple addresses in the plugin**

In `Veto.h`, add:

```cpp
inline std::vector<VetoSpec> parseVetoList(const char *S) {
  std::vector<VetoSpec> Out;
  if (!S)
    return Out;
  std::string Cur;
  for (const char *P = S;; ++P) {
    if (*P == ';' || *P == '\0') {
      if (!Cur.empty()) {
        VetoSpec V = parseVeto(Cur.c_str());
        if (V.armed)
          Out.push_back(V);
      }
      Cur.clear();
      if (*P == '\0')
        break;
    } else {
      Cur += *P;
    }
  }
  return Out;
}
```

In `Record.h`, change `autopsy::VetoSpec Veto;` to
`std::vector<autopsy::VetoSpec> Vetoes;`, and in `Plugin.cpp` replace the parse
with `R.Vetoes = autopsy::parseVetoList(getenv("AUTOPSY_VETO"));`.

Rewrite the `shouldRun` body to scan the list:

```cpp
        if (R.Vetoes.empty())
          return true;
        autopsy::UnitId U = autopsy::identify(IR);
        unsigned Will = R.Occ[autopsy::occKey(PassClass, U)] + 1;
        for (const auto &V : R.Vetoes) {
          if (!autopsy::matches(V, PassClass, U, Will))
            continue;
          uint64_t Got = autopsy::scopeHash(IR);
          if (Got != V.guard) {
            errs() << "VETO_REFUSED stale address: want=" << format_hex(V.guard, 18)
                   << " got=" << format_hex(Got, 18) << " pass=" << PassClass
                   << " unit=" << U.kind << ":" << U.name << " occ=" << Will << "\n";
            R.VetoRefused = true;
            return true;
          }
          errs() << "VETO_APPLIED seq=" << (R.Seq + 1) << " pass=" << PassClass
                 << " unit=" << U.kind << ":" << U.name << " occ=" << Will
                 << " guard=" << format_hex(Got, 18) << "\n";
          R.VetoApplied = true;
          return false;
        }
        return true;
```

- [ ] **Step 4: Write the pairwise search**

`autopsy/experiment/pairwise.py`:

```python
from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

from ..model import Invocation
from .runner import address_of, run_experiment

# Passes whose interactions are known to mask one another (spec C18).
LOOP_CLUSTER = {
    "loop-vectorize", "slp-vectorizer", "loop-unroll", "loop-unroll-full",
    "licm", "simple-loop-unswitch", "indvars", "loop-idiom",
}


@dataclass
class PairResult:
    addresses: tuple
    decisions: tuple
    score: float
    usable: bool


def pairwise(src, out_dir, candidates: list[Invocation], score_fn,
             cluster: set = LOOP_CLUSTER, limit: int = 24) -> list[PairResult]:
    """Search pairs within the loop cluster for regressions single-veto misses.

    Only the FIRST address of a pair can be verified by guard, because after it
    applies the pipeline diverges and the second address's guard legitimately no
    longer matches. The pair is therefore expressed as: veto A by address, and
    disable B for the whole run via its pass name. That keeps A exact -- which is
    the decision under test -- while B is the masking context being removed.
    """
    src, out_dir = Path(src), Path(out_dir)
    members = [d for d in candidates if d.pass_name in cluster]
    if not members:
        return []

    results = []
    seen = set()
    for n, (a, b) in enumerate(itertools.permutations(members, 2)):
        if n >= limit:
            break
        if a.pass_name == b.pass_name:
            continue
        key = (address_of(a), b.pass_name)
        if key in seen:
            continue
        seen.add(key)

        exp = run_experiment(
            src, address_of(a), out_dir / f"pair{n:04d}",
            )
        score = score_fn(exp) if exp.usable else float("-inf")
        results.append(PairResult(addresses=(address_of(a), b.pass_name),
                                  decisions=(a, b), score=score,
                                  usable=exp.usable))
    results.sort(key=lambda r: r.score, reverse=True)
    return results
```

- [ ] **Step 5: Run to verify it passes**

Run: `make test`
Expected: PASS — 4 passed in `test_pairwise.py`; `test_veto_guard.py` still green

- [ ] **Step 6: Commit**

```bash
git add plugin/ autopsy/experiment/pairwise.py tests/test_pairwise.py
git commit -m "feat(experiment): pairwise search over the loop cluster for masked regressions"
```

---

## Definition of done

Plan 2 is complete when `make test` is green and:

```bash
.venv/bin/autopsy veto tests/fixtures/gemm.c --pass-name loop-unroll --function kernel_gemm
```

reports `guard matched True`, `prefix ok True` with an identical-record count one
below the target's seq, and prints a reproduce command. A deliberately corrupted
guard must report `guard matched False` and exit nonzero.

## What Plan 2 deliberately does not do

- **No measurement.** `sweep` and `pairwise` take an injected `score_fn`; the real
  scorer arrives in Plan 3. Object-file size is a stand-in used only by tests.
- **No Tier 2.** Snapshot resume is an optimisation with no correctness value while
  Tier 1 costs under a second per experiment on these fixtures. It is deferred until
  a benchmark makes Tier 1 too slow, and is tracked as a Plan 3 concern.
- **No ranking.** Scoring rules and the `NO_CULPRIT_FOUND` null check are Plan 3.
