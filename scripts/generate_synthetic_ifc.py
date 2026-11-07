"""Generate a small semantic IFC fixture; no geometry or regulation thresholds.

Run: python scripts/generate_synthetic_ifc.py output.ifc
Requires the project's `3d` extra. Dimensions describe test data, not requirements.
"""
from pathlib import Path
import argparse

import ifcopenshell
import ifcopenshell.guid


def generate(path: str | Path, *, millimetres: bool = False):
    model = ifcopenshell.file(schema="IFC4")
    def root(kind, **kwargs):
        return model.create_entity(kind, GlobalId=ifcopenshell.guid.new(), **kwargs)
    length = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE",
                                 Prefix="MILLI" if millimetres else None)
    area = model.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE")
    project = root("IfcProject", Name="Synthetic test vessel",
                   UnitsInContext=model.create_entity("IfcUnitAssignment", Units=[length, area]))
    deck = root("IfcBuildingStorey", Name="Test deck")
    root("IfcRelAggregates", RelatingObject=project, RelatedObjects=[deck])
    factor = 1000 if millimetres else 1
    def props(element, **values):
        ps = root("IfcPropertySet", Name="Test dimensions", HasProperties=[
            model.create_entity("IfcPropertySingleValue", Name=name,
                                NominalValue=model.create_entity("IfcLengthMeasure", value * factor))
            for name, value in values.items()])
        root("IfcRelDefinesByProperties", RelatedObjects=[element], RelatingPropertyDefinition=ps)
    def floor_area(element, value):
        q = model.create_entity("IfcQuantityArea", Name="NetFloorArea", AreaValue=value)
        qs = root("IfcElementQuantity", Name="Qto_SpaceBaseQuantities", Quantities=[q])
        root("IfcRelDefinesByProperties", RelatedObjects=[element], RelatingPropertyDefinition=qs)
    spaces = [root("IfcSpace", Name=name, ObjectType=kind)
              for name, kind in [("Cabin A", "cabin"), ("Cabin B", "cabin"), ("Corridor", "corridor")]]
    for space, value in zip(spaces, [12.5, 15.0, 24.0]):
        floor_area(space, value)
    props(spaces[2], ClearWidth=1.1)
    root("IfcRelAggregates", RelatingObject=deck, RelatedObjects=spaces)
    doors = [root("IfcDoor", Name=name, OverallWidth=width * factor)
             for name, width in [("Cabin door", .9), ("Unmeasured clear opening", .85)]]
    props(doors[0], ClearWidth=.82)
    opening = root("IfcOpeningElement", Name="Passage opening")
    props(opening, ClearOpeningWidth=1.2)
    stairs = [root("IfcStair", Name=f"Stair {i}") for i in (1, 2)]
    flight = root("IfcStairFlight", Name="Flight", NumberOfRisers=9, NumberOfTreads=8,
                  RiserHeight=.18 * factor, TreadLength=.28 * factor)
    root("IfcRelAggregates", RelatingObject=stairs[0], RelatedObjects=[flight])
    root("IfcRelContainedInSpatialStructure", RelatingStructure=deck,
         RelatedElements=doors + [opening] + stairs)
    model.write(str(path))
    return model


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--millimetres", action="store_true")
    args = parser.parse_args()
    generate(args.output, millimetres=args.millimetres)
