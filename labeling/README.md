# Labeling recipe

This directory holds the scripts and prompts used to produce box labels for the UI-element detector:
frame list -> frontier-model labelling under one box convention -> QA sample and fix pass -> label format
export -> YOLO dataset -> training -> held-out evaluation.

Paths below are placeholders. Run every command from the repository root. The box rules are in
[`box_convention_v1.md`](box_convention_v1.md); the labelling prompt is in [`prompts/label_rules_v1_1.md`](prompts/label_rules_v1_1.md).

## What is included and what is not

| Included | Not included |
|---|---|
| Labelling prompts (`prompts/`) and the box convention | Frame-selection gate (which screenshots are kept) and the capture tooling that produced screenshots |
| Batch creation, label / QA / fix driver, label format, validation, YOLO export | Any training or evaluation image, and any label file |
| Training app for Modal and its helpers (`training/`) | Ledgers of past runs |
| Evaluation scorer (`eval/score.py`) | Detector weights (see the repository `weights/` notes) |

The data itself is described in [`../DATA.md`](../DATA.md). The per-source counts and the labelling cost of the
released label set are in [`../results/labeling_cost.md`](../results/labeling_cost.md).

## Pipeline

Each step gives one command. Check exact flags with `--help`.

1. **Frame selection (not included).** Produce a selection file with one row per kept screenshot: image path,
   source, application, platform and the crop rectangle in original-image pixels.

2. **Batch manifest.** Turn the selection into a manifest (one row per image, with the labelling fields):

   ```sh
   python labeling/batch.py select --selection work/selection.jsonl --out-dir work/batch1
   ```

   This writes `work/batch1/manifest_batch1.jsonl`, used below as the manifest.

   `select` applies the per-source quotas and per-application caps in `batch.py` (`QUOTAS`).
   The `pool` and `exam` subcommands need the frame-selection rules module, which is not included.

3. **Frames for the labeller.** Choose whole-image or tile mode. Images whose long side is above 2560 px are
   labelled in four tiles; the tiles are stitched back by `merge`.

   ```sh
   python labeling/tile_merge.py frames --manifest work/batch1/manifest_batch1.jsonl \
       --gids <comma-separated gids> --mode whole --out work/batch1/whole
   python labeling/tile_merge.py frames --manifest work/batch1/manifest_batch1.jsonl \
       --gids <comma-separated gids> --mode tile --out work/batch1/tile
   ```

4. **Label, QA, fix and review (driver).** Write a plan file and run the driver. For each batch the driver
   makes label batches, calls the labeller, merges, samples 20 % of each application for QA, checks the QA
   gate, exports ULF records and writes the review page.

   ```json
   {
     "rules": "../labeling/prompts/label_rules_v1_1.md",
     "qa_rules": "qa_rules_v1_1.md",
     "label_model": "claude-opus-5-5",
     "qa_model": "claude-sonnet-5-5",
     "effort": "high",
     "jobs": 2,
     "chunk": 8,
     "batches": [
       {"name": "batch1", "dir": "batch1/whole", "manifest": "batch1/manifest_batch1.jsonl"}
     ]
   }
   ```

   ```sh
   python labeling/driver.py run --plan work/plan.json            # add --dry-run to print the state only
   ```

   The label calls are `claude -p` with the Read and Write tools only, one call per batch of images
   (`label_one.py`). The labelling prompt is `prompts/label_rules_v1_1.md`; the QA prompt is
   `prompts/qa_rules_v1_1.md`; the fix prompt is `prompts/fix_rules_v1_1.md`. The `gold119_*` prompts are
   the prompts of the earlier 186-image gold set. Labelling uses the Opus model and QA uses the Sonnet model;
   a QA gate stops the run when more than 15 % of the sample needs a fix or more than 5 % is rejected.
   The driver writes `driver_events.log`, and a `STOP` file on any stop; delete `STOP` to resume.

   Cost of the call: the ledger (`work/*/ledger.tsv`) records the token usage of each call. Summarise it with
   `python labeling/driver.py ledger --root work`.

5. **Label format check.**

   ```sh
   python labeling/validate.py work/batch1/labels_batch1.jsonl --data-root <directory that holds the images>
   ```

6. **Split and YOLO export.** Create the internal validation split and the held-out files, then export.

   ```sh
   python labeling/training/prep_split.py --train work/train.jsonl --exam work/exam.jsonl --out work/yolo_prep
   python labeling/export_yolo.py --jsonl work/train.jsonl work/exam.jsonl --out work/yolo \
       --exam work/yolo_prep/holdout_exam.json --classes 16
   ```

   `--classes 16` keeps `other:visible`; `--classes 15` drops it. The export keeps box kinds `leaf` and `content`.

7. **Train** (Modal GPU, see [`training/README.md`](training/README.md)):

   ```sh
   modal deploy labeling/training/train_app.py
   python labeling/training/spawn_train.py start --run-name exp_a --train-list /vol/lists/train.txt \
       --epochs 40 --stage-local --weights yolo11s.pt --gpu A100
   ```

   Training recipe (`training/recipe.py`): YOLO11s, image size 1280, AdamW, seed 0, deterministic. The detector
   runs used 40 epochs, batch 12 and close_mosaic 5, passed as `--overrides` on top of the recipe defaults
   (batch 4, close_mosaic 2). Take the last checkpoint (`last.pt`); do not choose the epoch on the exam set. One run on an A100 40 GB took about 21 minutes for about 2,800 images. The starting point in the
   results was our synthetic base (S50_s, not released). A run from COCO yolo11s is only 0.006–0.01 lower on
   held-out Linux applications (see `results/D1_detector.md` and `results/D2_detector_side.md`).

8. **Evaluate.** Predict on the exam images on CPU, then score against the exam labels:

   ```sh
   python labeling/eval/score.py predict --weights runs/exp_a/weights/last.pt --images work/exam/images \
       --out work/pred.jsonl --device cpu
   python labeling/eval/score.py score --pred work/pred.jsonl --gt work/exam/labels \
       --mode agnostic --conf 0.25 --json work/score_agnostic_025.json
   ```

   Protocol: prediction with image size 1280, NMS IoU 0.7, at most 1,000 detections; every detection with
   confidence at least 0.05 is stored. Matching is IoU ≥ 0.5, greedy one-to-one, sorted by IoU. Scores
   are reported at confidence 0.25 and 0.45 side by side, and in two modes: **class-agnostic** (the class
   is ignored) and **strict** (the class must match). Thresholds are not tuned on the exam set.

## Labelling cost of the released label set

From [`../results/labeling_cost.md`](../results/labeling_cost.md): 3,215 images, 231,604 boxes, 168
applications or sites. API-equivalent cost by role, all billing paths summed: **label $922.40** (3,932 calls),
**QA $98.86** (907 calls), **fix $23.49** (59 calls); **total $1,044.74**. These are API-equivalent prices, not
billed amounts.

## Notes

- The label record format (fields, parent links, crop hashes, validation rules) is documented in the docstring
  of `ulf.py`; the box rules are in `box_convention_v1.md`.
- Records written by an earlier version of `batch.py` carry a stale `prompt` field (`label_rules_gold119.md`).
  The prompt used for those batches was `prompts/label_rules_v1_1.md`; `batch.py` now records that name.
- `eval/score.py` has 15 class names in its per-class table (the same list as the scorer it was taken from);
  check this before comparing per-class numbers with the 16-class export.
