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
