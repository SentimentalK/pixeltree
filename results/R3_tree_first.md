# R3 — Tree-first agent with hover and on-demand look, against screenshot-only agents

## Source and protocol

- **Experiment:** R3. Tests whether a cleaned, change-only tree (condition `X1`, and `X2` which adds hover and an on-demand `look` that returns the screenshot) lets the agent succeed about as often as a screenshot-only agent on the same batch, while being cheaper or faster. The pass rule is set before the run (see below).
- **Date:** 2026-11-12 (run) and 2026-11-13 (analysis).
- **Agent:** Claude Haiku 5.5 via `claude -p` in every condition except `X1_sonnet` (Claude Sonnet 5.5). Each episode uses the same six-tool MCP server as R1 (observe, click, type, key, scroll, done), plus `hover` and `look` in the X2 conditions. Built-in tools are locked down as in R1.
- **Tasks and oracles:** the 48 frozen tasks of R1 and the oracle v1.1 (programmatic checks of the app's saved state, no LLM judge). The runner refuses to start when the frozen task files differ from the R1 freeze.
- **Conditions:**

**Table conditions.** Conditions and what the agent sees.

| Condition | What the agent sees | Coordinates | Tools | First view |
|---|---|---|---|---|
| S_shot | Same as R1: 1280×720 screenshot and one line of instructions | Screenshot pixels, × 1.5 | observe, click, type, key, scroll, done | calls observe |
| X1 | Cleaned F2 list from R2, full list at each step (for example `btn "Save" 1710,26`) | Screen pixels | the six tools | calls observe |
| X2 | F3 from R2: observe returns a full list with IDs; after actions and hover only changes are sent (`+ id …`, `- id`, `~ id …`, or `no change`; full list if changes exceed 50 %) | 1280×720 view (list center = screen / 1.5; same frame as look) | six tools + `hover(x,y)` + `look()` | calls observe |
| X1_sonnet | Same as X1, Claude Sonnet 5.5, one repetition per task | Screen pixels | six tools | calls observe |
| S_shot_lean | Same as S_shot | Same as S_shot | five tools (no observe) | first screenshot in the task message |
| X2_lean | Same as X2 | Same as X2 | no observe, no hover, no look | first full list in the task message |

- **Lean conditions:** the initial observation is given in the first user message (screenshot as an image block, list as text) and the `observe` tool is removed. The rationale: in R1's screenshot runs, 573 of 1,694 calls were `observe`, of which 144 were first views and 429 followed an action directly.
- **hover:** moves the pointer to the point without clicking, waits 1.2 s, and returns the list change. **look:** returns the screenshot with the same instructions as S_shot without changing the incremental state. Both count as one step.
- **Perception service:** the detector and OCR run in one resident service shared by all episodes, with the same tree-building call and device defaults as R1. The shared service was chosen because the GPU memory allowed two copies and not three.
- **Pass rule (set before the first episode):** success of X2 must be at least −5 points against S_shot, cost must be lower, and wall-clock time must not be slower.
- **Protocol freeze:** condition definitions, the pre-registration, and the shared-service change were committed before the first formal episode. Regression tests confirm that the seven R1 conditions have byte-identical system prompts, model settings, command lines, MCP configuration, tool lists, and observation text.
- **Interleaving:** tasks are shuffled with seed 0; within each (task, repetition) all conditions run adjacent, with the starting condition rotated. The first pass covered repetition 0 of all six conditions; the second pass covered repetitions 1–2 of the five Haiku conditions. The 768 episodes ran in one session.
- **Rate and intervals:** success is the mean over tasks of each task's mean over 3 repetitions (`X1_sonnet`: 1 repetition). Intervals are task bootstraps, 95 %, 2,000 resamples, seed 0. Paired differences are condition minus the same-batch S_shot, paired by task.
- **Cost:** API-equivalent `total_cost_usd` from stream-json output. It is not a billing amount.
- **Sample size:** 144 episodes per Haiku condition, 48 episodes for `X1_sonnet`; 768 episodes total; 0 error rows in the tables.

Protocol notes:

1. This is a single batch. All conditions ran interleaved in one session, but only once. `S_shot` in this batch scored 82 %, 4 points below R1's 86 % (the interval includes 0).
2. Two episodes failed because the `claude` command was replaced during an automatic update. They were rerun; no error rows remain.
3. `X2` uses a different coordinate frame from `X1` (1280×720 view versus screen pixels), so `X2 − X1` combines the differences in incremental updates, hover, look and coordinate frame. Most of the +23.6 comes from look: 90 % of X2 episodes used it at least once.
4. The perception service is shared by all episodes; the tree step takes 0.27 s per step on the GPU used for the run.
5. The cleaning thresholds were frozen in R2 and not changed here. The "×" failure below was found after this batch and was not part of the frozen rules.
6. Not measured: dense or high-DPI screens, non-Claude readers, economics with a more expensive model; 48 tasks, 8 apps, one 1920×1080 Linux desktop.

## Results

**Table main.** Main results, Haiku 5.5 with 144 episodes per condition unless noted. Differences are in percentage points against the same-batch S_shot.

| Condition | Success (95 % CI) | vs S_shot (pts) | $ / episode | Wall s mean (median) | Steps | observe / look / hover / action / done |
|---|---|---|---|---|---|---|
| S_shot | **82 %** [72, 91] | — | 0.0048 | 21.8 (15.6) | 11.5 | 35 % / — / — / 58 % / 7 % |
| X1 | 47 % [35, 59] | −34.7 [−47.2, −22.2] | 0.0031 | 25.0 (23.6) | 13.4 | 39 % / — / — / 54 % / 6 % |
| X1_sonnet | 67 % [54, 79] | −15.3 [−27.1, −4.2] | 0.0474 | 31.8 (26.2) | 11.1 | 15 % / — / — / 78 % / 7 % |
| X2 | 71 % [59, 83] | **−11.1 [−19.4, −4.2]** | 0.0036 | 26.0 (19.1) | 12.5 | 11 % / 22 % / 1 % / 61 % / 5 % |
| S_shot_lean | **89 %** [82, 95] | **+6.9 [+1.4, +13.2]** | 0.0038 | 19.5 (14.9) | 9.0 | — / — / — / 90 % / 10 % |
| X2_lean | 74 % [63, 85] | −7.6 [−16.0, −0.0] | 0.0036 | 24.6 (17.4) | 11.7 | — / 30 % / 1 % / 63 % / 6 % |

`X1_sonnet` has 48 episodes (one repetition per task) and is not directly comparable in interval width with the Haiku rows.

**Pass rule.** X2 − S_shot = −11.1 (threshold ≥ −5: not met); cost 0.0036 vs 0.0048 (lower: met); wall-clock 26.0 s vs 21.8 s (not slower: not met). Result: **FAIL.**

**Table paired.** Other paired differences, by task.

| Comparison | Difference (pts) [CI] |
|---|---|
| X2 − X1 | **+23.6 [+13.2, +34.0]** |
| X1_sonnet − X1 | +19.4 [+6.9, +31.9] |
| X2_lean − X2 | +3.5 [−4.9, +11.8] |
| X2_lean − S_shot_lean | −14.6 [−23.6, −6.9] |

Stratified: poor tier (gnome-calendar and gnome-contacts, 12 tasks) X2 − S_shot −8.3 [−22.2, 0.0]; good tier (36 tasks) −12.0 [−22.2, −3.7].

**Table vs_R1.** Same batch compared with R1 (paired by task, different day and batch).

| Comparison | Difference (pts) [CI] |
|---|---|
| S_shot (this batch) − R1 S_shot | −4.2 [−9.7, +0.7] |
| X1 − R1 T_ours | −9.7 [−22.2, +2.8] |
| X2 − R1 T_ours | +13.9 [+1.4, +27.8] |
| X1_sonnet − R1 S_shot_strong | −18.1 [−28.5, −7.6] |

**Table by_app.** Success by app (%).

| App | S_shot | S_shot_lean | X1 | X1_sonnet | X2 | X2_lean |
|---|---|---|---|---|---|---|
| drawing | 83 | 89 | **6** | 50 | 44 | 61 |
| gitg | 72 | 83 | 50 | 83 | 72 | 50 |
| gnome-calendar | 50 | 72 | 39 | 17 | 50 | 56 |
| gnome-contacts | 72 | 89 | 33 | 67 | 56 | 61 |
| keepassxc | 100 | 100 | 67 | 100 | 83 | 100 |
| lutris | 89 | 94 | 50 | 67 | 83 | 100 |
| obsidian | 89 | 89 | 56 | 50 | 78 | 78 |
| okular | 100 | 94 | 78 | 100 | 100 | 89 |

**Table stop_reason.** Stop reasons per condition (count, with successes in parentheses).

| Condition | done | fail_answer | step_limit | no_done | timeout |
|---|---|---|---|---|---|
| S_shot | 105 (105) | 8 (0) | 22 (7) | 9 (6) | 0 |
| X1 | 68 (63) | 51 (1) | 18 (2) | 7 (2) | 0 |
| X1_sonnet | 26 (24) | 10 (0) | 4 (0) | 8 (8) | 0 |
| X2 | 87 (87) | 11 (0) | 38 (8) | 8 (7) | 0 |
| S_shot_lean | 119 (119) | 6 (0) | 8 (0) | 11 (9) | 0 |
| X2_lean | 94 (94) | 9 (0) | 32 (6) | 9 (7) | 0 |

X1 mostly gives up (`fail_answer` in 35 % of episodes); X2 mostly runs out of steps (`step_limit` in 26 %, against 15 % for S_shot).

## look and hover

**Table look_hover.** Number of `look` calls per episode, and hover use.

| Condition | 0 looks | 1 | 2 | 3 | ≥ 4 | Mean / median looks per episode | Successful episodes with zero looks (share of successes) | Hover calls | Hovers that revealed new text |
|---|---|---|---|---|---|---|---|---|---|
| X2 | 13 (9 %) | 29 (20 %) | 39 (27 %) | 26 (18 %) | 37 (26 %) | 2.76 / 2 | 13 % (n = 102) | 14 | 9 (64 %) |
| X2_lean | 16 (11 %) | 13 (9 %) | 29 (20 %) | 25 (17 %) | 61 (42 %) | 3.50 / 3 | 15 % (n = 107) | 12 | 5 (42 %) |

- Hover was rarely used: 14 times in X2 out of about 1,800 calls. The sample is too small for a conclusion.
- Incremental updates in action steps: X2 — 34.0 % full-list fallback, 8.7 % `no change`, 57.3 % changes sent; X2_lean — 33.8 % / 6.2 % / 60.0 %. (R2 measured 21.3 % fallback on the R1 trajectories.)

## Tokens and wall-clock time

**Table tokens.** Real new tokens per step, from per-call usage in stream-json (deduplicated by message ID). Estimated with an intercept-free least-squares fit of context growth on observation characters, images, and output characters.

| Condition | a (tokens / character) | Observation characters per list step | List tokens per step (a × characters) | R2 estimate | Tokens per image |
|---|---|---|---|---|---|
| X1 | 0.667 | 739 | **493** | F2 594 (0.589 × R2 characters) | — |
| X1_sonnet | 0.618 | — | — | — | — |
| X2 full-list steps | 0.681 | 987 | 672 | — | 1,351 (look) |
| X2 changed-list steps | 0.681 | 239 | **163** | F3 271 (including the average of full first steps) | — |
| X2 all list steps | 0.681 | 566 | 385 | F3 271 | — |

- Measured tokens per character were 0.67–0.69, about 15 % above the 0.589 used in R2.
- X1 at 493 tokens per step is below R2's 594 only because the screens in this batch had shorter lists (739 characters).
- The fit has known defects: in `S_shot` the observation text is constant (one line of instructions) and fully collinear with the image, so its `a` is not meaningful and only the image term is used. For X2 39 of 144 episodes and for X2_lean 32 of 144 episodes were skipped because the number of API calls did not match the number of steps (parallel tool calls or truncated episodes). The screenshot figure of 1,154 tokens per image from R1 is used as the reference.
- Rough per-episode observation estimate: X2 ≈ 9.1 list steps × 385 + 2.76 looks × 1,351 ≈ 7,230 tokens; S_shot ≈ 11.5 × 1,154 ≈ 13,300 tokens.

**Table wall_clock.** Wall-clock decomposition per episode, averaged over episodes (seconds).

| Condition | Wall s | Model time | Observation time | of which tree computation | of which screenshot, encoding and queueing | Actions (including 0.8 s settle) | Other (claude start-up etc.) |
|---|---|---|---|---|---|---|---|
| S_shot | 21.8 | 11.0 | 0.59 | — | 0.59 | 5.58 | 4.7 |
| X1 | 25.0 | 11.1 | 3.61 | 2.81 | 0.79 | 5.97 | 4.3 |
| X2 | 26.0 | 11.8 | 3.21 | 2.44 | 0.62 | 6.41 | 4.6 |
| S_shot_lean | 19.5 | 7.7 | 0.46 | — | 0.46 | 6.69 | 4.7 |
| X2_lean | 24.6 | 10.7 | 2.74 | 2.06 | 0.47 | 6.14 | 5.1 |
| X1_sonnet | 31.8 | 15.1 | 3.53 | 2.71 | 0.81 | 7.18 | 6.0 |

- Queueing on the shared perception service was close to zero: 0.063–0.080 s per step for the X conditions (screenshot, encoding, queueing and socket), against 0.052 s for S_shot (screenshot and encoding only).
- X2 is 4.2 s slower per episode than S_shot, which is about 2.4 s of tree computation plus roughly one extra step. Even with free perception, X2 would only match S_shot on wall-clock.
- The initial observations of the lean conditions (screenshot ≤ 0.06 s, tree ≤ 0.4 s) happen before `claude` starts and are not included in wall_s.

## Failure analysis

**Table cleared_names.** Clicks inside cleared-name boxes, and episodes in which the cleared close button ("×") was clicked.

| Condition | Clicks inside a cleared-name box (successful / failed episodes) | Episodes that clicked the cleared "×" (close) button | Of which successful |
|---|---|---|---|
| X1 | 32 / 330; 112 / 452 | **39 / 144** | 0 |
| X1_sonnet | 25 / 161; 36 / 122 | 5 / 48 | 0 |
| X2 | 56 / 454; 51 / 269 | 8 / 144 | 0 |
| X2_lean | 60 / 453; 58 / 234 | 6 / 144 | 0 |
| R1 T_ours (close button name kept) | — | 0 / 144 | — |

- Mechanism: the close button in the title bar of GTK applications is a 24 px "×". The R2 rule (non-text role with max side < 32 px: clear the name; symbol-only names cleared) turned it into an unnamed `btn 1893,26`. The agent then clicked the rightmost unnamed button, thinking it was a menu. The application closed, and the list had one element afterwards. The same rule cleared "+" (new item) and "目" (menu), which made agents try buttons one by one and used steps.
- R2's guardrail only checked elements that were clicked in successful episodes; R1's `T_ours` agents did not click "×" once they could read it, so the guardrail could not see this harm.
- This is the main reason X1 is below R1's `T_ours` (−9.7) and why X1 scores 6 % on drawing. Upper estimate, not a result: if all 8 close-button episodes in X2 had succeeded, X2 would be about +5.6 points higher (about 77 %), which is still on the threshold line, and the wall-clock criterion would still fail.

**Table failures.** Hand classification of 15 failed episodes (9 from X1, 6 from X2), drawn with a fixed seed from the failed episodes. Classification used the R1 failure categories; it was done by a reviewer model (Claude Sonnet 5.5) from the trajectories and screenshots, with 2 cases spot-checked against the archive and found consistent. The sample is too small for rates; it shows the types of failure only.

| Condition | missing_element | wrong_name | bad_coordinates | agent_reasoning | task_ambiguity | harness_or_oracle | Cleared name was the cause |
|---|---|---|---|---|---|---|---|
| X1 | 0 | 7 | 0 | 2 | 0 | 0 | 5 |
| X2 | 0 | 1 | 0 | 5 | 0 | 0 | 1 |

- Of X1's 7 `wrong_name` cases, 5 were the cleared "×" or "+"; the other 2 were names that OCR never read (not caused by the cleaning).
- X2's 5 `agent_reasoning` cases: the form was filled in but OK was not clicked and the steps ran out; in gnome-contacts a row was added and the wrong row was clicked (the same failure as S_shot in R1); a field was cleared character by character with BackSpace.
- The first-view check: 5 episodes per lean condition were drawn with a fixed seed (sorted by task and repetition); in 10 of 10 the full first screenshot had been rendered.
