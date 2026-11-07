"""Generated IFC only: no network, real designs or regulation constants."""
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
from scripts.generate_synthetic_ifc import generate
from app.design.ifc_reader import read_ifc


@pytest.mark.parametrize("millimetres", [False, True])
def test_spaces_widths_counts_and_provenance(tmp_path, millimetres):
    path = tmp_path / "deck.ifc"
    model = generate(path, millimetres=millimetres)
    facts = read_ifc(path, project="fixture")
    assert facts.project == "fixture"
    assert facts.source_files == [str(path)]
    by_name = {e.name: e for e in facts.elements}
    assert by_name["Cabin A"].properties["area"] == 12.5
    assert by_name["Cabin B"].space_type == "cabin"
    assert by_name["Corridor"].type == "corridor"
    assert by_name["Corridor"].properties["clear_width"] == pytest.approx(1100)
    assert by_name["Cabin door"].properties["clear_width"] == pytest.approx(820)
    assert by_name["Cabin door"].properties["overall_width"] == pytest.approx(900)
    # OverallWidth is exact overall width, not proof of unobstructed clear width.
    assert "clear_width" not in by_name["Unmeasured clear opening"].properties
    assert by_name["Passage opening"].properties["clear_width"] == pytest.approx(1200)
    assert sum(e.type == "stairway" for e in facts.elements) == 2
    assert by_name["Flight"].properties["number_of_risers"] == 9
    assert by_name["Flight"].properties["riser_height"] == pytest.approx(180)
    assert len(facts.elements) == 10
    for element in facts.elements:
        assert model.by_guid(element.id)
        assert element.provenance.element_id == element.id
        assert element.provenance.method == "ifc"
        assert element.provenance.confidence == 1.0
        assert element.provenance.file == str(path)
        if element.name != "Test deck":
            assert element.deck == "Test deck"


def test_quantity_unit_overrides_project_units(tmp_path):
    path = tmp_path / "units.ifc"
    model = generate(path, millimetres=True)
    q = model.by_type("IfcQuantityArea")[0]
    q.Unit = model.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE", Prefix="MILLI")
    q.AreaValue = 12500000
    prop = model.by_type("IfcPropertySingleValue")[0]
    prop.Unit = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    prop.NominalValue = model.create_entity("IfcLengthMeasure", 1.3)
    model.write(str(path))
    by_name = {e.name: e for e in read_ifc(path).elements}
    assert by_name["Cabin A"].properties["area"] == pytest.approx(12.5)
    assert by_name["Corridor"].properties["clear_width"] == pytest.approx(1300)


def test_unknown_units_and_missing_values_stay_unknown(tmp_path):
    path = tmp_path / "unknown.ifc"
    model = generate(path)
    model.by_type("IfcProject")[0].UnitsInContext = None
    model.by_type("IfcDoor")[0].OverallWidth = None
    model.write(str(path))
    facts = read_ifc(path)
    assert facts.project == "unknown"
    for element in facts.elements:
        assert not ({"area", "clear_width", "overall_width", "riser_height"} & element.properties.keys())


def test_missing_file_is_not_an_empty_success(tmp_path):
    with pytest.raises((FileNotFoundError, OSError)):
        read_ifc(tmp_path / "absent.ifc")


def test_conversion_based_units_and_floor_slabs(tmp_path):
    path = tmp_path / "feet.ifc"
    model = generate(path)
    metre = model.by_type("IfcProject")[0].UnitsInContext.Units[0]
    dimensions = model.create_entity("IfcDimensionalExponents", 1, 0, 0, 0, 0, 0, 0)
    factor = model.create_entity("IfcMeasureWithUnit",
                                 ValueComponent=model.create_entity("IfcLengthMeasure", .3048),
                                 UnitComponent=metre)
    foot = model.create_entity("IfcConversionBasedUnit", Dimensions=dimensions,
                               UnitType="LENGTHUNIT", Name="foot", ConversionFactor=factor)
    model.by_type("IfcProject")[0].UnitsInContext.Units = [foot]
    slab = model.create_entity("IfcSlab", GlobalId=ifcopenshell.guid.new(), Name="Floor", PredefinedType="FLOOR")
    model.write(str(path))
    by_name = {e.name: e for e in read_ifc(path).elements}
    assert by_name["Cabin door"].properties["clear_width"] == pytest.approx(.82 * 304.8)
    assert "area" not in by_name["Cabin A"].properties
    assert by_name["Floor"].type == "deck"
    assert by_name["Floor"].id == slab.GlobalId


def test_inherited_clear_width_and_conflicting_values(tmp_path):
    path = tmp_path / "typed.ifc"
    model = generate(path)
    door = model.by_type("IfcDoor")[1]
    width = model.create_entity("IfcPropertySingleValue", Name="ClearWidth",
                                NominalValue=model.create_entity("IfcLengthMeasure", .77))
    pset = model.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(),
                               Name="Type clearance", HasProperties=[width])
    dtype = model.create_entity("IfcDoorType", GlobalId=ifcopenshell.guid.new(),
                                HasPropertySets=[pset], PredefinedType="DOOR", OperationType="NOTDEFINED")
    model.create_entity("IfcRelDefinesByType", GlobalId=ifcopenshell.guid.new(),
                        RelatingType=dtype, RelatedObjects=[door])
    model.write(str(path))
    by_name = {e.name: e for e in read_ifc(path).elements}
    assert by_name[door.Name].properties["clear_width"] == pytest.approx(770)
    other = model.create_entity("IfcPropertySingleValue", Name="ClearWidth",
                                NominalValue=model.create_entity("IfcLengthMeasure", .7))
    other_set = model.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(),
                                    Name="Conflicting clearance", HasProperties=[other])
    model.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
                        RelatingPropertyDefinition=other_set, RelatedObjects=[door])
    model.write(str(path))
    by_name = {e.name: e for e in read_ifc(path).elements}
    assert "clear_width" not in by_name[door.Name].properties
