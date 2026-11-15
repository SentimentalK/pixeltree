# OmniParser v2 baseline tree source: setup (condition T_omni)

Screenshot PNG → element list, via a resident server. Client: `omni.py` (`parse(png_bytes)`, stdlib only,
importable from any venv). Server: `omni_server.py` (runs in OmniParser's own venv, outside git).

## Versions used for the published run (installed 2026-11-11)
- Code: `microsoft/OmniParser` @ `354021201345a96178360b28733573e27269f2de` (master, 2026-07-19), cloned to any directory; point `OMNI_HOME` at it (default `./OmniParser`).
- Venv: a separate venv (uv, CPython 3.12.14), referred to below as `<omniparser venv>`: torch 2.15.0, torchvision 0.29.2, **transformers 4.46.3** (4.57 breaks Florence-2 remote code: `_supports_sdpa`), tokenizers 0.20.3, easyocr 1.7.2, supervision 0.18.0, numpy 1.26.4, timm 1.0.31, einops 0.8.0, opencv-python-headless 4.11.0.86, openai 1.3.5. Not installed: ultralytics (only needed for the old v2 YOLOv8 detector), paddle/paddleocr, gradio and the other OmniTool deps.
- Weights: HF `microsoft/OmniParser-v2.0` @ `f55d0750e5b94db2125ef0b45b0fa4a85ddc59b4`, in `$OMNI_HOME/weights/` (git-ignored upstream, never committed here).

| file | sha256 | license |
|---|---|---|
| `icon_detect_v3/model.pt` (YOLOv9-E, **used**, upstream's current default) | `11c6cbb77f22569fab22d86c76407a83ec81ab89dbfe28279854822d6e3fb00c` | MIT |
| `icon_caption_florence/model.safetensors` (Florence-2 captioner, **used**; = HF `icon_caption/`) | `01b934b0fe2d07b181e2d07752f16ae27c9d0ea88ddffe13a9a003aa9680f233` | MIT |
| `icon_caption_florence/config.json` | `1c3c63bb16910b8fa7f3b74fb7ae4c8ffefbe7b008847e2e0b21be6aa807593b` | |
| `icon_caption_florence/generation_config.json` | `a2ef03e814a7ecbf6fcfe7479afd3e7385c6800202fcede1dc1bc01849375464` | |
| `icon_detect/model.pt` (original v2 YOLOv8, downloaded for reference, **not used**) | `dab3d4351ad00b035db829909a4db98354d5a90f6990e4ac00222a9a95d4bf57` | AGPL-3.0 |

The Florence-2 processor/remote code (`microsoft/Florence-2-base`) and EasyOCR English models are fetched on first run into `~/.cache/huggingface` and `~/.EasyOCR`.

**Licensing:** OmniParser code is CC-BY-4.0 (repo `LICENSE`); `icon_detect_v3` and `icon_caption` are MIT; the old `icon_detect` (YOLOv8/Ultralytics) is AGPL-3.0, one more reason to stay on v3. Used here as a baseline only; cite Microsoft's OmniParser if results are published.

## Config = OmniParser defaults (nothing tuned)
Uses the repo's own `util.omniparser.Omniparser` with the OmniTool-server defaults: `BOX_TRESHOLD=0.05`, EasyOCR `text_threshold=0.8`, `iou_threshold=0.7`, Florence-2 captions, `use_paddleocr=False`. Upstream's repo default detector is now `icon_detect_v3` (YOLOv9-E, HF PR #37 merged); the older v2 YOLOv8 file sits next to it in the same HF repo. We followed the repo default.
Output mapping: type `text` → role `text` (name = OCR text, interactable False); type `icon` → role `icon` (name = Florence-2 caption, interactable True); normalized xyxy → integer `[x, y, w, h]` in input pixels.

## Adaptation (no upstream file edited)
`util/utils.py` builds a `PaddleOCR` at import although the default OCR is EasyOCR; the server stubs the `paddleocr` module before import so paddle need not be installed.

## Run
```sh
# from the repo root; models load in ~20 s (first ever run downloads Florence code + EasyOCR models)
OMNI_HOME=/path/to/OmniParser <omniparser venv>/bin/python bench/perception/omni_server.py
# background: (setsid nohup <the command above> > /tmp/omni_server.log 2>&1 < /dev/null &)
```
Socket `/tmp/pixeltree_omni.sock` (override `P125_OMNI_SOCK`), mode 0600. Requests are served strictly serially; extra clients queue in the listen backlog (32), so several harness processes may call concurrently. `parse()` raises `OmniServerDown` with the start command if nothing listens. Client timeout 600 s (`P125_OMNI_TIMEOUT`). `omni.ping()` / `omni.stats()` for health and CUDA memory.

## Measured (RTX 2060 6 GB, 10 screenshots 1920×1080, after one warm-up call)
Median 1.65 s/frame (1.09–2.19), mean 30.6 elements/frame; nvidia-smi peak 4.8 GB (torch max-allocated 1.97 GB) with the server alone; 3 processes × 3 parses: 9/9 ok, each call 1.5–4.3 s incl. queue wait.

## Known baseline behaviour (default config, observed in overlays)
Large black/empty regions are detected as icons (e.g. gitg: two big icon boxes on the black desktop); small text may be both a `text` and an `icon` box; icon captions are often a guess ("Tjin") — they are OmniParser's own output, kept as is.
