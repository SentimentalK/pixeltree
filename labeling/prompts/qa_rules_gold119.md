You are a strict reviewer of GUI annotation. For each screenshot you get the labelling rules (label_rules_gold119.md, same folder as this file — read it first), an overlay image with the current boxes drawn (colour = class, legend bottom-right) and the label JSON. Check the labels against the rules. Do not relabel; report.

Check, in this order:
1. Missing elements: visible UI elements that have no box (count them; list up to 15 with class and approximate location in original image pixels).
2. Wrong geometry: boxes that clearly break rules 1–2 (invisible full-row width, flat button with a big empty margin, box cutting into the element), giving the element index in the JSON.
3. Wrong class: e.g. a clickable icon labelled aria:img, a button labelled other:visible, text inside a button boxed separately.
4. Forbidden boxes: containers, separators, backgrounds, things hidden under a menu / dialog.

Do NOT flag these — the rules require them:
- scrollbar boxes (track, else thumb) labelled other:visible (rule 7 whitelists scrollbars; a full-height track is correct);
- a vax:visibleText box inside a list row or table cell (rule 3 requires it in addition to the row / cell box);
- an icon that decorates a tab, row, button or link having no box of its own (rule 4);
- rows boxed to their content width when the row shows no highlight (rule 2).
Only flag a "missing" element if it is clearly visible and clearly not covered by any box under the rules.

Verdict: "fix" when the total number of issues (missing + wrong geometry + wrong class + forbidden) is 3 or more, otherwise "ok".

Write one JSON file per image:
{"gid": "<gid>", "verdict": "ok" | "fix", "n_missing": N, "n_geometry": N, "n_class": N, "n_forbidden": N,
 "notes": [{"type": "missing" | "geometry" | "class" | "forbidden", "index": <element index or null>, "cls": "<class>", "box": [x1, y1, x2, y2] or null, "note": "<short>"}]}
Be concrete and short. Do not run code; look at the images.
