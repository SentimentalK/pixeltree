"""Screenshot -> element tree.

`tree` is pure Python; `build` / `warmup` (the model stack: ultralytics, rapidocr, onnxruntime, OpenCV) are imported
on first use, so `import pixeltree.perceive` works without the `perceive` extra.
"""
from .tree import MAX_LINES, Element, Tree, make_tree, order, to_json, to_text

__all__ = ["Element", "Tree", "MAX_LINES", "make_tree", "order", "to_json", "to_text", "build", "warmup"]


def __getattr__(name):
    if name in ("build", "warmup"):
        from . import ours

        return getattr(ours, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
