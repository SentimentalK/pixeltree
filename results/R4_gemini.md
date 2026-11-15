# R4 — Gemini reader through the agy command-line wrapper (incomplete)

## Source and protocol

- **Experiment:** R4 asks whether a non-Claude reader ranks the same observations in the same order as Claude. The reader is Gemini 3.8 Flash through the agy command-line agent (agy 1.5.8, model `gemini-3.8-flash-medium`).
- **Date:** 2026-11-13.
- **Status: the run did not finish.** The agent service stopped with a usage limit after 4 tasks. The formal run has **1 complete valid task triplet out of the planned 48 tasks**. Two more triplets are incomplete because their screenshot episode was invalid, and one task has only error rows. **The numbers below are therefore direction only; n is 1 in the main table and 5 tasks (7 episodes for screenshot-only) in the sensitivity table.**
- **Conditions** (same definitions as R1): `S_shot` (1280×720 screenshot), `T_ours` (element list from the detector plus OCR, screen pixels), `H_ours` (screenshot plus the same list in screenshot coordinates).
- **Tasks and grading:** R1's 48 frozen tasks and the oracle v1.1 (the task oracle reads the app's saved state after the app is closed; no judge). Each app's six tasks are shuffled with seed 0; the three conditions of a task run adjacent with a rotating start.
- **Agent wrapper:** agy wraps its own base prompt (about 3.3k tokens, which cannot be removed) around the R1 system prompt. For `S_shot` and `H_ours` one sentence was added at the end of the system prompt, after the pilot: "Coordinates are absolute pixels of the 1280x720 screenshot (x 0–1279, y 0–719), not normalized 0–1000 values." `T_ours` is unchanged. The six R1 tools are provided through an MCP server with the same definitions and the same 20-call limit.
- **Protocol constraints of the agy wrapper (not properties of the model alone):**
  1. **Images go through a file.** agy stores MCP images above a small size as files and gives the model only one text line with the file path. Images of 768×432 and larger were not shown inline; 240×120 was. The screenshot conditions therefore need agy's `read_file` tool, which is limited to this conversation's own screenshots. `read_file` does not count toward the 20-call limit. Without the file tool, the model described a screen that did not exist.
  2. **Image size seen by the model:** the file is 1280×720. Whether the wrapper or the API rescales it before the model sees it could not be determined.
  3. agy's base prompt and tool-calling wrapper are always present, so per-episode token and time figures are comparable only within the Gemini conditions, not with Claude.
- **Lockdown:** the agent has only the six tools, plus agy's resource and task listing tools that are denied by a pre-tool-use gate. Any call outside the allowed set makes the episode invalid, whether or not it was blocked. Three such calls occurred in real episodes, all in `S_shot` and all denied; those episodes are invalid and are not in the main table.
- **Coordinate check:** Gemini mixes two conventions, absolute pixels and 0–1000 normalized values. In a pilot of 20 screenshot-only clicks, 8 hit as pixels, 3 hit only under the 0–1000 reading, and 9 missed under both. The added sentence did not remove the mixing (pilot with the sentence: 11 pixel hits, 4 hits only under the 0–1000 reading, 7 misses out of 22 clicks). The tree conditions use tree coordinates and all 16 pilot clicks hit.
- **Sample size:** formal run 12 task-condition keys (7 valid, 2 invalid, 3 error rows). Sensitivity table pools 5 tasks with 7 screenshot-only episodes, 5 `T_ours` episodes and 5 `H_ours` episodes.
- **Haiku column:** R1 results for the same tasks (3 repetitions each), shown for orientation only. They were not run with the agy wrapper.

## Results

**Table main.** Formal run, valid complete triplet only (1 task). This is **n = 1**: no intervals, and the table is not evidence for a ranking.

| Condition | Success | R1 Haiku, same task (3 reps) | Steps | Model calls | Image views | Input / cache-read / output (thinking) tokens | Wall s |
|---|---|---|---|---|---|---|---|
| S_shot | 0 / 1 | 3 / 3 | 19 | 36 | 16 | 114,617 / 819,223 / 32,697 (30,529) | 375.0 |
| T_ours | 1 / 1 | 0 / 3 | 6 | 7 | 0 | 23,410 / 65,977 / 1,280 (957) | 40.5 |
| H_ours | 1 / 1 | 3 / 3 | 8 | 9 | 0 | 29,946 / 110,979 / 1,272 (858) | 37.1 |

Paired on 1 task (win / loss / tie): H_ours vs S_shot 1 / 0 / 0; T_ours vs S_shot 1 / 0 / 0; H_ours vs T_ours 0 / 0 / 1.

**Table direction.** Sensitivity view, every graded Gemini episode on 5 tasks (formal run including its invalid episodes, plus a pilot without the coordinate sentence and a pilot rerun with it). **n is 5 tasks and 1 repetition per task for Gemini; direction only.** The R1 Haiku column covers the same 5 tasks with 3 repetitions each.

| Condition | Gemini success | Of which invalid | R1 Haiku, same 5 tasks | Image views per episode | Successful episodes with zero image views |
|---|---|---|---|---|---|
| S_shot | 3 / 7 | 3 | 93 % (14 / 15) | 16, 13, 8, 13, 17, 12, 16 | 0 / 3 |
| T_ours | 5 / 5 | 0 | 27 % (4 / 15) | 0 × 5 | 5 / 5 |
| H_ours | 5 / 5 | 0 | 67 % (10 / 15) | 0, 0, 0, 0, 2 | 4 / 5 |

On these 5 tasks the order is reversed compared with Haiku: for Gemini the tree-based conditions beat the screenshot-only condition, while for Haiku the screenshot is clearly best. Gemini's `H_ours` episodes almost never opened the screenshot (2 views in 5 episodes), so the result is close to `T_ours` rather than to "screenshot plus tree". Gemini's screenshot episodes opened a screenshot after nearly every action, so `S_shot` is affected by the image-file constraint above, and the sentence about coordinates did not remove the 0–1000 mixing.

What this does not show: anything statistical (5 tasks, 1 repetition), or whether Gemini reads trees better than Claude, as opposed to the image-file path and coordinate mixing making the screenshot condition weak.
