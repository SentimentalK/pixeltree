# Element tree format

`pixeltree.perceive` turns one screenshot into a flat list of visible UI elements. This page describes the text an
agent reads, the JSON written by the command line, and the compact formats in `pixeltree.formats`.

```
python -m pixeltree.perceive examples/screenshots/gitg.png          # text to stdout
python -m pixeltree.perceive SHOT.png --text OUT.txt --json OUT.json
```

(`examples/screenshots/gitg.png` is a screenshot of the gitg Git client on a GNOME desktop; `gitg.tree.txt` and
`gitg.tree.json` next to it are the resulting tree.)

## Text format

```
screen 1920x1080, 85 elements
aria:button [e1] "" @(12,10,34,33) c=(29,26)
vax:visibleText [e2] "demo-repo (~/Projects)" @(883,12,154,15) c=(960,19)
aria:button [e3] "Q" @(1633,10,34,33) c=(1650,26)
```

The first line is the header: `screen <width>x<height>, <n> elements`. Then one line per element:

```
<role> [e<k>] "<name>" @(x,y,w,h) c=(cx,cy)
```

| field | meaning |
|---|---|
| `<role>` | The detector class of the element: `aria:button`, `aria:link`, `aria:menuitem`, `aria:tab`, `aria:checkbox`, `aria:radio`, `aria:textbox`, `aria:combobox`, `aria:slider`, `aria:progressbar`, `aria:gridcell`, `aria:listitem`, `aria:heading`, `aria:img`, `vax:visibleText` (plain text), or `other:visible` (any other visible element). |
| `[e<k>]` | The element id. Ids are `e1 … eN` in reading order and are only stable inside one tree: a new screenshot is numbered again. |
| `"<name>"` | The text OCR read from the element, see below. `""` when nothing was read. Whitespace is collapsed to single spaces and a double quote inside the name is written `\"`. |
| `@(x,y,w,h)` | The bounding box: left, top, width, height. |
| `c=(cx,cy)` | The box centre, `int(x + w/2)` and `int(y + h/2)`: the point to click. |

**Coordinates** are integer pixels of the screenshot, origin at its top-left corner, x to the right and y down. No
scaling is applied: a click at `c=(cx,cy)` lands on that pixel of the same screen.

**Reading order.** Elements are sorted into rows by centre y: a new row starts when the centre y differs by more than
half the median element height from the first element of the current row. Inside a row, elements run left to right.
Elements are not nested: containers and their contents are all listed (a list item and the text inside it are two
lines).

**Length.** At most 400 element lines are written. When there are more, the last line is `... <n> more elements`.

### Names come from OCR only

A name is what the OCR model read inside the element's box, nothing else. The tree never guesses what an icon means:
an icon without readable text has the name `""`, and OCR on a glyph sometimes returns a stray character (`"="`,
`"0"`, `"业"` on toolbar icons are typical). Treat a name as "text seen on screen", not as an accessibility label.
Three details:

* Text-bearing roles (buttons, links, list items, text boxes, text, ...) are read from their box. For `aria:img`
  elements the OCR reads a band over the bottom text line of the box, because desktop icons carry a caption under the
  glyph; reads with fewer than two letters or digits are dropped.
* OCR reads with a confidence below 0.5 are dropped.
* For `aria:textbox` elements the box is also read line by line. The in-box reading-order text is used as the name when
  the whole-box read gave none, and replaces it when it has several lines.

## JSON format

`--json` (and `pixeltree.perceive.tree.to_json`) writes:

```json
{"source": "ours", "image_size": [1920, 1080],
 "elements": [{"id": "e1", "role": "aria:button", "name": "", "box": [12, 10, 34, 33],
               "center": [29, 26], "conf": 0.8848}],
 "timings": {"detect_s": 0.0225, "ocr_s": 0.3118, "tree_s": 0.0043, "decode_s": 0.0208,
             "load_s": 0.0, "total_s": 0.3962, "model_s": 0.3752}}
```

| field | meaning |
|---|---|
| `source` | `"ours"`: the screenshot-only perception of this package. |
| `image_size` | `[width, height]` of the screenshot in pixels. |
| `elements[].id` | `e1 …`, as in the text. |
| `elements[].role` | Detector class, as in the text. |
| `elements[].name` | OCR text, `""` if none. Not whitespace-collapsed in the JSON. |
| `elements[].box` | `[x, y, w, h]`, integer pixels. |
| `elements[].center` | `[cx, cy]`, integer pixels. |
| `elements[].conf` | Detector confidence, 4 decimals (`null` when unknown). Only elements with confidence >= 0.25 are kept. |
| `timings` | Seconds per stage: `detect_s` (leaf detector), `ocr_s` (name and text-box reads), `tree_s`, `decode_s`, `model_s`, `total_s`; `load_s` is the one-off model load of the first call and is not part of `total_s`. |

## Compact format and change encoding (`pixeltree.formats`)

`pixeltree.formats` works on the tree dict above and is plain Python (no model needed). It is used by the benchmark
variants that shorten what the agent reads; the default path does not use it.

**F1, compact lines**: short role, name (omitted when empty), centre only. Boxes and ids are dropped.

```
screen 1920x1080, 4 elements
btn 29,26
text "demo-repo (~/Projects)" 960,19
btn "Q" 1650,26
btn "=" 1690,26
```

`formats.f1(tree)` writes it. Short roles: `btn link menuitem tab check radio input combo cell item heading img text other`;
a role without a short form (for example `aria:slider`) is written in full.

**F3, changes between observations**: `formats.Delta3` is fed the element list of every observation of an episode in
order and returns the text to show. The first text is full, with a persistent integer id in front of each line. Later
texts list only what changed, or say `no change`. A full text is sent again when more than half of the elements
changed.

```
screen 1920x1080, 4 elements (full)          <- first observation
1 btn 29,26
2 text "demo-repo (~/Projects)" 960,19
...
changes: +1 -0 ~1, 5 elements                <- second observation: one added, one renamed
+ 5 btn "OK" 1030,515
~ 2 "Renamed" 960,19
```

`+ <id> ...` is an added element, `- <id>` a removed one, `~ <id> "<name>" <cx>,<cy>` a changed one (new name and
centre). `formats.Decoder3` rebuilds the element state from these texts, which is how the encoding is checked to be
lossless.

## Name cleaning (experimental, off by default)

`pixeltree.formats.clean` (`formats.clean`, `formats.f2`) rewrites names before display: it removes odd-script
characters, blanks the names of small icon-sized elements, blanks non-text names that have no letter or digit, merges
duplicates and blanks the name of an element that contains several text elements. The idea was that an empty name beats a
wrong one. **Known defect:** the pure-symbol rule blanks the name of the title-bar close button `×`, which OCR reads
correctly; agents shown a nameless button then click it as if it were a menu and close the application. Nothing in
the default path (the command line, `to_text`) calls the cleaning; use it only to reproduce the experiments that did, and
see `PAPER.md` for the results.

```
btn "×" 1893,27      <- formats.f1 of the raw tree
btn 1893,27          <- formats.f2 (cleaned): the close button lost its name
```

## Reproducibility

The trees archived by the experiments were produced on a GPU (fp16 detector and CUDA fp16 OCR). The default of
this package is the CPU (fp32), which differs slightly: on 30 archived steps (8 applications), a median of 93 % of
the elements matched an archived element (same role, IoU above 0.5) with an identical name, the box coordinates
differed by 0 px at the median and by at most 2 px at the 95th percentile, and 23 of the 30 trees had the same
number of elements. Because ids follow reading order, one extra or missing element renumbers every later id, so a
CPU tree is rarely line-for-line equal to an archived one. On a GPU (`--device 0`, needs `onnxruntime-gpu`) the same
30 steps are reproduced exactly; `tests/test_perceive_equivalence.py` checks both.
