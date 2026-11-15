# Training on Modal (reference)

These scripts train the detector on a rented GPU through [Modal](https://modal.com). They are a reference
for the setup; the account, workspace and volume names are placeholders, and a Modal account of your own is
needed. Nothing here contains credentials; Modal reads its own configuration.

Names used throughout:

- Volume: `pixeltree-data` (images, labels, weights and run outputs; mounted at `/vol` in the container).
- Deployed app: `pixeltree-train` (the default of `PIXELTREE_APP_NAME`).
- Training recipe: `recipe.py` (`RECIPE`). Overrides are passed per run with `--overrides`.

## 1. Prepare a local mirror

`build_manifest.py` scans a local mirror with `train/` and `val/` folders (`images/`, `labels/`) and
writes the upload manifests. Symlinks are resolved, so the real files are uploaded.

```sh
export PIXELTREE_MIRROR=data/mirror                     # folder with train/ and val/
export PIXELTREE_BASE_WEIGHTS=weights/yolo11s.pt        # starting checkpoint
python labeling/training/build_manifest.py out/modal
```

## 2. Upload

```sh
python labeling/training/upload.py --what weights       # base checkpoint -> /weights/
python labeling/training/upload.py --what labels        # labels -> /train, /val
python labeling/training/upload.py --what images        # images -> /train, /val
```

Upload is resumable: names already on the Volume are skipped. A file that is already on the Volume can be
copied inside the Volume with the `vol_copy` function of `train_app.py` instead of uploading it again.

To name a set of training images, give `make_list.py` a local directory of images or a text file of local
image paths. The labels must already be on the Volume, next to the images (`images/` -> `labels/`):

```sh
python labeling/training/make_list.py exp_a out/modal/train_images.txt --prefix /vol/train/images --upload
```

The list becomes `/vol/lists/exp_a.txt`.

## 3. Deploy the training app

```sh
modal deploy labeling/training/train_app.py             # once, and again after each change
```

## 4. Start, check and cancel runs

`spawn_train.py` starts a run as a Modal function call, so the local client can exit while the run continues.

```sh
python labeling/training/spawn_train.py start --run-name exp_a --train-list /vol/lists/exp_a.txt \
    --epochs 40 --gpu A100 --stage-local --weights yolo11s.pt \
    --overrides '{"batch": 12, "close_mosaic": 5}'
python labeling/training/spawn_train.py status --call-id <call id>
python labeling/training/spawn_train.py cancel --call-id <call id>
```

`--stage-local` copies the training images to the container disk before training; this avoids reading the
Volume during training. Outputs go to `/vol/runs/<run-name>`, including `last.pt`, `timing.json` and `gpu_util.csv`.
Runs are restartable: a run with `weights/last.pt` and no `DONE` file resumes.

## 5. Data split for export

`prep_split.py` creates the internal validation split (about 5 % of each application group, used only to
read training curves) and the held-out files used by `export_yolo.py`. See the labeling README for the
order of steps.

## Reference numbers

From `results/D1_detector.md`: one run of 2,782 images on an A100 40 GB took about 21 minutes (the
synthetic-base run) and about 22 minutes (COCO start); the run with twice the data took about 42 minutes.
