"""PP-OCRv6 text reading on ONNX Runtime: a text-line detector, a batched line recogniser and region helpers.

Both ONNX models (`PP-OCRv6_det_small`, `PP-OCRv6_rec_small`) ship inside the `rapidocr` wheel (pinned to 3.10.0).
Everything runs on `CPUExecutionProvider` by default; `provider="cuda"` needs `onnxruntime-gpu`.

* `TextLineDetector` finds axis-aligned text-line boxes in a BGR image.
* `RecReader` recognises line crops. The model graph is extended with ArgMax / ReduceMax outputs so only the CTC
  indices and probabilities leave the session; crops are bucketed by aspect ratio into fixed tensor widths
  (height 48 px) so each batch shares one shape.
* `read_region` crops a UI element, detects its text lines, recognises each line and joins them in reading order
  (used for text-box values).
"""
import math
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

DET_MEAN = 0.5
DET_STD = 0.5
GRID = 32
MIN_SIDE = 8

REC_H = 48
MAX_BUCKET = 1280
FIXED_SHAPES = ((128, 32), (320, 32), (640, 16), (1280, 8))  # (bucket width, batch size)


def _model_path(name):
    import rapidocr

    path = Path(rapidocr.__file__).parent / "models" / name
    if not path.exists():
        raise FileNotFoundError(f"OCR model not found: {path} (install rapidocr==3.10.0)")
    return path


def _providers(provider, device_id):
    if provider == "cpu":
        return ["CPUExecutionProvider"]
    if provider == "cuda":
        import torch  # noqa: F401  loads the CUDA libraries onnxruntime-gpu depends on

        return [("CUDAExecutionProvider", {"device_id": device_id,
                                           "cudnn_conv_algo_search": "HEURISTIC",
                                           "arena_extend_strategy": "kSameAsRequested"}),
                "CPUExecutionProvider"]
    raise ValueError(f"unknown provider {provider!r}; choose 'cuda' or 'cpu'")


def _check_provider(session, provider, what):
    if provider == "cuda" and "CUDAExecutionProvider" not in session.get_providers():
        raise RuntimeError(f"{what} is not running on CUDAExecutionProvider (install onnxruntime-gpu); "
                           "refusing a silent CPU fallback")


# ---------------------------------------------------------------- text-line detector
def _snap_side(value):
    """Round a side length to the nearest multiple of 32, minimum 32."""
    return max(GRID, int(round(float(value) / GRID)) * GRID)


class TextLineDetector:
    def __init__(self, provider="cpu", device_id=0, limit_side=None):
        self.provider = provider
        self.limit_side = limit_side
        self.session = ort.InferenceSession(str(_model_path("PP-OCRv6_det_small.onnx")),
                                            providers=_providers(provider, device_id))
        _check_provider(self.session, provider, "PP-OCRv6 detector")
        self.input_name = self.session.get_inputs()[0].name

        from rapidocr.ch_ppocr_det.utils import DBPostProcess

        self.post = DBPostProcess(thresh=0.3, box_thresh=0.5, max_candidates=1000,
                                  unclip_ratio=1.6, score_mode="fast", use_dilation=True)

    def _resize(self, img_bgr):
        h, w = img_bgr.shape[:2]
        if self.limit_side is not None:
            longer = max(h, w)
            if longer > self.limit_side:
                scale = self.limit_side / float(longer)
                h = max(1, int(round(h * scale)))
                w = max(1, int(round(w * scale)))
        return cv2.resize(img_bgr, (_snap_side(w), _snap_side(h)))

    def detect(self, img_bgr):
        """Detect text lines -> [(axis-aligned [x0, y0, x1, y1] in image pixels, score)]."""
        h, w = img_bgr.shape[:2]
        if h < MIN_SIDE or w < MIN_SIDE:
            return []

        resized = self._resize(img_bgr)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        arr = rgb.astype(np.float32) / 255.0
        arr = (arr - DET_MEAN) / DET_STD
        arr = np.ascontiguousarray(arr.transpose((2, 0, 1))[None, ...])
        pred = self.session.run(None, {self.input_name: arr})[0]

        boxes, scores = self.post(pred, (h, w))
        if boxes is None or len(boxes) == 0:
            return []

        out = []
        for box, score in zip(boxes, scores):
            pts = np.asarray(box, dtype=np.float64).reshape(-1, 2)
            x0 = max(0.0, min(float(pts[:, 0].min()), w))
            y0 = max(0.0, min(float(pts[:, 1].min()), h))
            x1 = max(0.0, min(float(pts[:, 0].max()), w))
            y1 = max(0.0, min(float(pts[:, 1].max()), h))
            if x1 <= x0 or y1 <= y0:
                continue
            out.append(([x0, y0, x1, y1], float(score)))
        out.sort(key=lambda item: ((item[0][1] + item[0][3]) / 2.0, item[0][0]))
        return out

    def warmup(self):
        white = np.full((64, 64, 3), 255, dtype=np.uint8)
        self.detect(white)
        self.detect(white)
        self.detect(np.full((1088, 1920, 3), 255, dtype=np.uint8))


# ---------------------------------------------------------------- line recogniser
def add_argmax_outputs(model_proto):
    """Copy of a recogniser graph whose outputs are the per-step ArgMax index and max probability of its Softmax."""
    import onnx

    proto = onnx.ModelProto()
    proto.CopyFrom(model_proto)
    graph = proto.graph
    out = graph.output[0].name
    producer = next((node for node in graph.node if out in node.output), None)
    if producer is None or producer.op_type != "Softmax":
        raise ValueError(f"expected a Softmax producing {out!r}")
    graph.node.append(onnx.helper.make_node("ArgMax", [out], ["rec_idx"], axis=2, keepdims=0))
    graph.node.append(onnx.helper.make_node("ReduceMax", [out], ["rec_prob"], axes=[2], keepdims=0))
    del graph.output[:]
    graph.output.extend([
        onnx.helper.make_tensor_value_info("rec_idx", onnx.TensorProto.INT64, [None, None]),
        onnx.helper.make_tensor_value_info("rec_prob", onnx.TensorProto.FLOAT, [None, None]),
    ])
    return proto


def ctc_greedy(idx_row, prob_row, chars):
    """Greedy CTC decode of one line -> (text, mean probability of the kept steps)."""
    kept, scores = [], []
    prev = 0
    for t, idx in enumerate(idx_row):
        idx = int(idx)
        if idx != 0 and (t == 0 or idx != prev):
            kept.append(idx)
            scores.append(float(prob_row[t]))
        prev = idx
    text = "".join(chars[idx] for idx in kept)
    return text.strip(), (float(np.mean(scores)) if scores else 0.0)


def bucket_width(h, w):
    target = math.ceil(REC_H * w / max(h, 1))
    for width, _ in FIXED_SHAPES:
        if width >= target:
            return width
    return MAX_BUCKET


def preprocess(crop_bgr, bucket):
    h, w = crop_bgr.shape[:2]
    resized_w = min(bucket, max(1, math.ceil(REC_H * w / h)))
    resized = cv2.resize(crop_bgr, (resized_w, REC_H), interpolation=cv2.INTER_LINEAR)
    arr = resized.astype(np.float32) / 255.0
    arr -= 0.5
    arr /= 0.5
    arr = arr.transpose((2, 0, 1))
    out = np.zeros((3, REC_H, bucket), dtype=np.float32)
    out[:, :, :resized_w] = arr
    return out


def _character_list(session):
    from rapidocr.ch_ppocr_rec.utils import CTCLabelDecode

    raw = session.get_modelmeta().custom_metadata_map["character"].splitlines()
    return list(CTCLabelDecode(character=raw).character)


class RecReader:
    """PP-OCRv6 small line recogniser. `read(crops)` -> [(text, score)] for a list of BGR line crops.

    provider="cpu" (default, fp32, `threads` intra-op threads) or "cuda" (`fp16=True` converts the graph to fp16).
    """

    def __init__(self, provider="cpu", device_id=0, threads=6, fp16=False):
        import onnx

        self.provider = provider
        self.fp16 = fp16
        proto = add_argmax_outputs(onnx.load(str(_model_path("PP-OCRv6_rec_small.onnx"))))
        if fp16:
            from onnxruntime.transformers.float16 import convert_float_to_float16

            proto = convert_float_to_float16(proto, keep_io_types=True)
        serialized = proto.SerializeToString()
        providers = _providers(provider, device_id)

        self._sessions = {}
        chars = None
        for width, batch in FIXED_SHAPES:
            options = ort.SessionOptions()
            if provider == "cpu":
                options.intra_op_num_threads = int(threads)
                options.inter_op_num_threads = 1
                options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            sess = ort.InferenceSession(serialized, sess_options=options, providers=providers)
            _check_provider(sess, provider, "PP-OCRv6 recogniser")
            if chars is None:
                chars = _character_list(sess)
            self._sessions[width] = (sess, sess.get_inputs()[0].name, batch)
        self._chars = chars

    def _run_chunk(self, crops, bucket):
        sess, inp, batch_size = self._sessions[bucket]
        batch = np.zeros((batch_size, 3, REC_H, bucket), dtype=np.float32)
        for k, crop in enumerate(crops):
            batch[k] = preprocess(crop, bucket)
        idx, prob = sess.run(["rec_idx", "rec_prob"], {inp: batch})
        return [ctc_greedy(idx[k], prob[k], self._chars) for k in range(len(crops))]

    def read(self, crops):
        if not crops:
            return []
        out = [None] * len(crops)
        groups = {}
        for i, crop in enumerate(crops):
            h, w = crop.shape[:2]
            if h == 0 or w == 0:
                out[i] = ("", 0.0)
                continue
            groups.setdefault(bucket_width(h, w), []).append(i)
        for bucket in sorted(groups):
            indices = groups[bucket]
            limit = self._sessions[bucket][2]
            for start in range(0, len(indices), limit):
                chunk = indices[start:start + limit]
                lines = self._run_chunk([crops[i] for i in chunk], bucket)
                for i, line in zip(chunk, lines):
                    if not line:
                        out[i] = ("", 0.0)
                    else:
                        text, score = line
                        out[i] = (str(text).strip(), float(score))
        return out

    def warmup(self):
        for width, batch_size in FIXED_SHAPES:
            sess, inp, _ = self._sessions[width]
            batch = np.zeros((batch_size, 3, REC_H, width), dtype=np.float32)
            for _ in range(2):
                sess.run(["rec_idx", "rec_prob"], {inp: batch})
        white = np.full((32, 100, 3), 255, dtype=np.uint8)
        self.read([white])


# ---------------------------------------------------------------- multi-line regions
def group_rows(boxes):
    """Group xyxy boxes into visual rows; returns row index lists, top->bottom, x-sorted inside a row."""
    boxes = np.asarray(boxes, dtype=np.float64).reshape(-1, 4)
    if len(boxes) == 0:
        return []
    heights = boxes[:, 3] - boxes[:, 1]
    centres = (boxes[:, 1] + boxes[:, 3]) / 2.0
    order = sorted(range(len(boxes)), key=lambda i: (centres[i], boxes[i, 0], i))

    rows = []
    for i in order:
        if rows:
            row = rows[-1]
            row_top = min(boxes[j, 1] for j in row)
            row_bottom = max(boxes[j, 3] for j in row)
            row_height = row_bottom - row_top
            overlap = min(boxes[i, 3], row_bottom) - max(boxes[i, 1], row_top)
            if overlap >= 0.5 * min(heights[i], row_height):
                row.append(i)
                continue
        rows.append([i])

    for row in rows:
        row.sort(key=lambda i: (boxes[i, 0], i))
    return rows


def join_lines(boxes, texts):
    """Join recognised per-line texts into reading order: one space inside a row, newline between rows."""
    boxes = list(boxes)
    texts = list(texts)
    kept = [i for i in range(min(len(boxes), len(texts)))
            if texts[i] is not None and str(texts[i]).strip()]
    if not kept:
        return ""
    kept_boxes = [boxes[i] for i in kept]
    rows = group_rows(kept_boxes)
    lines = [" ".join(str(texts[kept[j]]).strip() for j in row) for row in rows]
    return "\n".join(lines)


def read_region(detector, reader, img_bgr, box_xyxy, pad=2, min_score=0.5):
    """Crop a UI region, OCR its text lines and join them; None when the crop is too small."""
    H, W = img_bgr.shape[:2]
    x0 = max(0, int(np.floor(float(box_xyxy[0]))) - pad)
    y0 = max(0, int(np.floor(float(box_xyxy[1]))) - pad)
    x1 = min(W, int(np.ceil(float(box_xyxy[2]))) + pad)
    y1 = min(H, int(np.ceil(float(box_xyxy[3]))) + pad)
    if x1 - x0 < MIN_SIDE or y1 - y0 < MIN_SIDE:
        return None

    crop = img_bgr[y0:y1, x0:x1]
    ch, cw = crop.shape[:2]
    line_boxes, line_crops = [], []
    for box, _score in detector.detect(crop):
        lx0 = max(0, int(np.floor(box[0])) - 1)
        ly0 = max(0, int(np.floor(box[1])) - 1)
        lx1 = min(cw, int(np.ceil(box[2])) + 1)
        ly1 = min(ch, int(np.ceil(box[3])) + 1)
        if lx1 - lx0 < 1 or ly1 - ly0 < 1:
            continue
        line_boxes.append([lx0, ly0, lx1, ly1])
        line_crops.append(crop[ly0:ly1, lx0:lx1])

    if not line_crops:
        return ""
    results = reader.read(line_crops) or []
    kept_boxes, kept_texts = [], []
    for box, res in zip(line_boxes, results):
        if not res:
            continue
        text, score = res
        text = str(text).strip()
        if not text or float(score) < min_score:
            continue
        kept_boxes.append(box)
        kept_texts.append(text)
    return join_lines(kept_boxes, kept_texts)
