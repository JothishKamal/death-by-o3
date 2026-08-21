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
