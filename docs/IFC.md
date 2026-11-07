# IFC reader (D5)

See also: [3D-MODELS.md](3D-MODELS.md) (status and sources), [3D.md](3D.md) (mesh size check on the real IFC export).

Install the optional `3d` extra, then run these commands from the repository root:

```bash
uv pip install -p .venv -e '.[dev,3d]'
.venv/bin/python scripts/generate_synthetic_ifc.py /tmp/rulecheck-synthetic.ifc
.venv/bin/python -m app.design.ifc_reader /tmp/rulecheck-synthetic.ifc --project synthetic
```

The generator creates a semantic test model with one deck, two cabins, one corridor, two doors, an opening, two stairs and a stair flight. It contains explicit test dimensions, not regulation requirements, and has no renderable geometry. `--millimetres` generates length attributes in millimetres instead of metres; floor areas remain in square metres.

`read_ifc(path, project=...)` returns the existing `DesignFacts` contract. It reads spaces and net (or, if absent, gross) floor areas; explicit clear-width properties on doors, corridors and openings; door overall widths; stair-flight dimensions and riser/tread counts; storeys and slabs. A floor slab is a deck; other slabs remain slabs. Stair flights stay separate from stairways so counting stairs does not double-count their flights. Each element carries its GlobalId in both `id` and `provenance.element_id`, with `method="ifc"` and confidence 1.0. The shared `Provenance` contract has no `source` field, so no such field is added.

Lengths are converted to mm and areas to m2 using declared project or property/quantity units. Unknown units and missing measurements stay absent. OverallWidth is recorded as `overall_width`, never substituted for `clear_width`: the overall frame dimension does not prove usable clearance. Clear widths must be explicit `ClearWidth` or `ClearOpeningWidth` properties. Counts of elements can be evaluated by the existing evaluator; no aggregate elements or inferred escape routes are generated.

There is no generic design-reader entry point in the current app; this module provides a callable reader and CLI. PDF behavior and the PDF reader are unchanged. Real IFC exports, NWD conversion, geometry-derived clearances and regulatory findings are not validated by these synthetic tests. IFC tests skip when IfcOpenShell is absent.
