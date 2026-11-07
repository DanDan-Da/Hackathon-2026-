"""Mesh extent from a tiny generated geometry-only IFC (same shape as the real RCRV export)."""
import pytest

pytest.importorskip("ifcopenshell")
from app.design import mesh_reader
from app.design.mesh_reader import read_mesh_extent


def ifc_text(unit_prefix=".MILLI.", pts_a=None, offset=(0.0, 0.0, 0.0)):
    pts_a = pts_a or [(0, 0, 0), (100, 0, 0), (0, 20, 0), (0, 0, 5)]
    pts_b = [(10, 5, 1), (30, 8, 40), (20, 9, 2)]

    def lst(p):
        return "(" + ",".join("(%s)" % ",".join(repr(float(c)) for c in t) for t in p) + ")"

    return f"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]'),'2;1');
FILE_NAME('t.ifc','2026-01-01T00:00:00',(''),(''),'x','x','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCSIUNIT(*,.LENGTHUNIT.,{unit_prefix},.METRE.);
#2=IFCUNITASSIGNMENT((#1));
#3=IFCCARTESIANPOINT((0.,0.,0.));
#4=IFCAXIS2PLACEMENT3D(#3,$,$);
#5=IFCPROJECT('3AP3wEZVv1y8lgrUfjrJNu',$,'P',$,$,$,$,$,#2);
#6=IFCLOCALPLACEMENT($,#4);
#7=IFCCARTESIANPOINT(({offset[0]!r},{offset[1]!r},{offset[2]!r}));
#8=IFCAXIS2PLACEMENT3D(#7,$,$);
#9=IFCLOCALPLACEMENT(#6,#8);
#10=IFCCARTESIANPOINTLIST3D({lst(pts_a)});
#11=IFCTRIANGULATEDFACESET(#10,$,$,((1,2,3),(1,2,4)),$);
#12=IFCSHAPEREPRESENTATION($,'Body','Tessellation',(#11));
#13=IFCPRODUCTDEFINITIONSHAPE($,$,(#12));
#14=IFCBUILDINGELEMENTPROXY('15Vvf0TLn83gQBuFohS8Fs',$,'Part 1',$,'Part 1',#9,#13,$,.NOTDEFINED.);
#15=IFCCARTESIANPOINTLIST3D({lst(pts_b)});
#16=IFCTRIANGULATEDFACESET(#15,$,$,((1,2,3)),$);
#17=IFCSHAPEREPRESENTATION($,'Body','Tessellation',(#16));
#18=IFCPRODUCTDEFINITIONSHAPE($,$,(#17));
#19=IFCBUILDINGELEMENTPROXY('25Vvf0TLn83gQBuFohS8Fs',$,'Part 2',$,'Part 2',#6,#18,$,.NOTDEFINED.);
ENDSEC;
END-ISO-10303-21;
"""


def write(tmp_path, **kw):
    p = tmp_path / "m.ifc"
    p.write_text(ifc_text(**kw))
    return p


def ext(facts):
    (el,) = [e for e in facts.elements if e.type == "ship_extent"]
    return el


def test_known_box_with_placement_offset(tmp_path):
    # part 1 spans x 0..100 y 0..20 z 0..5, shifted by +50 in x (-> 50..150); part 2 z up to 40
    p = write(tmp_path, offset=(50.0, 0.0, 0.0))
    facts = read_mesh_extent(p, project="t", cache_dir=tmp_path / "c")
    el = ext(facts)
    assert el.properties["length_overall"] == pytest.approx(150.0 - 10.0)  # x from 10 (part 2) to 150
    assert el.properties["beam"] == pytest.approx(20.0)
    assert el.properties["height"] == pytest.approx(40.0)
    assert el.properties["length_axis"] == "X"
    assert el.provenance.method == "mesh"
    assert el.provenance.confidence <= 0.7
    assert el.provenance.file == str(p)
    assert facts.source_files == [str(p)]


def test_unit_converted_to_mm(tmp_path):
    p = write(tmp_path, unit_prefix="$")  # plain metres
    el = ext(read_mesh_extent(p, cache_dir=tmp_path / "c"))
    assert el.properties["length_overall"] == pytest.approx(100_000.0)


def test_cache_hit_and_invalidation(tmp_path, monkeypatch):
    p = write(tmp_path)
    cdir = tmp_path / "c"
    read_mesh_extent(p, cache_dir=cdir)
    assert list(cdir.glob("*.json"))
    monkeypatch.setattr(mesh_reader, "_scan", lambda *a, **k: pytest.fail("rescanned"))
    el = ext(read_mesh_extent(p, cache_dir=cdir))
    assert el.properties["height"] == pytest.approx(40.0)
    monkeypatch.undo()
    p.write_text(ifc_text(pts_a=[(0, 0, 0), (500, 0, 0), (0, 20, 0), (0, 0, 5)]))
    el = ext(read_mesh_extent(p, cache_dir=cdir))
    assert el.properties["length_overall"] == pytest.approx(500.0)


def test_no_geometry_raises(tmp_path):
    p = tmp_path / "e.ifc"
    p.write_text("ISO-10303-21;\nDATA;\n#1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);\nENDSEC;\nEND-ISO-10303-21;\n")
    with pytest.raises(ValueError):
        read_mesh_extent(p, cache_dir=tmp_path / "c")


def test_generated_file_is_valid_ifc(tmp_path):
    import ifcopenshell
    m = ifcopenshell.open(str(write(tmp_path)))
    assert len(m.by_type("IfcBuildingElementProxy")) == 2
