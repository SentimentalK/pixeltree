"""Training recipe for the detector (YOLO11s fine-tune on the labelled data).

Extracted from the training driver of the detector project: only the RECIPE dict is kept, because the Modal
training app imports nothing else from it. Data paths, epochs and project names are passed by the caller.
"""

RECIPE = {
    "imgsz": 1280,
    "batch": 4,
    "optimizer": "AdamW",
    "lr0": 0.001,
    "lrf": 0.01,
    "cos_lr": True,
    "warmup_epochs": 3.0,
    "close_mosaic": 2,
    "amp": True,
    "seed": 0,
    "deterministic": True,
    "workers": 6,
    "cache": False,
    "rect": False,
    "patience": 100,
    "multi_scale": 0.0,
    "hsv_h": 0.015,
    "hsv_s": 0.7,
    "hsv_v": 0.4,
    "degrees": 0.0,
    "translate": 0.1,
    "scale": 0.5,
    "fliplr": 0.5,
    "mosaic": 1.0,
    "mixup": 0.0,
    "device": 0,
}
