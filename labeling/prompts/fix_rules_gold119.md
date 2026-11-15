You correct an existing GUI annotation. Read the labelling rules in label_rules_gold119.md (same folder as this file) and follow them exactly.

For each image you get: the screenshot, the current label JSON, and a reviewer's notes JSON (issues found). Produce the corrected, complete label JSON for that image:
- add every missing element (the reviewer's list is a starting point, not complete — look at the whole image again),
- fix boxes and classes the reviewer flagged when the rules agree with the reviewer,
- remove forbidden boxes,
- keep every other existing element unchanged.
Look-only: use Read to view files and Write to save the JSON; do not run code. Output format is exactly the one in the rules file (image, width, height, elements with cls, box, kind, name, name_source).
