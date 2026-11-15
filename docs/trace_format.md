# Episode trace format `pixeltree.trace/1`

An **episode** (one AI agent doing one task in one real desktop app, at most 20 steps) is one directory:

```
<trace dir>/
  meta.json     written once when the episode starts
  steps.jsonl   one line per step (a live recorder can append while the episode runs)
  result.json   written when the episode ends; absent = the episode is still running
  img/          screenshots referenced by steps.jsonl (optional; any relative layout works)
```

All JSON is written with `ensure_ascii=False, sort_keys=True`. Path fields may be absolute or relative to
the trace directory; the exported example episodes use relative paths (`img/01.webp`), so a trace directory
can be moved or zipped as a whole. Large files such as screenshots are referenced, never embedded.

The reading and writing API is in `pixeltree/trace/format.py`: `write_trace(dir, meta, steps, result)`,
`append_step(dir, step)` and `read_trace(dir) -> {"meta", "steps", "result"}` (`result` is `None` when
`result.json` does not exist).

The offline viewer builds a replay site from a directory of such episodes:

```
python -m pixeltree.viewer build --traces <dir with one subdirectory per episode> --out site
```

## meta.json

| Field | Type | Description |
|---|---|---|
| `format` | string | Always `"pixeltree.trace/1"` |
| `id` | string | `<source>__<model key>__<task>__<condition>__r<rep>`, e.g. `r5__glm__drawing_no_ctrl_zoom__H_ours__r0` |
| `source.kind` | string | Where the episode comes from: `r1`, `r3` or `r5` for the experiments of this repository (other values are fine for your own recordings) |
| `source.path` | string, optional | Original location of the episode. Written by the adapters for raw archives; the exporter and the site build drop it |
| `task.id` / `task.app` / `task.sentence` / `task.difficulty` | | Task id, app, the task sentence given to the agent, difficulty |
| `model.key` / `model.name` / `model.id` | | Model key (`glm`, `deepseek`, `longcat`, `haiku`, `sonnet`, ...), display name; `id` (raw model id) is optional |
| `condition.key` / `condition.note` | | Condition key (`S_shot`, `T_ours`, `H_ours`, ...) and a one-line description |
| `shell` | string | The harness that ran the agent: `OMP` or `claude -p` |
| `rep` | integer | Which repetition of this (task, condition) |
| `started_at` | ISO string, optional | Start time |
| `screen_size` | `[1920, 1080]` | Size of the desktop screen; all element boxes and action coordinates live in this space |
| `agent_image_size` | `[1280, 720]` or `null` | Size of the image the agent received; `null` for conditions without an image |
| `observation` | `"tree"` / `"image"` / `"tree+image"` | What the agent received at each step |

## steps.jsonl (one step per line)

| Field | Description |
|---|---|
| `i` | Step number, starting at 1 |
| `t_start` / `t_end` | Epoch seconds (float), may be `null` |
| `duration_s` | Duration of the step in seconds |
| `action.tool` | `observe` / `click` / `type` / `key` / `scroll` / `done` (some experiments also use `hover` / `look`) |
| `action.args` | Tool arguments as the agent gave them (coordinates may be on the 1280×720 image) |
| `action.screen_xy` | The coordinates actually executed on the 1920×1080 screen; `null` for non-pointer tools |
| `action.ok` / `action.error` | Whether the action executed successfully / the error text |
| `agent.text` | What the agent said in the same message before this call (may be empty) |
| `agent.thinking` | Visible thinking text (may be empty) |
| `agent.message_index` | Which agent message (from 0) this call belongs to. Consecutive calls of one message were issued without the agent seeing a new screen; `text` / `thinking` are attached only to the first call of a message |
| `observation.text` | The observation the agent received **after** this step (tree text / screenshot caption / error), verbatim |
| `observation.image` | Path of the image the agent received (1280×720), or `null` |
| `screen` | Path of the desktop screenshot taken **after** this step was executed. It may be stored at a lower resolution than `screen_size` (the exported examples use 1280×720 WebP) as long as the aspect ratio is the same |
| `tree` | `{"source": "ours" / "atspi", "elements": [...]}`, or `null` for conditions without a tree. Element = `{"id", "role", "name", "box": [x, y, w, h], "conf"}` with `box` in `screen_size` pixels (`conf` is optional) |

Timing (the easiest thing to get backwards when reading a replay): the `screen`, `tree` and `observation` of
step N are all the state **after step N was executed**; when the agent decided step N it was looking at the
state after step N−1.

## result.json

| Field | Description |
|---|---|
| `ok` | Success or failure (from the re-grading file, not the runtime grader) |
| `grader` | `"oracle v1.1"` |
| `grader_detail` | The grading evidence verbatim (a program reads the state the app actually saved to disk; no human or AI judge) |
| `stop_reason` | `done` (the agent said it was done) / `step_limit` (used all 20 steps) / `timeout` / `no_done` / `fail_answer` (the agent said it could not do it) |
| `answer` | The agent's final answer |
| `steps` / `wall_s` | Total steps / total wall time in seconds |
| `tokens.input` / `tokens.output` / `tokens.cache_read` | Token usage |
| `cost_usd` | API-equivalent cost of the episode in US dollars |

## A complete small example

`meta.json`:

```json
{"agent_image_size": [1280, 720], "condition": {"key": "H_ours", "note": "Screenshot + our tree, both in the 1280×720 frame."}, "format": "pixeltree.trace/1", "id": "r5__deepseek__gitg_stage_readme__H_ours__r0", "model": {"key": "deepseek", "name": "DeepSeek V4.1 Flash"}, "observation": "tree+image", "rep": 0, "screen_size": [1920, 1080], "shell": "OMP", "source": {"kind": "r5"}, "task": {"app": "gitg", "difficulty": 1, "id": "gitg_stage_readme", "sentence": "In gitg, stage the modified file README.md without committing, and leave src/util.py unstaged."}}
```

Line 2 of `steps.jsonl` (abridged):

```json
{"action": {"args": {"button": "left", "double": false, "x": 19, "y": 18}, "error": null, "ok": true, "screen_xy": [28, 27], "tool": "click"}, "agent": {"message_index": 1, "text": "", "thinking": "This is gitg, a git repository viewer."}, "duration_s": 0.952, "i": 2, "observation": {"image": "img/02_a.webp", "text": "Screenshot 1280x720. …\naria:button [e1] \"Clone\" @(7,7,46,23) c=(30,18)\n…"}, "screen": "img/02.webp", "t_end": null, "t_start": null, "tree": {"elements": [{"box": [10, 10, 69, 34], "id": "e1", "name": "Clone", "role": "aria:button"}], "source": "ours"}}
```

`result.json`:

```json
{"answer": "FAIL: gitg is a read-only git history viewer …", "cost_usd": 0.006895, "grader": "oracle v1.1", "grader_detail": "staged=[] commits='5'", "ok": false, "steps": 7, "stop_reason": "fail_answer", "tokens": {"cache_read": 59648, "input": 34575, "output": 2550}, "wall_s": 67.6}
```

## Raw archives and the adapters

The experiments were recorded in three raw archive layouts, which the adapters in
`pixeltree/trace/adapters.py` convert to traces (read-only): kind `w2c` = experiment R5 (agents run through
the OMP shell), `p125` = R1 and `w2` = R3 (both `claude -p`). `python -m pixeltree.viewer export` converts
selected archive episodes into self-contained trace directories (images re-encoded to 1280×720 WebP, relative
paths, no archive paths, ids and `source.kind` renamed to `r5` / `r1` / `r3`); the examples under
`examples/episodes/` were produced this way.

The adapters align a transcript with the step directories as follows: the agent's messages are flattened, in
order, into a list of tool calls, and call k belongs to `steps/<k as two digits>/`. When there are more or
fewer step directories than calls, the step directories win and the missing agent fields are empty
(`message_index` is `null`). Calls beyond the 20-step limit in R5 episodes have no step directory and are
dropped.
