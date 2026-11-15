# R2 — Offline token accounting for tree text formats

## Source and protocol

- **Experiment:** R2, an offline measurement. The same R1 `T_ours` trees are re-serialized in four text formats, and the observation tokens per step are compared with one screenshot. No model was called, no API was used, no application was started; the cost is $0.
- **Date:** 2026-11-12.
- **Data:** the 144 `T_ours` episodes of R1, with 1,826 observation steps that have a stored tree (`done` steps have no tree and are excluded).
- **Token conversion:** characters × 0.5890 tokens per character. This coefficient is the least-squares fit of R1 `T_ours` context growth on tree characters. A 1280×720 screenshot is counted as 1,153.7 tokens (fit for the Haiku screenshot condition of R1). Characters are reported as well. The coefficient was fitted on the verbose format F0; the compact formats have more digits, commas and short words per character, so their real tokens per character may be higher (see limitations).
- **Formats:**
  - **F0 (current):** the R1 serialization, `role [id] "name" @(x,y,w,h) c=(cx,cy)`.
  - **F1 (compact rows):** `<short role> "<name>" <cx>,<cy>`, with the name quotes dropped when the name is empty. Only the center point is kept, not the box, because the agent acts on point coordinates. Element IDs, boxes and confidence values are dropped.
  - **F2 (F1 plus cleaning):** F1 applied to the cleaned elements. Cleaning rules, in order: (1) names of non-text roles with max(width, height) < 32 px are cleared; names with non-Latin symbolic characters are stripped, and cleared if nothing remains; non-text-role names without any letter or digit are cleared. (2) Near-duplicates (normalized name similarity ≥ 0.6 with box IoU ≥ 0.7, or one box inside the other with overlap fraction ≥ 0.8, or two unnamed boxes with IoU ≥ 0.7) are merged, keeping the higher-priority role, then the larger box, then the higher confidence. (3) A container element that holds two or more named text elements has its own name cleared.
  - **F3 (F2 with changes only):** the first step is a full listing with persistent IDs; later steps list only `+` (added), `-` (removed) and `~` (changed name or moved center) elements, or `no change`. If more than half of the elements changed, the step falls back to a full listing. Matching across steps: identical role, name and center; or same role and name with center moved ≤ 80 px; or same role with box IoU ≥ 0.3 and a changed name.
- **Calibration:** thresholds were chosen on 175 frames from training-app screens that were not in the exam, using the stated rules. Eight exam apps are excluded from calibration. The rules and thresholds were committed before the measurement was run on the R1 data. One change to the encoding of out-of-table roles was made after the first measurement, and the thresholds and cleaning rules were not changed.
- **Sample size:** 144 episodes, 1,826 steps, 8 apps. Per-episode averages are the average over the 144 episodes of each episode's per-step mean; "pooled" is the average over all 1,826 steps.
- **Limitations:** (1) token counts use the F0 fit, see above; the F3 mean of 460 characters per step would need more than 1.30 tokens per character to exceed 600, while F2 would exceed 600 at 0.595 tokens per character. (2) "no change" steps depend on R1's habit of calling `observe` after each action; the sensitivity row below removes those steps. (3) Only tokens were measured here; agent success with F2 and F3 was measured in R3.

## Results

**Table main.** Observation tokens per step, all 144 episodes. "Episode mean" is the per-episode mean first, then averaged over episodes (this is the column used for the threshold).

| Format | Tokens / step (pooled) | Tokens / step from step 2 | **Episode mean tokens / step** | Total observation tokens per episode | Characters / step |
|---|---|---|---|---|---|
| F0 current | 2,156 | 2,182 | **2,122** | 27,340 | 3,661 |
| F1 compact rows | 823 | 835 | **818** | 10,435 | 1,397 |
| F2 = F1 + cleaning | 604 | 612 | **594** | 7,655 | 1,025 |
| F3 = F2 + changes only | 239 | 210 | **271** | 3,036 | 406 |
| Screenshot (reference) | 1,154 | 1,154 | 1,154 | 14,630 (12.7 steps × 1,154) | — |

Sensitivity: removing the steps that were `observe` calls directly after an action (the "no change" steps) gives an F3 episode mean of **386 tokens / step**. Using only observations returned by actions (click, key, type, scroll; 1,171 steps), F3 pooled is **290 tokens / step**.

**Table by_app.** Per app, each cell is pooled / from step 2 / episode mean / total per episode (tokens).

| App | Episodes | Observation steps | F0 | F1 | F2 | F3 |
|---|---|---|---|---|---|---|
| drawing | 18 | 238 | 1483 / 1509 / 1545 / 19605 | 524 / 535 / 554 / 6923 | 446 / 455 / 466 / 5900 | 167 / 148 / 190 / 2203 |
| gitg | 18 | 150 | 3059 / 3017 / 3206 / 25496 | 1339 / 1317 / 1414 / 11160 | 879 / 869 / 913 / 7328 | 397 / 304 / 451 / 3305 |
| gnome-calendar | 18 | 256 | 3446 / 3469 / 3234 / 49012 | 1159 / 1174 / 1074 / 16480 | 921 / 925 / 875 / 13097 | 280 / 223 / 391 / 3984 |
| gnome-contacts | 18 | 186 | 946 / 1008 / 900 / 9775 | 390 / 416 / 371 / 4030 | 262 / 278 / 253 / 2711 | 172 / 176 / 164 / 1779 |
| keepassxc | 18 | 237 | 2292 / 2355 / 2137 / 30178 | 941 / 973 / 856 / 12385 | 659 / 677 / 619 / 8678 | 249 / 227 / 265 / 3273 |
| lutris | 18 | 204 | 2233 / 2267 / 2192 / 25313 | 899 / 913 / 882 / 10185 | 582 / 593 / 572 / 6594 | 261 / 236 / 262 / 2958 |
| obsidian | 18 | 262 | 1832 / 1836 / 1828 / 26671 | 656 / 658 / 654 / 9546 | 466 / 469 / 466 / 6780 | 185 / 162 / 194 / 2698 |
| okular | 18 | 293 | 2007 / 2034 / 1932 / 32672 | 785 / 801 / 740 / 12774 | 623 / 636 / 592 / 10148 | 251 / 234 / 250 / 4085 |

**Table f3_behaviour.** Behavior of F3 from step 2 onward (1,682 steps).

- Steps that fell back to a full listing: 358 (21.3 %).
- Steps with `no change`: 532 (31.6 %). The rest are incremental updates.
- Elements per step, before → after cleaning: 62.5 → 52.0 (median 57 → 47).
- Average cleaning actions per step: icon-size names cleared 10.9; duplicates removed 10.6; out-of-set characters stripped 2.0; symbol-only names cleared 0.7; container names cleared 0.5.

| App | F3 full-listing fallback (from step 2) | `no change` | Elements before → after cleaning |
|---|---|---|---|
| drawing | 10 % | 44 % | 45.7 → 42.7 |
| gitg | 23 % | 44 % | 79.1 → 63.2 |
| gnome-calendar | 12 % | 18 % | 102.5 → 88.5 |
| gnome-contacts | 45 % | 24 % | 26.1 → 18.5 |
| keepassxc | 22 % | 27 % | 64.8 → 54.5 |
| lutris | 23 % | 39 % | 62.7 → 41.6 |
| obsidian | 17 % | 34 % | 56.9 → 47.0 |
| okular | 26 % | 28 % | 59.1 → 52.8 |

**Table guard_lossless.** Guardrail 1: F3 is lossless. At every step, the element multiset decoded from the F3 text (role, name, center) was compared with the F2 full listing of the same step.

| Quantity | Value |
|---|---|
| Steps where F3 decoding differs from F2 | 0 / 1,826 |

**Table guard_click.** Guardrail 2: cleaning does not delete useful elements. Only the 82 episodes that succeeded in R1 `T_ours` are used. Each click is checked against the last observation the agent had received before that click.

| Quantity | Value |
|---|---|
| Clicks with a reference tree | 336 |
| Clicks inside an element box before cleaning | 329 |
| Clicks still inside a kept element box after cleaning | 329 (100.0 %) |
| Clicked element: name kept | 225 |
| Clicked element: name cleared | 42 |
| Clicked element: removed as duplicate (a same-name containing element was kept, so the click stayed inside a box) | 62 |

**Table cleared_names.** The 10 most frequent cleared names among the 42 clicks on cleared-name elements (40 distinct episode-name-role combinations).

| # | OCR name | Role | Rule | Clicks |
|---|---|---|---|---|
| 1 | `+` | button | icon size | 11 |
| 2 | `目` | button | out-of-set character | 10 |
| 3 | `+` | button | symbol only | 6 |
| 4 | `三` | button | icon size | 5 |
| 5 | `ab` | button | icon size | 3 |
| 6 | `冈` | button | out-of-set character | 2 |
| 7 | `Old Router admin11/11/26 4:41 P...` | listitem | container name | 2 |
| 8 | `0` | button | icon size | 1 |
| 9 | `品` | button | out-of-set character | 1 |
| 10 | `●` | checkbox | out-of-set character | 1 |

Clearing `+` loses a correctly read label (a new-item button) and leaves the agent only `btn x,y`; this is the accepted cost of preferring an empty name to a wrong one. Clearing the CJK-character names corrects icons that were read as CJK characters. By app, the cleared-name clicks were: gnome-contacts 16, lutris 12, drawing 11, keepassxc 3, others 0.

## Limitations

- The per-character coefficient was fitted on verbose F0 text. Real tokens per character for F1–F3 were not measured here; see the threshold note above.
- Guardrail 2 shows that the click point stays inside a kept box; it does not show that the agent can still tell what the element is (the `+` case).
- Calibration frames were used to choose thresholds; the tree on those frames was built by the same detector arm that is evaluated in R1, so duplicate and matching thresholds were chosen on cleaner boxes than unseen apps produce. OCR was not trained on those frames, so the name-based thresholds (icon size, out-of-set characters, symbol-only names, containers) are fair.
- Density: R1 trees have 11–96 elements per screen (mean 62.5 before cleaning), which is sparse. Dense screens may fall back to full listings more often.
