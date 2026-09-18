from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DecisionAddress:
    """Self-verifying address of one pass invocation (spec §5.4)."""

    pass_class: str
    kind: str
    unit_name: str
    func: str
    occurrence: int
    guard: str

    def as_dict(self) -> dict:
        return {
            "pass_class": self.pass_class,
            "kind": self.kind,
            "unit_name": self.unit_name,
            "func": self.func,
            "occurrence": self.occurrence,
            "guard": self.guard,
        }


@dataclass(frozen=True)
class Invocation:
    seq: int
    parent_seq: int
    depth: int
    pass_class: str
    pass_name: str
    role: str
    kind: str
    unit_name: str
    func: str
    occurrence: int
    required: bool
    status: str
    changed: bool
    guard: str
    bisect_index: int
    wall_ns: int
    blobs_after: tuple = ()
    metrics_before: dict | None = None
    metrics_after: dict | None = None

    @property
    def is_decision(self) -> bool:
        """A Decision is an invocation that changed the IR. Scaffolding never is."""
        return self.changed and self.role == "transform"

    @property
    def vetoable(self) -> bool:
        """Required passes never reach shouldRun, so they cannot be vetoed."""
        return not self.required and self.role == "transform"

    @property
    def address(self) -> DecisionAddress:
        return DecisionAddress(
            pass_class=self.pass_class, kind=self.kind, unit_name=self.unit_name,
            func=self.func, occurrence=self.occurrence, guard=self.guard,
        )

    @classmethod
    def from_json(cls, d: dict) -> "Invocation":
        return cls(
            seq=d["seq"], parent_seq=d["parent_seq"], depth=d["depth"],
            pass_class=d["pass_class"], pass_name=d["pass_name"], role=d["role"],
            kind=d["kind"], unit_name=d["unit_name"], func=d["func"],
            occurrence=d["occurrence"], required=d["required"], status=d["status"],
            changed=d["changed"], guard=d["guard"],
            bisect_index=d["bisect_index"], wall_ns=d["wall_ns"],
            blobs_after=tuple(d.get("blobs_after", ())),
            metrics_before=d.get("metrics_before"),
            metrics_after=d.get("metrics_after"),
        )


@dataclass
class Run:
    invocations: list[Invocation]
    cas_dir: Path | None = None
    _by_parent: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self._by_parent = {}
        for i in self.invocations:
            self._by_parent.setdefault(i.parent_seq, []).append(i)

    def decisions(self) -> list[Invocation]:
        return [i for i in self.invocations if i.is_decision]

    def tree_roots(self) -> list[Invocation]:
        return self._by_parent.get(-1, [])

    def children(self, seq: int) -> list[Invocation]:
        return self._by_parent.get(seq, [])

    def by_function(self, name: str) -> list[Invocation]:
        return [i for i in self.invocations if i.func == name]

    def blob(self, blob_id: str) -> str:
        if self.cas_dir is None:
            raise ValueError("this Run was captured without a CAS directory")
        return (self.cas_dir / blob_id[:2] / blob_id[2:]).read_text()
