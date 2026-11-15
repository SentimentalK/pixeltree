"""OmniParser v2 baseline tree source: screenshot PNG -> element list.

    from bench.perception.omni import parse
    elements = parse(png_bytes)   # [{"role": "text"|"icon", "name": str,
                                  #   "box": [x, y, w, h], "interactable": bool}, ...]

Pixel coordinates of the input image (1920x1080 expected). Talks to the resident
server (omni_server.py, OmniParser's own venv) over a unix socket; stdlib only,
so any venv can import this. Setup: see OMNI_SETUP.md.
"""
import json
import os
import socket
import struct

SOCK = os.environ.get("P125_OMNI_SOCK", "/tmp/pixeltree_omni.sock")
START_CMD = (os.environ.get("OMNI_PYTHON", "<omniparser venv>/bin/python") + " bench/perception/omni_server.py   "
             "# run from the repo root; loads models in ~1 min, wait for 'listening'")
TIMEOUT = float(os.environ.get("P125_OMNI_TIMEOUT", "600"))  # queueing behind other clients included


class OmniServerDown(RuntimeError):
    pass


def _call(op: bytes, payload: bytes = b"", timeout: float = TIMEOUT) -> dict:
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    try:
        try:
            s.connect(SOCK)
        except OSError as e:
            raise OmniServerDown(
                f"OmniParser server not reachable at {SOCK} ({e}). Start it with:\n  {START_CMD}") from e
        s.sendall(op + struct.pack(">I", len(payload)) + payload)
        head = _recv_exact(s, 4)
        (n,) = struct.unpack(">I", head)
        return json.loads(_recv_exact(s, n))
    finally:
        s.close()


def _recv_exact(s, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = s.recv(min(1 << 20, n - len(buf)))
        if not chunk:
            raise ConnectionError("OmniParser server closed the connection")
        buf += chunk
    return bytes(buf)


def parse(png_bytes: bytes) -> list:
    r = _call(b"I", png_bytes)
    if not r.get("ok"):
        raise RuntimeError(f"OmniParser server error: {r.get('error')}")
    return r["elements"]


def ping() -> bool:
    return bool(_call(b"P", timeout=10).get("pong"))


def stats() -> dict:
    return _call(b"S", timeout=30)
