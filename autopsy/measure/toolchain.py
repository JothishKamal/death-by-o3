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
