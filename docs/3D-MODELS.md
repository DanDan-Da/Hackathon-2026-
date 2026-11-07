# 3D models

## The sample: `12100-RCRV-199_07-08-2021.nwd`
- This is the Navisworks model of the Regional Class Research Vessel, 305 MB, in the proprietary `LcUStream` format. **It is not in git**, because GitHub's file limit is 100 MB. Share it outside git (USB or a cloud drive) and put it in `Files/`.
- No open-source library reads `.nwd`, so it has to be converted first.

## Conversion options (D4: spend at most 1h)
1. **Navisworks Manage or Simulate** runs on Windows and has a free Autodesk education licence. Open the NWD and export it to **IFC** or **FBX**. If the export is huge, hide everything except one deck or fire zone first. The free viewer, **Navisworks Freedom, can't export**.
2. **Autodesk Platform Services Model Derivative API** can translate an uploaded NWD. Worth trying, but don't count on it.
3. **Fallback: a synthetic IFC.** Script a small deck with `ifcopenshell` (corridor, cabins, doors, two stairs) and plant known violations, such as a 760 mm accessible door or only one escape stair. This is the most reliable accuracy demo, because the true answers are known exactly.

## In the pipeline
- `app/design/ifc_reader.py` turns IFC into `DesignElement`s, with `provenance.method="ifc"` and `element_id` set to the IFC GlobalId so a finding can point back to the 3D element.
- glTF, OBJ and STL can be read with `trimesh`, but they give bounding boxes only, with no semantics.
- Later, as roadmap: export findings as BCF so they open directly in Navisworks or Revit.
