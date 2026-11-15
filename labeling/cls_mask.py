"""Per-box class-loss masking for ultralytics detection training.

Boxes whose label class id == nc are "class unknown": they train box regression
and DFL only, never the class loss.  Inference code is untouched.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from ultralytics.utils.tal import TaskAlignedAssigner

UNKNOWN_CLS_DOC = """Convention: a label row whose class id == nc (here 16) means "box is real,
class unknown".  Such rows appear ONLY in train labels; exam / val labels never
contain them.  They get assigned anchors like any gt (box weight preserved) but
contribute zero classification loss.  The nc-class head never learns a 17th class."""

_PATCHED_ATTR = "_cls_mask_wrapped"


def patch_dataset() -> None:
    """Idempotently wrap ultralytics.data.dataset.verify_image_label so labels may use cls == nc."""
    import ultralytics.data.dataset as ds

    orig = ds.verify_image_label
    if getattr(orig, _PATCHED_ATTR, False):
        return

    def wrapped(args: tuple):
        args = list(args)
        args[4] = args[4] + 1  # num_cls: let the id nc pass `max_cls < num_cls`
        return orig(tuple(args))

    setattr(wrapped, _PATCHED_ATTR, True)
    ds.verify_image_label = wrapped


class MaskedAssigner(nn.Module):
    """TaskAlignedAssigner wrapper: runs an (nc+1)-class assigner, folds the extra channel away."""

    def __init__(self, base: TaskAlignedAssigner):
        super().__init__()
        self.nc = base.num_classes
        self.assigner = TaskAlignedAssigner(
            topk=base.topk, num_classes=base.num_classes + 1, alpha=base.alpha, beta=base.beta,
            stride=list(base.stride), eps=base.eps, topk2=base.topk2,
        )
        self.last_unknown: torch.Tensor | None = None
        self._acc: dict[str, torch.Tensor] = {}
        self._batches = 0

    @property
    def stats(self) -> dict[str, float]:
        out = {k: float(v) for k, v in self._acc.items()}
        for k in ("fg_anchors", "unknown_fg_anchors", "unknown_box_weight"):
            out.setdefault(k, 0.0)
        out["batches"] = self._batches
        return out

    @torch.no_grad()
    def forward(self, pd_scores, pd_bboxes, anc_points, gt_labels, gt_bboxes, mask_gt, **kw):
        nc = self.nc
        pd_ext = torch.cat([pd_scores, pd_scores.max(-1, keepdim=True).values], -1)
        labels, bboxes, ts, fg_mask, gt_idx = self.assigner(
            pd_ext, pd_bboxes, anc_points, gt_labels, gt_bboxes, mask_gt, **kw
        )
        if gt_labels.shape[1] == 0:
            unknown = torch.zeros_like(fg_mask)
        else:
            gl = gt_labels.reshape(gt_labels.shape[0], -1)
            unknown = fg_mask & (gl.gather(1, gt_idx.long().clamp(0, gl.shape[1] - 1)) == nc)
        scores = ts[..., :nc].clone()
        scores[..., 0] += ts[..., nc] * unknown.to(ts.dtype)  # keep box weight / score sum
        self.last_unknown = unknown
        for k, v in (
            ("fg_anchors", fg_mask.sum()),
            ("unknown_fg_anchors", unknown.sum()),
            ("unknown_box_weight", ts.sum(-1)[unknown].sum()),
        ):
            self._acc[k] = self._acc.get(k, 0) + v.double()
        self._batches += 1
        return labels, bboxes, scores, fg_mask, gt_idx


class MaskedBCE(nn.Module):
    """BCE-with-logits (reduction none) with the rows of unknown-class anchors zeroed."""

    def __init__(self, assigner: MaskedAssigner):
        super().__init__()
        self.assigner = assigner

    def forward(self, pred, target):
        loss = F.binary_cross_entropy_with_logits(pred, target, reduction="none")
        return loss * (~self.assigner.last_unknown).unsqueeze(-1).to(pred.dtype)


def install(criterion) -> MaskedAssigner:
    """Swap criterion.assigner / criterion.bce for the masked versions; return the MaskedAssigner."""
    if isinstance(criterion.assigner, MaskedAssigner):
        raise RuntimeError("cls_mask already installed on this criterion")
    masked = MaskedAssigner(criterion.assigner)
    criterion.assigner = masked
    criterion.bce = MaskedBCE(masked)
    return masked


def make_callback():
    """Return an `on_train_start` callback that installs the mask into trainer.model's criterion."""

    def on_train_start(trainer):
        crit = trainer.model.init_criterion()
        trainer.cls_mask_assigner = install(crit)
        trainer.model.criterion = crit

    return on_train_start
