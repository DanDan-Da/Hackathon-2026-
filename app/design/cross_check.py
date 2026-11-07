"""D4: compare mesh extents with the particulars the design documents state.

Deterministic. A mesh bounding box includes masts, antennas, cranes and other appendages, so a
difference is never a failure: outside tolerance -> needs_review, inside -> pass. Missing stated
value -> needs_review. Both sides are cited (mesh Provenance + stated Provenance/quote).

    python -m app.design.cross_check MESH.(json|ifc) STATED.(json|pdf) [--tolerance 0.10]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.design.particulars_text import load_labels
from app.models import DesignFacts, Finding, Provenance, SourceRef, Status

DEFAULT_TOLERANCE = 0.10
REGIME = "design-consistency"   # internal consistency check, not a regulation
UNIT_MISMATCH_RATIO = 5.0


def _stated(facts: DesignFacts) -> dict[str, tuple[float, Provenance, str]]:
    out: dict[str, tuple[float, Provenance, str]] = {}
    for e in facts.elements:
        if e.type == "stated_particular" and isinstance(e.properties.get("value"), (int, float)):
            out[e.properties["parameter"]] = (float(e.properties["value"]), e.provenance,
                                              str(e.properties.get("quote", "")))
    p = facts.particulars   # fallback: ShipParticulars filled by pdf_text.parse_particulars
    for field, key in (("length_overall_m", "length_overall"), ("breadth_m", "beam")):
        v = getattr(p, field)
        if v is not None and key not in out and p.provenance:
            out[key] = (v * 1000.0, p.provenance[0], f"{field} = {v} m")
    return out


def cross_check(mesh: DesignFacts, stated: DesignFacts, tolerance: float = DEFAULT_TOLERANCE,
                labels_path: str | Path | None = None) -> list[Finding]:
    cfg = load_labels(labels_path)
    ext = next((e for e in mesh.elements if e.type == "ship_extent"), None)
    if ext is None:
        raise ValueError("mesh facts contain no ship_extent element")
    have = _stated(stated)
    out: list[Finding] = []
    for prop, parts in cfg["comparisons"].items():
        rule_id = f"mesh-vs-particulars.{prop}"
        mval = ext.properties.get(prop)
        note = cfg.get("comparison_notes", {}).get(prop, "")
        doc = stated.source_files[0] if stated.source_files else "stated particulars"
        if not isinstance(mval, (int, float)):
            continue
        missing = [p for p in parts if p not in have]
        if missing:
            out.append(Finding(
                rule_id=rule_id, status=Status.needs_review, element_id=ext.id,
                message=f"No stated {'/'.join(missing)} found, cannot compare mesh {prop} ({mval:.0f} mm).",
                measured=mval, rule_source=SourceRef(document=doc, regime=REGIME, quote=""),
                evidence=[ext.provenance]))
            continue
        sval = sum(have[p][0] for p in parts)
        prov = [have[p][1] for p in parts]
        quote = " ; ".join(have[p][2] for p in parts)
        diff = (mval - sval) / sval if sval else float("inf")
        ok = abs(diff) <= tolerance
        msg = (f"Mesh {prop} {mval:.0f} mm vs stated {sval:.0f} mm ({diff:+.1%}"
               f"{'; ' + note if note else ''}). ")
        if ok:
            msg += f"Within {tolerance:.0%} tolerance."
        else:
            msg += (f"Outside {tolerance:.0%} tolerance. The mesh bounding box includes masts, antennas and "
                    f"other appendages, so this is a flag for review, not a failure.")
            ratio = mval / sval if sval else 0
            if ratio and (ratio > UNIT_MISMATCH_RATIO or ratio < 1 / UNIT_MISMATCH_RATIO):
                msg += " The size is off by more than 5x: check the length unit of the mesh file."
        out.append(Finding(
            rule_id=rule_id, status=Status.passed if ok else Status.needs_review, element_id=ext.id,
            message=msg, measured=mval, required=f"{sval:.0f} mm +/- {tolerance:.0%}",
            rule_source=SourceRef(document=prov[0].file, regime=REGIME, page=prov[0].page, quote=quote),
            evidence=[ext.provenance, *prov], method="deterministic",
            reasoning="Deterministic comparison of mesh extent and stated particulars."))
    return out


def _load(arg: str, kind: str) -> DesignFacts:
    p = Path(arg)
    if p.suffix.lower() == ".json":
        return DesignFacts.model_validate_json(p.read_text())
    if kind == "mesh" and p.suffix.lower() == ".ifc":
        from app.design.mesh_reader import read_mesh_extent
        return read_mesh_extent(p)
    if kind == "stated" and p.suffix.lower() == ".pdf":
        from app.design.particulars_text import read_stated_particulars
        return read_stated_particulars(p)
    raise SystemExit(f"unsupported {kind} input: {arg}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.design.cross_check", description=__doc__)
    ap.add_argument("mesh"); ap.add_argument("stated")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    a = ap.parse_args(argv)
    findings = cross_check(_load(a.mesh, "mesh"), _load(a.stated, "stated"), a.tolerance)
    print(json.dumps([f.model_dump(mode="json") for f in findings], indent=2))
    for f in findings:
        print(f"[{f.status.value}] {f.rule_id}: {f.message}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
