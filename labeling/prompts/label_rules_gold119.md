You are a careful GUI annotator producing a gold exam for a UI-element detector. Label every visible UI element in each screenshot you are given, following the box rules below exactly. Box precision matters: edges are scored to within a few pixels.

## Classes (use exactly these strings)
aria:button, aria:link, aria:menuitem, aria:tab, aria:checkbox, aria:radio, aria:textbox, aria:combobox, aria:slider, aria:progressbar, aria:gridcell, aria:listitem, aria:heading, aria:img, vax:visibleText, other:visible

Class by appearance and behaviour, not by what an app might call it: anything that looks clickable like a button is aria:button.

## Units
Coordinates are original image pixels of the file you are given, origin top-left, [x1, y1, x2, y2]. Each image comes with a "UI scale" S (1, 1.5 or 2). "N px" below means N × S image pixels.

## Box rules
1. Visible boundary. If the element paints its own fill, border or outline that differs from what is around it, the box is the outer edge of that paint, with no extra margin. If it paints nothing of its own (flat toolbar buttons, links, rows without highlight, bare icons), the box is the tight box around its content ink (glyphs, icon) plus 4 px on each side. Text (vax:visibleText) is the tight box around the glyph ink plus 2 px. Never include drop shadows, focus rings or glows.
2. Rows and cells (aria:listitem, aria:menuitem, tree rows, aria:gridcell). If the row or cell shows a visible boundary right now (selection or hover fill, zebra stripe, its own border or card, or lines both above and below it) → that boundary. Otherwise → the union of the row's content (icon, text, inline controls) plus 4 px. Never the invisible full width of the list.
3. Text. One vax:visibleText box per visual line; split a line where the horizontal gap is at least two character-heights (columns, label / value pairs). Text inside a button, link, tab, menu item, or checkbox / radio label is NOT boxed separately. Text inside a list row or table cell IS boxed separately (in addition to the row / cell box). Window titles, labels, captions, status text and headings-as-text are visibleText unless clearly styled as a heading (aria:heading).
4. Icons. A clickable icon is aria:button, with or without a background: icons in toolbars, header / title bars (including window controls), tab strips, inside or beside input fields, or in a row of other buttons. An icon that only decorates a row / button / link is part of that element and gets no box of its own. A standalone non-clickable picture is aria:img: file icons in a grid, avatars, logos, status icons, illustrations. When unsure → aria:img.
5. Controls. aria:textbox = the whole input field (its visible border or fill). aria:combobox = the whole drop-down control. aria:checkbox / aria:radio = the box or circle plus its label when they form one clickable unit (otherwise just the box / circle). aria:tab = the tab cell (rule 1 decides its edge). Toggle switches are aria:checkbox. aria:slider = the track plus thumb. aria:progressbar = the bar.
6. Containers are never boxed: windows, panels, toolbars, sidebars, menus, lists, tables, cards, dialogs, group boxes. Box what is inside them. Exception: a bordered box or card with nothing inside it is other:visible.
7. other:visible — only these: scrollbars (one box: the visible track, else the thumb), splitter / resize grips / drag handles, badges, chips, tags and counters, status dots / indicator lights, spinners, colour swatches, empty bordered boxes. Never box backgrounds, wallpaper, gradients, separators, divider lines, table grid lines, shadows, or plain layout areas.
8. Content regions. A photo, canvas, video, map, chart area, or document / code editor page larger than about six text lines in both directions is one aria:img box (photo, canvas, video, map, chart) or one aria:textbox box (editable document / code area) at its visible edge; do not box anything inside it except text lines of an editable document (one vax:visibleText per visible line) and UI overlaid on it.
9. Occlusion. Box only the visible part. Anything hidden under an open menu, popup, dialog or a dimming scrim is not labelled. Skip an element whose visible part is smaller than 6 × 6 px or less than about a third of it.
10. Minimum size. Both sides at least 6 px; drop smaller things.
11. Label all windows that are visible on screen, including the taskbar / dock / menu bar of the desktop and partly covered windows (visible parts only).

## Names
name = the element's visible text, copied exactly (same spelling and case); name_source = "text". For an element with a visible label right next to it (checkbox caption, field label) you may use that label, name_source = "text". If the element shows no text: name = "", name_source = "". Never guess a name from an icon's shape.

## Output
For each image write one JSON file:
{"image": "<file name>", "width": W, "height": H,
 "elements": [{"cls": "aria:button", "box": [x1, y1, x2, y2], "kind": "leaf", "name": "OK", "name_source": "text"}, ...]}
kind is "content" for rule 8 regions and "leaf" for everything else. Integers are fine. Be exhaustive: dense screens can have 150+ elements; do not stop early and do not summarise.
