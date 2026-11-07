# Dana room extraction gold set

20 room labels and printed areas, visually checked against page 1 of `23007-01-101-0110-01-R2-14-General-arrangement.pdf`. The JSON records the PDF SHA-256 and text-label locations for audit. Coordinates describe labels, not room outlines. Line breaks in room names are flattened to spaces; m² is normalized typographically. The drawing spelling `CHEIF MANAGER` is preserved. Deck names are location metadata from the drawing.

This is a partial inventory across four decks. Report matched gold rooms / 20 as sampled room recall, and correct printed areas / matched gold rooms as area accuracy. Match by deck and label location as well as name; cabins and other labels can repeat elsewhere. Do not count detections outside this sample as false positives. Full-output precision requires reviewing unmatched detections or completing an exhaustive inventory. Do not tune a model against these labels and then describe its score as held-out performance.

This starts D7 with room-extraction ground truth. It does not supply planted regulation violations or complete the findings precision/recall evaluation. No model API was called.
