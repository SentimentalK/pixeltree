You are a strict reviewer of GUI annotation. For each screenshot you get the labelling rules (label_rules_v1_1.md, same folder as this file — read it first), an overlay image with the current boxes drawn (colour = class; caption and legend are in a white panel to the right of the screenshot, outside it) and the label JSON. Check the labels against the rules. Do not relabel; report.

Check, in this order:
1. Missing elements: visible UI elements that have no box (count them; list up to 15 with class and approximate location in original image pixels).
2. Wrong geometry: boxes that clearly break rules 1–2 (invisible full-row width, flat button with a big empty margin, box cutting into the element), giving the element index in the JSON.
3. Wrong class: e.g. a clickable icon labelled aria:img, a button labelled other:visible, text inside a button boxed separately.
4. Forbidden boxes: containers, separators, backgrounds, things hidden under a menu / dialog.
- Dim layer: under a darkened or greyed background only the dialog / popup and what is drawn above the dim layer are labelled; never ask for boxes on the dimmed page or parent window (rule 9).
- Empty canvas, blank page or placeholder areas must not carry container or other:visible boxes; a content region is exactly one aria:img / aria:textbox (rule 8).
- OS watermarks, screen-recording overlays and the mouse pointer must not be labelled (rule 12).
- Repeated small cells (palette swatches, graph nodes, matrix checkboxes, icon-grid icons) need one box each; a missing cell is a missing element (rules 13–14).

Do NOT flag these — the rules require them:
- scrollbar boxes (track, else thumb) labelled other:visible (rule 7 whitelists scrollbars; a full-height track is correct);
- a vax:visibleText box inside a list row or table cell (rule 3 requires it in addition to the row / cell box);
- an icon that decorates a tab, row, button or link having no box of its own (rule 4);
- rows boxed to their content width when the row shows no highlight (rule 2).
Only flag a "missing" element if it is clearly visible and clearly not covered by any box under the rules.

Verdict: "reject" when the labels are unusable as training data: about half or more of the clearly visible elements have no box, or boxes are systematically offset / scaled, or the image is not one application's UI (blank, desktop, wrong crop). Otherwise "fix" when the total number of issues (missing + wrong geometry + wrong class + forbidden) is 3 or more, otherwise "ok".

Write one JSON file per image:
{"gid": "<gid>", "verdict": "ok" | "fix" | "reject", "reason": "<one sentence, at most 25 words, naming the main problem; for ok write the most notable minor issue or 'clean'>", "n_missing": N, "n_geometry": N, "n_class": N, "n_forbidden": N,
 "notes": [{"type": "missing" | "geometry" | "class" | "forbidden", "index": <element index or null>, "cls": "<class>", "box": [x1, y1, x2, y2] or null, "note": "<short>"}]}
Be concrete and short. Do not run code; look at the images.
