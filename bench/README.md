# bench: a Linux desktop agent testbench

A research testbench, not a product.  It exists so that the experiments of the accompanying paper can be re-run and
audited: 48 frozen tasks on 8 real desktop applications, a programmatic judge that reads what each application wrote to
disk, an Xvfb desktop per episode, a six-tool MCP server, two agent shells (`claude -p` and OMP), the exact condition
definitions and system prompts, lockdown probes and the analysis scripts.  The perception code it evaluates (the
screenshot -> element-tree pipeline `ours`) lives in the `pixeltree` package next to this directory; `bench` imports it
as `pixeltree.perceive` and `pixeltree.formats`.

Experiment names used throughout the code and in the paper:

| name | what |
|---|---|
| R1 | main exam: Claude Haiku through `claude -p`, 48 tasks x 7 conditions x 3 repetitions |
| R2 | offline token accounting of the element-list formats (no model calls) |
| R3 | tree-first conditions: cleaned element list, changes-only list, `hover` + `look` tools (Haiku, `claude -p`) |
| R4 | Gemini through a third-party agent shell (not part of this repository) |
| R5 | four reader models (GLM, DeepSeek, LongCat, Haiku) through the OMP shell |
| D1, D2 | detector experiments (not in `bench`) |

## Layout

```
bench/
  tasks_v1.json            the 48 frozen tasks (id, app, tier, difficulty, sentence); TASKS.md is the readable table
  tasks.py                 python -m bench.tasks --markdown   (regenerates TASKS.md)
  apps/                    one file per application: how to start / close it, its initial state, its 6 tasks, oracles
                           and positive scripts (_template.py is the commented empty one)
  env/                     the desktop and the judge: desktop.py (Xvfb + dbus + AT-SPI + XTEST input), episode.py
                           (start_episode / close_app / stop), sandbox.py (files every app finds in $HOME), app_prep.py
                           (git repo, Obsidian vault, flatpak argv), actions.py (the whitelist of agent actions),
                           oracle_kit.py + registry.py (oracle helpers, task registry), oracles_v1_1.py, selftest.py
  agent/                   R1: prompts.py (system prompts, verbatim), observation.py (what each condition sees),
                           mcp_server.py (the six tools), run.py (runner for `claude -p`), regrade.py, summarize.py,
                           compare.py, probe_lockdown.py, transcript.py (stream-json readers)
  perception/              tree sources besides `ours`: sources.py (one entry point), atspi.py, omni.py + omni_server.py
                           (OmniParser baseline, setup in OMNI_SETUP.md), cli.py (screenshot -> tree on the command line)
  variants/tree_first/     R3: conds.py (conditions X1, X1_sonnet, X2, S_shot_lean, X2_lean), prompts.py, observer.py,
                           mcp_server.py (adds hover / look), ours_server.py (resident perception server, also used by R5),
                           analyze.py, extra.py, probe.py, run_formal.sh
  shells/omp/              R5: the OMP shell: omp.py, run.py, mcp_server.py (in-order execution), omp_prompt.ts (system-prompt
                           hook), omp_overlay.yml, probes, analyze.py, run_formal.sh
  analysis/                R2 and token accounting: measure.py, calib_build.py, calibrate.py, obs_tokens.py
  tests/                   unit tests (no GUI, no model); oracle tests on stored end states in tests/fixtures/
```

## System dependencies

Tested on Ubuntu / Debian style systems; package names below are for apt, "verify on your distro" for anything else.

* `xvfb` (every episode gets its own virtual 1920x1080 display), `dbus` (`dbus-daemon`), `at-spi2-core`
  (`/usr/libexec/at-spi-bus-launcher`), `openssl`, `git`.
* Input is injected with XTEST through `python-xlib`; `xdotool` and a window manager are **not** needed (there is no window
  manager: the harness stretches the main window over the screen).
* AT-SPI queries (the `T_atspi` / `H_atspi` conditions and the positive scripts) run in the system
  `/usr/bin/python3`, which must import `gi.repository.Atspi` (`python3-gi`, `gir1.2-atspi-2.0`).
* Python (3.11+) packages used by the harness: `numpy`, `Pillow`, `opencv-python`, `python-xlib`, `mss`, `mcp` (the MCP
  server), `pypdf` (oracle v1.1), `pytest`.  Versions of the published runs: mcp 2.3.0, pypdf 5.1.0, python-xlib 0.33,
  mss 10.2.0.  The oracles, the task registry and `tasks.py` need only the standard library (plus `pypdf` for two oracles).
* `claude` (Claude Code CLI, logged in) for R1 and R3; `omp` (oh-my-pi, v18.16) with an `opencode-go` provider login for R5.
* The `ours` perception pipeline (`pixeltree.perceive`) needs its model weights; a GPU is recommended (see the pixeltree docs).

Applications under test (all must be installed and runnable without network):

| app | install | notes |
|---|---|---|
| Drawing | `apt install drawing` | settings are read from the GSettings keyfile backend |
| gitg | `apt install gitg` | the repository is generated by `git` in the sandbox |
| KeePassXC | `apt install keepassxc` | the oracle uses `keepassxc-cli` (same package on Debian / Ubuntu; some distros split it) |
| Lutris | distro package or upstream `.deb` (verify on your distro) | must be importable by `/usr/bin/python3` (the setup adds games through Lutris' own Python API), so a flatpak build does not work |
| Obsidian | `flatpak install --user flathub md.obsidian.Obsidian` | started with `flatpak run --user`; needs the real `XDG_RUNTIME_DIR`; an episode takes about a minute |
| Okular | `apt install okular` (the Qt6 build) | |
| GNOME Calendar | `apt install gnome-calendar evolution-data-server` | data lives in Evolution Data Server, started by D-Bus activation inside the episode |
| GNOME Contacts | `apt install gnome-contacts evolution-data-server` | same |

## Tasks and conditions

`TASKS.md` lists the 48 tasks (six per application, difficulty 1-3) with the sentence the agent receives and what the oracle
checks.  The task files are frozen: the sentences, oracles and the files in `apps/`, `env/episode.py`,
`env/oracle_kit.py`, `env/registry.py` and `tasks_v1.json` are the object under test; `bench.agent.run --freeze-sha <commit>`
refuses to start when they differ from a commit.

Every episode: fresh sandbox `$HOME`, fresh Xvfb, one application, at most 20 tool calls, then the oracle.  The agent sees
the screen only through the six tools `observe`, `click`, `type`, `key`, `scroll`, `done` (R3 adds `hover` and `look` for
two conditions).  The conditions differ only in what an observation contains; tools, call limit and the rest of the system
prompt are identical.

| condition | model | an observation is | defined in |
|---|---|---|---|
| `S_shot` | Haiku | the screenshot scaled to 1280x720 plus a one-line note; click / scroll coordinates are pixels of that image | `agent/prompts.py`, `agent/observation.py` |
| `S_shot_strong` | Sonnet | as `S_shot` | same |
| `T_ours` | Haiku | text element list from `pixeltree.perceive` (`ours`), screen pixels | same |
| `T_atspi` | Haiku | text element list from the AT-SPI tree | same |
| `T_omni` | Haiku | text element list from OmniParser (needs the OmniParser server, `perception/OMNI_SETUP.md`) | same |
| `H_ours` | Haiku | screenshot + `ours` list in screenshot coordinates | same |
| `H_atspi` | Haiku | screenshot + AT-SPI list in screenshot coordinates | same |
| `X1` (R3) | Haiku | cleaned element list (`pixeltree.formats` F2), screen pixels | `variants/tree_first/conds.py`, `prompts.py`, `observer.py` |
| `X1_sonnet` (R3) | Sonnet | as `X1` | same |
| `X2` (R3) | Haiku | first the cleaned list, afterwards only the changes (F3), 1280x720 coordinates; extra tools `hover(x, y)` and `look()` (a screenshot) | same |
| `S_shot_lean` (R3) | Haiku | screenshot only; no `observe` tool, the first screenshot comes with the task | same |
| `X2_lean` (R3) | Haiku | as `X2` but without `observe`: the full list comes with the task | same |

The system prompts are verbatim constants (the wording is part of the design): `agent/prompts.py` for the R1 conditions,
`variants/tree_first/prompts.py` for R3.  R5 uses the R1 prompts plus one coordinate sentence for the image conditions
(`shells/omp/shared.py: COORD_NOTE`).  Historical names that are part of the frozen prompts and tool names were kept:
the MCP server is registered as `p125`, so the tools are called `mcp__p125__observe` and so on; the environment variables
of the server are `P125_*`; some helper variables start with `VAX_`.

## Tool lockdown (`claude -p`)

The agent must be able to use the six MCP tools and nothing else (no shell, no file access, no web, no subagent).
`agent/run.py` starts `claude` with exactly these flags:

```
claude -p <task sentence> --model <haiku|sonnet>
  --system-prompt <condition prompt>
  --mcp-config <episode>/mcp.json --strict-mcp-config
  --tools ""                                  # no built-in tools at all
  --allowedTools mcp__p125__observe,mcp__p125__click,mcp__p125__type,mcp__p125__key,mcp__p125__scroll,mcp__p125__done
  --disallowedTools Bash,BashOutput,KillShell,Read,Write,Edit,MultiEdit,NotebookEdit,Glob,Grep,LS,WebFetch,WebSearch,Agent,Task,Skill,TodoWrite,ToolSearch,Monitor,SlashCommand
  --disable-slash-commands
  --setting-sources "" --no-session-persistence
  --output-format stream-json --verbose
```

(R3's lean conditions use `--input-format stream-json` so that the first screenshot or list can travel with the task.)  The
process runs in a fresh empty directory `/tmp/pixeltree_agent/<episode>` (not in a repository: otherwise Claude Code adds the
project's memory and git context to the agent's prompt), with `DISPLAY` / Wayland variables removed, and is killed after 15
minutes (`stop_reason = timeout`, counted as a failure).  A run is marked as a harness error and repeated when the init
event does not show the `p125` server as connected or the cwd is not under `/tmp/pixeltree_agent`.

Lockdown probe: a "permissions test" task asks the agent to run a shell command, read `/etc/hostname`, write a file, fetch a
URL and start a subagent.  The probe passes for a condition when the init event lists exactly the condition's MCP tools, no
tool outside them produced a non-error result, the content of `/etc/hostname` appears nowhere in the transcript and the
probe file was not written.  It makes real model calls.

```sh
Xvfb :149 -screen 0 1920x1080x24 &
python -m bench.agent.probe_lockdown --out out/r1/lockdown        # the R1 conditions
python -m bench.variants.tree_first.probe --out out/r3/probe       # the R3 conditions
python -m bench.shells.omp.probe --model glm --out out/r5/glm/probe  # R5: lockdown, vision and tool-call probes per model
```

## The OMP shell (R5)

R5 runs other reader models through OMP instead of `claude -p`.  To keep the experiment comparable, three things differ from
a stock OMP session, all in `shells/omp/`:

1. **System-prompt hook** (`omp_prompt.ts`, loaded with `omp -e`).  OMP's `--system-prompt` only appends to its own prompt (it
   adds a project-context block and a "critical" block, and prefixes the first user message with a date / cwd reminder).
   `claude -p --system-prompt` sends the given text alone.  The hook rewrites every provider request so that the system
   prompt is exactly the condition's text and the reminder is gone, and logs a hash of what was actually sent, the offered
   tool names and the image sizes (`requests.jsonl`) so that each episode can be checked afterwards.
2. **Behaviours switched off** (`omp_overlay.yml`, passed with `--config`; plus `--no-tools --no-extensions --no-skills
   --no-rules --no-context-files --no-lsp --no-title --no-session`).  No intent-tracing argument on the tool schemas, no model
   fallback or retry to another model, no context compaction, no loop guards or auto-continue, no image description for
   text-only models, no image resizing, no memory / auto-learning / advisor / recap.  Reason: the agent loop should be as close
   as possible to `claude -p`, and the model under test should be the only thing that varies.
3. **In-order tool execution** (`OrderedGate` in `mcp_server.py`).  OMP sends all tool calls of one model message to the MCP
   server at once and the MCP library runs each request in its own thread, so a message `[click, type, click, type, observe]`
   was executed in arbitrary order.  `claude -p` executes them in the order the model wrote them.  The hook logs every call in
   the model's order (`calls.jsonl`) before it is sent, and the gate runs the calls one at a time in that order (after 5 s
   without progress a waiting call runs anyway and the fallback is recorded in `order_fallbacks.txt`).

Calls to any tool outside the six make the episode `invalid`; it is counted but not part of the success denominator.  Episodes
are limited to 10 minutes.  The runner stops itself (writes `<out>/STOP`) on a provider quota / rate-limit error that survives
three attempts, when the local time passes `BENCH_NIGHT_HHMM` (optional, e.g. `2340`), and from 2026-11-15 on for the
calendar tasks.

## Grading

The judge never looks at the screen or at the agent's answer.  Each task has an **oracle**: a function
`oracle(home) -> (ok, detail)` that reads what the application persisted in the sandbox `$HOME` after the app was closed
(`Episode.close_app()` closes it the way the app expects and answers "save changes?" prompts): files, sqlite databases,
iCalendar and vCard stores, KeePass databases through `keepassxc-cli`, git repositories, INI / XML / PDF.  Oracles are helpers
from `env/oracle_kit.py`; they return `None` for unreadable state and never raise.  Every task also has a **positive script**
(a human-style UI session) so that task and oracle are proven consistent: `python -m bench.env.selftest` runs the positive
script (must pass) and a 5-second no-op (must fail) for every task.

Oracle **v1** is the frozen original in `apps/`.  **v1.1** (`env/oracles_v1_1.py`) changed only how the two Okular note tasks
parse the saved PDF: v1 used a regular expression that matched only generation-0 objects and read every revision of an
incrementally saved file, v1.1 uses `pypdf` and the final revision.  `bench.agent.regrade` re-applies the oracles to the
archived end state of every episode (`ep/*/sbx/home`): `--check` proves the stored v1 grades reproduce, `--oracles v1_1 --tag
v1_1` writes `episodes_v1_1.jsonl`.

## Fixed-date tasks

The six GNOME Calendar tasks use absolute dates between 2026-11-12 and 2026-11-27 (and the seed calendar has an event on
2026-11-18).  Calendar shows the real date and the positive scripts compute grid cells from `date.today()`; the month grid starts
at the Sunday of the week that contains today and covers five rows, so these dates are reachable only when the run happens
between **2026-11-08 and 2026-11-14**.  The runners therefore stop (R3 driver) or skip the calendar tasks (R5) from 2026-11-15.
Running these tasks at another date needs a clock override, which this repository does not provide.

## Running the experiments

All commands from the repository root, with the dependencies above installed, one free display number per parallel worker
(`:140`-`:143` below), and `pixeltree.perceive` able to load its weights.  Outputs go to `./out/...` (git-ignored).

```sh
# R1: main exam (7 conditions x 48 tasks x 3 repetitions; resumable, `touch out/r1/formal/STOP` finishes the running
# episodes and starts no new one)
python -m bench.agent.run --tasks all --reps 3 --parallel 3 --displays :140,:141,:142,:143 \
    --out out/r1/formal [--freeze-sha <commit>]          # default --conds = all seven
python -m bench.agent.regrade out/r1/formal --check
python -m bench.agent.regrade out/r1/formal --oracles v1_1 --tag v1_1
python -m bench.agent.summarize out/r1/formal/episodes_v1_1.jsonl
python -m bench.agent.compare out/r1/formal/episodes_v1_1.jsonl --pairs T_ours:T_atspi,S_shot:T_ours
python -m bench.analysis.obs_tokens out/r1/formal --out out/r1/obs_tokens

# R2: offline token accounting (needs the R1 archive, no model call)
python -m bench.analysis.measure --rows out/r1/formal/episodes_v1_1.jsonl --out out/r2

# R3: tree-first conditions (starts the resident perception server on the first display, then the runner)
PY=python OUT=out/r3/formal R1_ROWS=out/r1/formal/episodes_v1_1.jsonl bash bench/variants/tree_first/run_formal.sh

# R5: one lane per reader model (<model>:<display number>); BENCH_OMP_FIRST=48 runs all tasks (default 24)
python -m bench.shells.omp.probe --model glm --out out/r5/glm/probe        # per model, before the formal run
PY=python OUT=out/r5 BENCH_OMP_FIRST=48 bash bench/shells/omp/run_formal.sh glm:150 deepseek:151 longcat:152 haiku:153
python -m bench.shells.omp.analyze --run glm=out/r5/glm/formal/episodes_v1_1.jsonl --run haiku=... \
    --ref-r1 out/r1/formal/episodes_v1_1.jsonl --out out/r5/analysis
```

Output layout of one run directory (R1, R3, R5 share it):

```
<out>/episodes.jsonl             one row per episode (task, app, difficulty, cond, model, rep, ok, oracle_detail, stop_reason,
                                 answer, steps, token counts, cost_usd, wall_s, mean_obs_s, mean_model_s, t_start, tier, dir)
<out>/STOP                       (you create it) no new episode starts
<out>/ep/<task>__<cond>__r<rep>/
    transcript.jsonl             the agent's stream (every message, tool call and result)
    mcp.json  episode.json  result.json  done.json  claude.stderr   configuration, row, the agent's final answer
    sbx/                         sandbox HOME after the episode (the oracle's input; `regrade` reads it)
    steps/<NN>/                  one directory per tool call: screen.png (raw 1920x1080 after the action), obs.txt (what the
                                 agent got back), action.json (tool, args, timings), shot.png / tree.json (image / element list)
```

`stop_reason` is one of `done`, `fail_answer` (done with an answer starting `FAIL:`), `step_limit`, `timeout`, `error`
(harness failure, rerun on resume) and `no_done`.  `cost_usd` is the API-equivalent price reported by `claude`, not a billing
record.

Unit tests (no application, no GUI, no model; tests that need `cv2`, `keepassxc-cli` or `git` skip themselves when the tool
is missing):

```sh
python -m pytest bench/tests -q
python -m bench.env.registry --check        # structure of apps/ and tasks (no GUI)
python -m bench.env.selftest --tasks all --mode both --display :130 --out out/selftest   # needs the applications and Xvfb
```
