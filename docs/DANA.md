# Enrich step (`app/design/enrich.py`)

`python -m app.design.enrich FACTS.json PDF [-o OUT.json] [--report REPORT.json]`

Pure deterministic post-processing of extracted `DesignFacts` with the drawing's own text layer. No LLM. All vocabulary is in `app/design/enrich_config.json`.

## What is read, from where
- **ship_type**: the vessel-type phrase printed in the text layer (config list, e.g. "Research Vessel" from the class line). Copied as printed, with `pdf_text` provenance (bbox, 0.9). Never overwrites an existing value. Left unset if no phrase or more than one different phrase is found.
- **space_type**: from the element name via config regexes. Set only when exactly one space_type entry matches and none is set yet. `properties.space_type_source = "name"`. Element confidence is unchanged.
- **Cabin summary** (`--report`): lines like `SHELTER DECK: 6 SINGLE AND 10 DOUBLE CABINS` (a header ending in `:` takes the next line) are compared with the number of extracted `cabin` elements. One `Finding`: `pass` if equal, `needs_review` if not. Elements are not altered.

## Limits
- Names only: elements without a recognisable name (e.g. unnamed stairways, doors, most technical spaces) keep `space_type = None`.
- Cabin comparison is total only. Extracted cabins have no deck, so the per-deck split cannot be checked.
- A mismatch does not say which side is wrong (extraction miss/extra, or an incomplete printed summary).
- Config vocabulary is English-only and only as broad as the drawing needs; extend the JSON, not the code.

## Result on the demo GA (`designs/demo/ga.pdf`)
- ship_type: `Research Vessel`.
- space_type set on 69 of 189 elements: toilet 36, cabin 29, hospital 1, laundry 1, mess 1, galley 1.
- Printed cabins: 28 (shelter deck 6 single + 10 double = 16; fo'c'sle deck 12 single). Extracted: 29. Finding: `needs_review`.
