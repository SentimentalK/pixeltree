"""Leaf element detector: a YOLO model that finds every visible UI element on a whole screenshot.

The detector class names are the element roles of the tree (16 classes: 15 ARIA-style leaf roles such as
`aria:button`, `aria:textbox`, `vax:visibleText`, plus `other:visible`). Detection runs on the whole image at
`imgsz` (no tiling) with a fixed NMS IoU of 0.7 and at most 1000 boxes.
"""
import numpy as np

IMGSZ = 1280
KEEP_CONF = 0.25
NMS_IOU = 0.7
MAX_DET = 1000


class LeafDetector:
    """`predict(img_bgr)` -> (xyxy float64 [n, 4], confidence [n], class index [n]); `names` maps index -> role."""

    def __init__(self, weights, device="cpu", imgsz=IMGSZ, conf=KEEP_CONF, threads=6):
        from ultralytics import YOLO

        self.imgsz = imgsz
        self.conf = conf
        self.device = device
        self.cpu = device == "cpu"
        self.half = not self.cpu
        self.threads = int(threads)
        if self.cpu:
            import torch

            torch.set_num_threads(self.threads)
        self.model = YOLO(str(weights))
        self.names = dict(self.model.names)
        black = np.zeros((64, 64, 3), dtype=np.uint8)
        self.model.predict(source=black, imgsz=64, conf=conf, verbose=False, **self._opts())
        if self.cpu:
            import torch

            torch.set_num_threads(self.threads)  # the first CPU predict resets the torch thread count

    def _opts(self):
        # `half` is only passed on CUDA: ultralytics 8.4 prints a deprecation warning for any `half` argument.
        return {"device": self.device, "half": True} if self.half else {"device": self.device}

    def predict(self, img_bgr):
        r = self.model.predict(source=img_bgr, imgsz=self.imgsz, conf=self.conf, iou=NMS_IOU, max_det=MAX_DET,
                               verbose=False, **self._opts())[0]
        return (r.boxes.xyxy.cpu().numpy().astype(np.float64),
                r.boxes.conf.cpu().numpy().astype(np.float64),
                r.boxes.cls.cpu().numpy().astype(int))
