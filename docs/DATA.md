# Sample data (not in git)

Exceptions: the two demo facts files `designs/demo/demo_*.json` (extracted from the public Dana GA) are in git, see `docs/DEMO.md`. The PDFs themselves are not.

Put these files in `Files/` locally, which git ignores. Copy the ones you use into `designs/<project>/` or `knowledge/rules/<REGIME>/`. The challenge brief lists public sources; treat those links as examples only and never hardcode them.

| File | What it is |
|---|---|
| `04650 Rev.H General Arrangement GO SARS.pdf` | GA drawing, research vessel G.O. Sars |
| `23007-01-101-0110-01-R2-14-General-arrangement.pdf` | GA drawing, Dana |
| `9281-ga-plan-2017117-01-model-anynomized.pdf` | GA drawing, anonymised |
| `6096-070-001-(J) General Arrangement.pdf` | GA drawing |
| `12100-000-01_design_summary_report_rev_a.pdf`, `rcrv-particulars.pdf`, `development_of_rcrv_design.pdf`, `12100-054-01_green_ship_initiatives_rev_p3.pdf` | RCRV design docs and particulars |
| `noaa_30507_DS1.pdf`, `6790.4_Final.pdf` | Studies |
| `12100-RCRV-199_07-08-2021.nwd` | RCRV 3D model (Navisworks, 305 MB), see `3D-MODELS.md` |

## Regulations to put in `knowledge/rules/`
Use publicly available text:
- **PVAG** (US Access Board) and **ADA**: full text, with concrete numbers. Start with these.
- **COLREG**
- **SOLAS / MARPOL / Load Line** summaries from IMO
- **DNV rules**, via DNV Veracity if you have access

## 3D model as IFC
`~/Downloads/12100-RCRV-199_07-08-2021.ifc` (303 MB, IFC4, geometry only: 84,583 anonymous `IfcBuildingElementProxy` parts, no psets or spaces) is a conversion of the NWD above. Keep it outside the repo (or in `Files/`, which git ignores). Read it with `app/design/mesh_reader.py`; see `3D.md` for what it gives and its unit problem.
