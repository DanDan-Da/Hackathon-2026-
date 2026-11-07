"""IFC semantic attributes and quantities -> DesignFacts, without geometry or AI.

Only explicit measurements are extracted. Overall door width is kept separately
from clear width; it cannot establish clearance for a compliance check.
Install the optional `3d` extra to use this reader.
"""
from __future__ import annotations

import math
from pathlib import Path

from app.check.units import to_base
from app.models import DesignElement, DesignFacts, Provenance


def _unit_scale(unit, unit_type: str) -> float | None:
    """Scale to metres / square metres; never assume an absent unit is SI."""
    from ifcopenshell.util.unit import get_prefix_multiplier

    if unit is None or getattr(unit, "UnitType", None) != unit_type:
        return None
    if unit.is_a("IfcSIUnit"):
        expected = "METRE" if unit_type == "LENGTHUNIT" else "SQUARE_METRE"
        if unit.Name != expected:
            return None
        power = 1 if unit_type == "LENGTHUNIT" else 2
        return get_prefix_multiplier(unit.Prefix) ** power
    if unit.is_a("IfcConversionBasedUnit"):
        factor = unit.ConversionFactor
        base = _unit_scale(factor.UnitComponent, unit_type)
        if base is not None:
            return float(factor.ValueComponent.wrappedValue) * base
    return None


def _measurement(model, value, unit_type: str, unit=None) -> float | None:
    from ifcopenshell.util.unit import get_project_unit

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    if unit is None:
        unit = get_project_unit(model, unit_type)
    scale = _unit_scale(unit, unit_type)
    if scale is None or not math.isfinite(scale) or scale <= 0:
        return None
    si_value = float(value) * scale
    return to_base(si_value, "m" if unit_type == "LENGTHUNIT" else "m2")[0]


def _property_measurement(model, psets, names, unit_type):
    """Prefer explicit names in order; conflicting same-name values stay unknown."""
    for name in names:
        values = []
        found = False
        for pset in psets.values():
            entry = pset.get(name)
            if not isinstance(entry, dict):
                continue
            found = True
            prop = model.by_id(entry["id"])
            value = _measurement(model, entry["value"], unit_type, getattr(prop, "Unit", None))
            if value is None:
                return None
            values.append(value)
        if found:
            return values[0] if all(math.isclose(v, values[0]) for v in values) else None
    return None


def _deck(element) -> str | None:
    from ifcopenshell.util.element import get_aggregate, get_container

    current = element
    seen = set()
    while current is not None and current.id() not in seen:
        seen.add(current.id())
        if current.is_a("IfcBuildingStorey"):
            return current.Name or current.GlobalId
        current = get_container(current, should_get_direct=True) or get_aggregate(current)
    return None


def _space_kind(element) -> str | None:
    # Use only explicit type labels (or an exact name), not fuzzy inference.
    label = (element.ObjectType or "").strip().lower()
    if label:
        return label
    if (element.Name or "").strip().lower() == "corridor":
        return "corridor"
    return None


def read_ifc(path: str | Path, *, project: str | None = None) -> DesignFacts:
    """Read IFC spaces, doors, openings, stairs and decks with GlobalId provenance.

    No geometry is measured, missing values stay absent, and no ship particulars
    or compliance requirements are inferred. Per-element output supports counts
    in the existing evaluator without inventing aggregate facts.
    """
    try:
        import ifcopenshell
        from ifcopenshell.util.element import get_psets
    except ImportError as exc:
        raise ImportError('IFC reading requires the optional "3d" extra: install .[3d]') from exc

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    model = ifcopenshell.open(str(path))
    facts = DesignFacts(project=project if project is not None else path.stem, source_files=[str(path)])
    classes = {
        "IfcSpace": "space", "IfcDoor": "door", "IfcOpeningElement": "opening",
        "IfcStair": "stairway", "IfcStairFlight": "stair_flight",
        "IfcBuildingStorey": "deck", "IfcSlab": "slab",
    }
    for ifc_class, kind in classes.items():
        for item in model.by_type(ifc_class):
            psets = get_psets(item, verbose=True)
            properties: dict[str, float | str | bool] = {"ifc_class": item.is_a()}
            space_type = _space_kind(item) if ifc_class == "IfcSpace" else None
            element_type = "corridor" if space_type == "corridor" else kind
            if ifc_class == "IfcSlab" and getattr(item, "PredefinedType", None) == "FLOOR":
                element_type = "deck"
            if ifc_class == "IfcSpace":
                area = _property_measurement(model, psets, ("NetFloorArea", "GrossFloorArea", "Area"), "AREAUNIT")
                if area is not None:
                    properties["area"] = area
            width = _property_measurement(model, psets, ("ClearWidth", "ClearOpeningWidth"), "LENGTHUNIT")
            if width is not None:
                properties["clear_width"] = width
            for attribute, name in (("OverallWidth", "overall_width"),
                                    ("RiserHeight", "riser_height"), ("TreadLength", "tread_length")):
                value = _measurement(model, getattr(item, attribute, None), "LENGTHUNIT")
                if value is not None:
                    properties[name] = value
            for attribute, name in (("NumberOfRisers", "number_of_risers"), ("NumberOfTreads", "number_of_treads")):
                value = getattr(item, attribute, None)
                if value is not None and value >= 0:
                    properties[name] = value
            facts.elements.append(DesignElement(
                id=item.GlobalId, type=element_type, name=item.Name, deck=_deck(item),
                space_type=space_type, properties=properties,
                provenance=Provenance(file=str(path), element_id=item.GlobalId, method="ifc", confidence=1.0),
            ))
    return facts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--project")
    args = parser.parse_args()
    print(read_ifc(args.path, project=args.project).model_dump_json(indent=2))
