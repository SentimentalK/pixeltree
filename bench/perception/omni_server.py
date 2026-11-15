#!/usr/bin/env python
"""Resident OmniParser v2 server (screenshot PNG -> element list) on a unix socket.

Run with OmniParser's own venv (NOT the venv the benchmark runs in):

    <omniparser venv>/bin/python bench/perception/omni_server.py

Models load once at start-up (~1 min); requests are served strictly one at a
time (extra clients wait in the listen backlog), so several harness processes
may call `omni.parse()` concurrently.

Protocol (shared with omni.py): request  = 1 opcode byte + uint32 BE length + payload
  b"I" + PNG bytes  -> parse        b"P" + empty -> ping        b"S" + empty -> stats
response = uint32 BE length + JSON utf-8:
  {"ok": true, "elements": [...], "server_sec": float}  |  {"ok": false, "error": str}

Configuration = OmniParser defaults of the OmniTool server (BOX_TRESHOLD 0.05,
EasyOCR text_threshold 0.8, iou 0.7, Florence-2 icon captions); nothing tuned.
"""
import io
import json
import os
import socket
import struct
import sys
import time
import traceback
import types

SOCK = os.environ.get("P125_OMNI_SOCK", "/tmp/pixeltree_omni.sock")
OMNI_HOME = os.environ.get("OMNI_HOME", "./OmniParser")   # checkout of microsoft/OmniParser
BOX_THRESHOLD = 0.05  # OmniTool server default (omniparserserver.py)


def _load_parser():
    sys.path.insert(0, OMNI_HOME)
    os.chdir(OMNI_HOME)
    # util/utils.py builds a PaddleOCR at import time although the default OCR path
    # (use_paddleocr=False) is EasyOCR. Stub it so paddle need not be installed.
    stub = types.ModuleType("paddleocr")
    stub.PaddleOCR = lambda *a, **k: None
    sys.modules.setdefault("paddleocr", stub)
    from util.omniparser import Omniparser  # noqa: E402
    return Omniparser({
        "som_model_path": os.path.join(OMNI_HOME, "weights/icon_detect_v3/model.pt"),
        "caption_model_name": "florence2",
        "caption_model_path": os.path.join(OMNI_HOME, "weights/icon_caption_florence"),
        "BOX_TRESHOLD": BOX_THRESHOLD,
    })


def _to_elements(parsed, w, h):
    out = []
    for e in parsed:
        x1, y1, x2, y2 = e["bbox"]
        X1, Y1 = max(0, round(x1 * w)), max(0, round(y1 * h))
        X2, Y2 = min(w, round(x2 * w)), min(h, round(y2 * h))
        if X2 <= X1 or Y2 <= Y1:
            continue
        out.append({
            "role": "text" if e["type"] == "text" else "icon",
            "name": (e.get("content") or "").strip(),
            "box": [X1, Y1, X2 - X1, Y2 - Y1],
            "interactable": bool(e.get("interactivity")),
        })
    return out


def _recv_exact(conn, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(min(1 << 20, n - len(buf)))
        if not chunk:
            raise ConnectionError("client closed early")
        buf += chunk
    return bytes(buf)


def _send(conn, obj):
    data = json.dumps(obj, ensure_ascii=False).encode()
    conn.sendall(struct.pack(">I", len(data)) + data)


def main():
    import base64  # noqa: F401
    from PIL import Image
    import torch

    # Refuse to start twice.
    probe = socket.socket(socket.AF_UNIX)
    try:
        probe.connect(SOCK)
        print(f"already running on {SOCK}", file=sys.stderr)
        sys.exit(1)
    except OSError:
        pass
    finally:
        probe.close()

    t0 = time.time()
    parser = _load_parser()
    print(f"[omni_server] models loaded in {time.time() - t0:.1f}s", flush=True)

    if os.path.exists(SOCK):
        os.unlink(SOCK)
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(SOCK)
    os.chmod(SOCK, 0o600)
    srv.listen(32)
    print(f"[omni_server] listening on {SOCK}", flush=True)
    served = 0
    while True:
        conn, _ = srv.accept()
        conn.settimeout(120)
        try:
            op = _recv_exact(conn, 1)
            (n,) = struct.unpack(">I", _recv_exact(conn, 4))
            payload = _recv_exact(conn, n) if n else b""
            if op == b"P":
                _send(conn, {"ok": True, "pong": True})
            elif op == b"S":
                _send(conn, {"ok": True, "served": served,
                             "cuda_max_alloc_mb": torch.cuda.max_memory_allocated() / 2**20,
                             "cuda_max_reserved_mb": torch.cuda.max_memory_reserved() / 2**20})
            elif op == b"I":
                t = time.time()
                img = Image.open(io.BytesIO(payload))
                w, h = img.size
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                _, parsed = parser.parse(base64.b64encode(buf.getvalue()).decode())
                served += 1
                _send(conn, {"ok": True, "elements": _to_elements(parsed, w, h),
                             "server_sec": round(time.time() - t, 3)})
            else:
                _send(conn, {"ok": False, "error": f"bad opcode {op!r}"})
        except Exception as e:  # keep serving
            traceback.print_exc()
            try:
                _send(conn, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            except Exception:
                pass
        finally:
            conn.close()


if __name__ == "__main__":
    main()
