# R5 — Four model families as readers of screenshot, tree, and hybrid observations (partial)

## Source and protocol

- **Experiment:** R5 asks whether other model families rank the same three observation types (screenshot only, our tree only, screenshot plus our tree) in the same order as Claude. Readers: GLM 5.3 Flash, DeepSeek V4.1 Flash, LongCat 2.0 (text-only input, so only the tree conditions apply), and Claude Haiku 5.5 run through the same shell as a calibration.
- **Date:** 2026-11-13.
- **Status: partial.** The design was 48 tasks, one run per model and condition. The run covers **27 tasks**: the first 24 of a stratified order (3 per app) plus the 3 remaining gnome-calendar tasks, whose oracle only works until 2026-11-14. The other 21 tasks were not run, so there are no confidence intervals; the tables report counts and paired win / loss / tie.
- **Reading rule:** differences under about 15 points are not read as findings.
- **Do not compare absolute numbers across models or across shells.** Each model is compared only with itself across conditions. Claude Haiku 5.5 through this shell versus Claude Haiku 5.5 through the `claude -p` shell of R1 measures the shell, not a model difference. Wall-clock time and tokens are comparable only within one model.
- **Shell:** `omp` 18.16.0 with provider `opencode-go`, print mode with JSON output and no saved session; each episode runs in a fresh neutral working directory that contains only the MCP configuration.
- **Models and thinking level:** `glm-5.3-flash` (low), `deepseek-v4.1-flash` (low), `longcat-2.0` (low), `claude-haiku-5-5` (low). Each is the lowest reasoning level above off / minimal that the shell lists. Haiku used 0 reasoning tokens.
- **Conditions:** as in R1 (`S_shot`, `T_ours`, `H_ours`; LongCat: `T_ours` and `T_atspi`). The system prompt is the R1 text verbatim. `S_shot` and `H_ours` received the coordinate sentence added in R4. Trees are the R1 `T_ours` / `H_ours` trees (not the cleaned R2 version), produced by the same resident perception service.
- **Tools:** the six R1 tools; their schemas were checked to be identical to R1's. 20-call limit and the same step archive.
- **Tasks and grading:** R1's frozen tasks and the oracle v1.1 (the task oracle reads the app's saved state after the app closes; no model or human judge). The order is the stratified order used in R4: each app's six tasks shuffled with seed 0, one task per app per block, block order shuffled, the conditions of a task adjacent with a rotating start.
- **Per-episode cap:** 10 minutes of wall-clock time (R1 used 15). A timeout counts as a failure and stays in the denominator. LongCat had 8 timeouts in `T_ours` and 2 in `T_atspi` in the 27-task scope.
- **Denominators:** the final tables have 0 invalid episodes and 0 harness errors, so every episode run is counted. Each cell has 24 (scope A) or 27 (scope B) tasks, one run per task.
- **Success:** oracle v1.1 passed.
- **Tool-call lockdown:** all four models passed the lockdown probe (same tests as R1); no model attempted a tool outside the six in the formal episodes.
- **Image input:** the OpenAI-compatible providers (GLM, DeepSeek, LongCat) cannot carry images inside a tool message, so the shell adds a user message with the image after the tool result. Claude Haiku receives the image inside the tool result. Images were 1280×720 in every request.
- **Shell defect and fix (affects Haiku most):** the shell sends all tool calls of one assistant message to the MCP server at once and the server executed them in arbitrary order. In the first pass, Haiku through this shell scored 42 / 33 / 46 % on the first 24 tasks, against 85 / 51 / 79 % in R1. The fix runs the calls one at a time in the written order (order gate). Episodes that contained a multi-call message in the first pass were rerun. The episodes that were not affected by the race are kept as they were. The rule for "affected" depends only on the transcript, not on success.
- **Sample size:** 24 or 27 tasks per model and condition.

## Results

**Table scope_a.** Scope A, first 24 tasks, success as count and percentage.

| Model (shell) | S_shot | T_ours | H_ours | T_atspi |
|---|---|---|---|---|
| GLM 5.3 Flash | 17/24 (71 %) | 16/24 (67 %) | 22/24 (92 %) | – |
| DeepSeek V4.1 Flash | 17/24 (71 %) | 20/24 (83 %) | 19/24 (79 %) | – |
| LongCat 2.0 (no image input) | – | 18/24 (75 %) | – | 15/24 (62 %) |
| Claude Haiku 5.5 (this shell, calibration) | 20/24 (83 %) | 14/24 (58 %) | 20/24 (83 %) | – |
| *Claude Haiku 5.5 (R1 `claude -p` shell), same 24 tasks, mean of 3 reps* | *85 %* | *51 %* | *79 %* | – |

**Table scope_b.** Scope B, 27 tasks (scope A plus 3 gnome-calendar tasks).

| Model (shell) | S_shot | T_ours | H_ours | T_atspi |
|---|---|---|---|---|
| GLM 5.3 Flash | 17/27 (63 %) | 18/27 (67 %) | 24/27 (89 %) | – |
| DeepSeek V4.1 Flash | 19/27 (70 %) | 22/27 (81 %) | 21/27 (78 %) | – |
| LongCat 2.0 (no image input) | – | 19/27 (70 %) | – | 15/27 (56 %) |
| Claude Haiku 5.5 (this shell) | 21/27 (78 %) | 15/27 (56 %) | 21/27 (78 %) | – |
| *Claude Haiku 5.5 (R1 shell), same 27 tasks* | *83 %* | *49 %* | *75 %* | – |

**Table calendar3.** The three extra gnome-calendar tasks (counts out of 3).

| Model (shell) | S_shot | T_ours | H_ours | T_atspi |
|---|---|---|---|---|
| GLM 5.3 Flash | 0/3 | 2/3 | 2/3 | – |
| DeepSeek V4.1 Flash | 2/3 | 2/3 | 2/3 | – |
| LongCat 2.0 | – | 1/3 (2 timeouts) | – | 0/3 |
| Claude Haiku 5.5 (this shell) | 1/3 | 1/3 | 1/3 | – |

Reading within each model (scope A, then scope B; paired over tasks, win / loss / tie):

- **Tree versus screenshot (`T_ours` vs `S_shot`):** DeepSeek 5 / 2 / 17, then 6 / 3 / 18. GLM 3 / 4 / 17, then 5 / 4 / 18. Haiku 0 / 6 / 18, then 0 / 6 / 21 (the same direction as R1).
- **Screenshot plus tree (`H_ours` vs `S_shot`):** GLM 7 / 2 / 15, then 9 / 2 / 16. For DeepSeek and Haiku the hybrid is no better than the best single source.
- **Text-only model:** LongCat does better with our tree than with the system accessibility tree: 6 / 3 / 15, then 7 / 3 / 17. `T_atspi` scores 0/3 on gnome-contacts and 0/6 on gnome-calendar.
- **Shell calibration:** Haiku through this shell differs from Haiku in R1 by −1 / +7 / +4 points on scope A and −5 / +6 / +3 on scope B (`S_shot` / `T_ours` / `H_ours`), once the order fix is applied. Before the fix the figures were 42 / 33 / 46 %.

## Shell fix and reruns

**Table rerun.** Outcomes of the rerun episodes, before and after the order fix. "ok → fail" is the count of episodes that succeeded before and failed after.

| Model | Episodes rerun | OK before | OK after | ok→ok | fail→ok | ok→fail | fail→fail |
|---|---|---|---|---|---|---|---|
| DeepSeek | 11 | 4 | 5 | 2 | 3 | 2 | 4 |
| LongCat | 3 | 2 | 1 | 1 | 0 | 1 | 1 |
| Claude Haiku 5.5 (all) | 72 | 29 | 54 | 28 | 26 | 1 | 17 |
| Claude Haiku 5.5, second rerun (episodes with a fallback in the first rerun) | 11 | 4 | 3 | – | – | – | – |

For DeepSeek and LongCat the fix changes the net count very little (+1 and −1), because these models rarely batch calls. For Haiku, which batches calls in almost every episode, the fix accounts for most of the change. For the DeepSeek and LongCat reruns, each rerun is a fresh draw; the original racing episodes are kept as evidence and are included in the analysis together with the reruns.

**Table calibration.** Claude Haiku 5.5 before and after the order fix (first 24 tasks), compared with the R1 shell.

| Condition | Haiku, this shell, racing (first pass) | Haiku, this shell, in order (after fix) | Haiku, R1 shell, same 24 tasks (3 reps) | In order − R1 |
|---|---|---|---|---|
| S_shot | 10/24 (42 %) | 20/24 (83 %) | 85 % | −1 pt |
| T_ours | 8/24 (33 %) | 14/24 (58 %) | 51 % | +7 pts |
| H_ours | 11/24 (46 %) | 20/24 (83 %) | 79 % | +4 pts |

With in-order execution, this shell reproduces R1's Haiku numbers and ranking (`S_shot` ≈ `H_ours` > `T_ours`) within a few points on these tasks. Without the fix the shell would have cost Haiku 25–45 points; that is a harness effect, not a property of the model or of the observation.

## Paired differences

**Table paired.** Paired differences by task: win / loss / tie, and mean difference in points in parentheses.

| Model | Pair | Scope A (24) | Scope B (27) |
|---|---|---|---|
| GLM | T_ours − S_shot | 3 / 4 / 17 (−4) | 5 / 4 / 18 (+4) |
| GLM | H_ours − S_shot | 7 / 2 / 15 (+21) | 9 / 2 / 16 (+26) |
| GLM | H_ours − T_ours | 7 / 1 / 16 (+25) | 8 / 2 / 17 (+22) |
| DeepSeek | T_ours − S_shot | 5 / 2 / 17 (+12) | 6 / 3 / 18 (+11) |
| DeepSeek | H_ours − S_shot | 2 / 0 / 22 (+8) | 3 / 1 / 23 (+7) |
| DeepSeek | H_ours − T_ours | 2 / 3 / 19 (−4) | 2 / 3 / 22 (−4) |
| LongCat | T_ours − T_atspi | 6 / 3 / 15 (+12) | 7 / 3 / 17 (+15) |
| Claude Haiku 5.5 | T_ours − S_shot | 0 / 6 / 18 (−25) | 0 / 6 / 21 (−22) |
| Claude Haiku 5.5 | H_ours − S_shot | 1 / 1 / 22 (0) | 1 / 1 / 25 (0) |
| Claude Haiku 5.5 | H_ours − T_ours | 6 / 0 / 18 (+25) | 6 / 0 / 21 (+22) |

## Steps, tokens and wall-clock time

**Table steps.** Means over valid episodes, scope A. Compare only within one model. Tokens are as reported by the provider through the shell; cost is the shell's own price estimate.

| Model | Condition | Steps | Model calls | Input / cache-read / output (reasoning) tokens | Cost $ | Wall mean / median s | Stop reasons |
|---|---|---|---|---|---|---|---|
| GLM | S_shot | 11.1 | 27.0* | 63,622 / 258,309 / 1,222 (365) | 0.018 | 55 / 26 | done 18, step_limit 5, fail 1 |
| GLM | T_ours | 12.0 | 15.9 | 31,441 / 301,059 / 1,384 (953) | 0.014 | 43 / 26 | done 15, step_limit 8, no_done 1 |
| GLM | H_ours | 10.4 | 11.6 | 126,928 / 92,797 / 707 (392) | 0.022 | 39 / 26 | done 22, step_limit 2 |
| DeepSeek | S_shot | 12.0 | 12.7 | 32,006 / 32,661 / 2,887 (2,107) | 0.007 | 71 / 44 | done 17, step_limit 6, no_done 1 |
| DeepSeek | T_ours | 11.9 | 13.1 | 27,225 / 212,453 / 4,463 (3,629) | 0.007 | 90 / 53 | done 21, step_limit 3 |
| DeepSeek | H_ours | 10.8 | 11.9 | 96,747 / 126,384 / 3,095 (2,348) | 0.017 | 89 / 50 | done 18, step_limit 4, fail 2 |
| LongCat | T_ours | 11.6 | 12.8 | 38,325 / 266,949 / 11,860 (11,148) | 0.027 | 263 / 200 | done 15, timeout 6, step_limit 3 |
| LongCat | T_atspi | 14.8 | 16.6 | 36,886 / 265,877 / 8,485 (7,680) | 0.023 | 195 / 123 | done 12, step_limit 8, timeout 2, fail 1 |
| Claude Haiku 5.5 | S_shot | 11.5 | 6.2 | 14 / 18,620 / 1,062 (0) | 0.003 | 18 / 17 | done 14, step_limit 6, no_done 3, fail 1 |
| Claude Haiku 5.5 | T_ours | 13.7 | 7.5 | 17 / 103,009 / 1,654 (0) | 0.005 | 26 / 23 | done 15, step_limit 8, fail 1 |
| Claude Haiku 5.5 | H_ours | 11.7 | 6.7 | 15 / 48,096 / 1,350 (0) | 0.011 | 24 / 18 | done 17, step_limit 5, no_done 2 |

\* GLM `S_shot` includes one episode that kept calling `done` after the step limit (369 model calls); the median for that row is 11. Claude Haiku makes fewer model calls than steps because it batches calls, as in R1. Its input is almost all cache reads.

## Click check (image conditions)

Method: each click is drawn on the screen the agent saw before it. A red mark is the executed pixel point; a blue mark is where a reading in 0–1000 normalized coordinates would land. The model's own words before the call are the caption. Twenty-four clicks per model, spread evenly over the `S_shot` and `H_ours` episodes.

**Table click.** Coordinate convention of the clicks.

| Model | Hit as pixels | Hit only under 0–1000 reading | Miss under both | Cannot judge (no stated target) |
|---|---|---|---|---|
| GLM | 16 | 0 | 3 | 5 |
| DeepSeek | 24 | 0 | 0 | 0 |
| Claude Haiku 5.5 | 19 | 0 | 3 | 2 |

None of the three mixes 0–1000 coordinates (the Gemini reader in R4 did). The Haiku sample comes from the racing first pass; click geometry does not depend on execution order. Of GLM's 8 non-hits, 3 missed under both readings and 5 could not be judged.

**Table h_list.** `H_ours` clicks whose coordinates come from the element list (click within 3 px of the centre of an element in the observation just before), scope A.

| Model | Clicks from the list |
|---|---|
| GLM | 116 / 150 (77 %) |
| DeepSeek | 128 / 158 (81 %) |
| Claude Haiku 5.5 (in-order runs) | 75 / 106 (71 %) |
