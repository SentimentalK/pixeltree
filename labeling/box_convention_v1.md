# Box Convention v1

Goal: every source (DOM, human, AT-SPI, Figma, model labels) draws **one geometry**, so the detector
learns one thing. The reference is **what is visible on screen now**, not the layout box, the
toolkit allocation, the design layer, or a loose hand-drawn rectangle.

Evidence: `docs/data/box_convention_audit.md` (4 sources × 30 images). It shows that GroundCUA's human
boxes are *looser* than the ink (median 6.2 logical px), so v1 does **not** copy GroundCUA geometry; it
copies GroundCUA's *choice of what to box* (content, not invisible row width; no containers) and fixes the
margin.

Units: logical px = image px / `scale`. "Visible" uses the audit measure: background = per-channel median
of the 1–3 px ring outside the candidate box; a pixel is visible when its max channel difference from
that background is > 24. The class taxonomy (16 classes, ULF v1) is unchanged.

Examples: every rule has a sheet `data/convention_examples/C<n>.png`
(git-ignored; red = current box, green = v1 box). Paths are listed in §Examples.

## Rules

**C1 Visible boundary.** An element's box is the tight box of what is painted for it now:
- if it paints its own fill, border or outline that differs from its surroundings → the edge of that paint, no pad;
- otherwise (flat buttons, links, rows without highlight, icons) → the union of its content ink (glyphs, icon)
  **+ 4 logical px** per side, never larger than the element's own layout box;
- text (cls 14) → glyph ink **+ 2 logical px** per side.
Shadows, focus rings, hover glows and drop-shadows are not part of the box.
Pos: a filled button → its fill edge. Neg: a 36 × 36 layout box around a 16 px toolbar glyph → 24 × 24.

**C2 Rows and cells** (listitem, menuitem, tree row, table row used as a list row, gridcell). If the row or
cell has a visible boundary now (selection / hover fill, zebra stripe, own border or card, or rules both above
and below it) → that boundary (C1, no pad). Otherwise → union of the row's content (icon, text, inline
controls) + 4 px. **Never the invisible full width.**
Pos: a selected sidebar row → highlight edge. Neg: an unhighlighted `<li>` spanning a 280 px panel with a
40 px label → label + 4 px.

**C3 Text.** One box per visual line. A line splits into separate boxes at a horizontal gap ≥ 2 em, where em = the font size of that text (DOM: computed `font-size` × scale; pixel-only sources and model labellers: the height of the line's glyph box, ascender to descender)
(columns, label / value pairs). Text inside a button, link, tab, menuitem or checkbox / radio label is not
boxed separately; text inside a listitem or gridcell **is** (cls 14, as in label_rules_v3).

**C4 Icons.** A clickable icon is `aria:button` (cls 0), with or without a background: icons in toolbars,
header / title bars, tab strips, input adornments, or in a row of other buttons. An icon that only decorates
a row / button / link is part of that element (no own box). A standalone non-clickable picture is `aria:img`
(cls 13): file icons in a grid, avatars, logos, status icons, illustrations. When unsure → img.

**C5 Clickable div / span (DOM).** A node with no ARIA / native role is *clickable* when its computed
cursor is `pointer` and its parent's is not (outermost pointer node). Then:
- own visible boundary (bg differs from the nearest painted ancestor by > 24 on the max channel, or a
  border ≥ 1 px whose colour differs by > 24, or a background image) **and** both sides ≥ 16 logical px
  **and** width ≤ 480, height ≤ 120 logical px (all limits in logical px = image px / scale, so a 3× phone viewport uses 1,440 × 360 image px) → `aria:button`;
- no boundary, content is text only → `aria:link`;
- no boundary, content is a single icon / svg → `aria:button` (C4);
- larger than the limits (cards, whole rows) → not reclassified (stays as it was).
Its descendants are suppressed like any button (ULF §4 rule 1).

**C6 Containers.** Detector targets are leaves and content regions only. Any painted region that contains
≥ 1 other target (panel, card, toolbar, group box, dialog, list) is a container: written as a tree parent
(`kind=container`), never exported to the detector. Of nested containers with IoU ≥ 0.9, keep the innermost.
A painted region with no target inside (empty bordered box / empty card) is a class-15 leaf.

**C7 Class 15 ("other visible element").** Whitelist — exported as leaves: scrollbar (one box: the visible
track, else the thumb); splitter / resize grip / drag handle; badge, chip, tag, counter (earlier decision ①);
status dot / indicator light; spinner / loading indicator; colour swatch; empty bordered box (C6).
Blacklist — never boxed: layout div / span with no own paint; transparent containers; backgrounds,
wallpaper and page gradients (≥ 60 % of the window, ULF §4 rule 6); separators, dividers and grid lines
(`kind=separator`, not exported — GroundCUA does not box them either); shadows, focus rings; containers (C6);
text (→ cls 14).

**C8 Occlusion and clipping.** Box only the visible part, clipped to the window region and to scrolling /
clipping ancestors. Anything under a modal scrim, an open menu or a dialog is not a target. A partly covered
element is kept when its visible part is ≥ 6 × 6 logical px and ≥ 30 % of its area. Foreground window only
(ULF v1).

**C9 Minimum size.** After C1–C8, both sides ≥ 6 logical px; smaller boxes are dropped. Exception: aria:slider and aria:progressbar (thin by nature) need long side ≥ 6 and short side ≥ 2 logical px. Replaces the
0.5 em gate and the avatar-dot rule of ULF §4.

**C10 Content regions** (unchanged from ULF §4 rule 5 and decision ②): a photo, canvas, video, map or
document canvas with both sides ≥ 6 em is one `content` box at its visible edge (C1, no pad); nothing
inside it is boxed.

**C11 Class by appearance, not by source category.** An element that looks and behaves like a button (C4 / C5)
is cls 0 whatever the source calls it. GroundCUA's `None` / `Others` / `Navigation` categories hold many
buttons and nav rows (audit §5); their remapping is a separate step (not in v1 tooling).

**C12 Conformance.** A box conforms when each side is within ± 2 logical px of the v1 box. Detector exams
keep IoU 0.5 matching; ± 2 px is for label QA only.

## Differences from the earlier label format (ULF v1) and transition

| Topic | ULF v1 | v1 | Transition |
|---|---|---|---|
| Rows (listitem / menuitem) | DOM layout box, often full width | C2: visible boundary or content + 4 | `--convention v1` only |
| Flat buttons, links, icons | layout box incl. padding | C1: ink + 4 within layout box | `--convention v1` only |
| Small things gate | both sides < 0.5 em dropped; avatar-dot rule | C9: < 6 logical px dropped | `--convention v1` only |
| Clickable div / span | class 15 if painted, else dropped | C5: button / link | `--convention v1` only |
| Chips / badges (①), big media (②), svg root & grid lines (③), names (④) | — | unchanged | none |
| Containers, separators | not exported | unchanged (C6, C7) | none |
| GroundCUA geometry | taken as is | looser than v1 by ~4–8 px | **next step:** a shrink-to-ink pass — shrink only, never grow: inside each leaf box find the visible-ink bbox (audit measure) and set the box to it + 4 px (+ 2 px for cls 14), intersected with the original; containers, content boxes, ring-noisy and ink-less boxes unchanged. Estimate on 300 sampled GroundCUA leaf boxes (seed 119, audit data): 75 % change, mean shrink 6.1 px per side among changed boxes (median 3.4), median area loss 26 %; 11 % skipped as ring-noisy / empty. |
| GroundCUA class 15 | category mapping (§8) | C11 conflict | separate remap step |

Records produced under v1 carry `"convention": "v1"`; records without the field are ULF v1.
Do not mix the two in one training run. Default exports are unchanged.
