"""The packaged perception against the trees archived by the main experiment.

For 30 archived steps (tests/data/equivalence_steps.txt, 8 desktop applications) the tree is built from the archived
screenshot and compared with the archived `obs.txt` / `tree.json`.

* device 0 (GPU): the archived trees were produced on a GPU (fp16 detector and recogniser), so all 30 tree texts must
  be identical, line for line. Skipped when CUDA (or onnxruntime-gpu) is absent.
* device "cpu" (the package default, fp32): numbers differ slightly from the GPU ones, so nothing is asserted; the
  agreement statistics are printed.

Needs the archive and the weights; skips (as in CI) when any is missing:

    PIXELTREE_ARCHIVE=<dir with <episode>/steps/NN/{screen.png,obs.txt,tree.json}> \\
    PIXELTREE_WEIGHTS=<pixeltree-detector-v1.pt> \\
        python -m pytest tests/test_perceive_equivalence.py -q -s
"""
import json
import os
import statistics
from pathlib import Path

import pytest

STEPS_FILE = Path(__file__).resolve().parent / "data" / "equivalence_steps.txt"


def _setup(device):
    archive = os.environ.get("PIXELTREE_ARCHIVE")
    if not archive or not Path(archive).is_dir():
        pytest.skip("PIXELTREE_ARCHIVE is not set to an archive directory")
    for module in ("ultralytics", "rapidocr", "onnxruntime", "cv2"):
        pytest.importorskip(module)
    if device != "cpu":
        import onnxruntime
        import torch

        if not torch.cuda.is_available() or "CUDAExecutionProvider" not in onnxruntime.get_available_providers():
            pytest.skip("CUDA with onnxruntime-gpu is not available")
    from pixeltree.perceive import ours

    try:
        ours.resolve_weights()
    except FileNotFoundError as exc:
        pytest.skip(str(exc).splitlines()[0])
    steps = [s for s in STEPS_FILE.read_text(encoding="utf-8").split() if s]
    assert len(steps) == 30
    return Path(archive), steps, ours


def _iou(a, b):
    iw = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    ih = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return iw * ih / (a[2] * a[3] + b[2] * b[3] - iw * ih)


def _agreement(new_elements, old_elements):
    """(share of archived elements matched with an identical name, max coordinate shifts of the matches)."""
    used, same_name, shifts = set(), 0, []
    for old in old_elements:
        best, best_iou = None, 0.5
        for k, new in enumerate(new_elements):
            if k in used or new.role != old["role"]:
                continue
            iou = _iou(old["box"], new.box)
            if iou > best_iou:
                best, best_iou = k, iou
        if best is not None:
            used.add(best)
            same_name += new_elements[best].name == old["name"]
            shifts.append(max(abs(a - b) for a, b in zip(old["box"], new_elements[best].box)))
    return same_name / max(1, len(old_elements)), shifts


@pytest.mark.parametrize("device", ["cpu", 0], ids=["cpu", "gpu"])
def test_trees_against_the_archive(device):
    archive, steps, ours = _setup(device)
    from pixeltree.perceive.tree import to_text

    identical, same_count, shares, shifts = 0, 0, [], []
    for step in steps:
        tree = ours.build((archive / step / "screen.png").read_bytes(), device=device)
        new = to_text(tree).split("\n")
        old = (archive / step / "obs.txt").read_text(encoding="utf-8").split("\n")
        n_diff = sum(a != b for a, b in zip(new, old)) + abs(len(new) - len(old))
        identical += n_diff == 0
        if n_diff:
            print(f"differs: {step}: {n_diff} of {len(old)} lines")
        archived = json.loads((archive / step / "tree.json").read_text(encoding="utf-8"))["elements"]
        same_count += len(archived) == len(tree.elements)
        share, step_shifts = _agreement(tree.elements, archived)
        shares.append(share)
        shifts += step_shifts
    shifts.sort()
    print(f"device {device}: identical steps {identical} of {len(steps)}; same element count {same_count}; "
          f"median share of elements with identical name {statistics.median(shares):.2f}; "
          f"box shift median {statistics.median(shifts)} px, p95 {shifts[int(0.95 * len(shifts))]} px")
    if device != "cpu":
        assert identical == len(steps)
