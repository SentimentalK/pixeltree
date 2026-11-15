"""Client of the resident ours perception server (bench.variants.tree_first.ours_server): PNG bytes -> tree json dict.

Protocol (as bench/perception/omni_server.py): request = 1 opcode byte + uint32 BE length + payload,
b"I" + PNG -> {"ok": true, "tree": <pixeltree.perceive.tree.to_json>, "server_sec": float}, b"P" -> ping;
response = uint32 BE length + JSON utf-8; errors are {"ok": false, "error": str}.
"""
import json
import socket
import struct
import time


class OursServerUnavailable(RuntimeError):
    """The ours perception server of a display does not answer (not started, crashed)."""


# ONE server for all displays. Each server holds ~2.3 GB of GPU memory (detector + OCR on the 6 GB card),
# so a third per-display server fails to load (onnxruntime "Failed to allocate memory"); requests from the 3
# parallel episodes queue on the one server (t_obs_s includes that wait). `display` is kept for the call signature.
SOCKET = "/tmp/pixeltree_ours.sock"


def socket_path(display=None):
    return SOCKET


def recv_exact(conn, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(min(1 << 20, n - len(buf)))
        if not chunk:
            raise ConnectionError("peer closed early")
        buf += chunk
    return bytes(buf)


def send_request(conn, op, payload=b""):
    conn.sendall(op + struct.pack(">I", len(payload)) + payload)


def _connect(path, connect_timeout_s):
    deadline = time.monotonic() + connect_timeout_s
    last = None
    while True:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(5)
        try:
            s.connect(path)
            return s
        except OSError as exc:
            last = exc
            s.close()
        if time.monotonic() >= deadline:
            raise OursServerUnavailable(f"ours server {path} not reachable within {connect_timeout_s}s: {last}")
        time.sleep(0.25)


def _call(display, op, payload, connect_timeout_s, read_timeout_s):
    path = socket_path(display)
    conn = _connect(path, connect_timeout_s)
    try:
        conn.settimeout(read_timeout_s)
        send_request(conn, op, payload)
        (n,) = struct.unpack(">I", recv_exact(conn, 4))
        return json.loads(recv_exact(conn, n).decode("utf-8"))
    except (OSError, ConnectionError, ValueError) as exc:
        raise OursServerUnavailable(f"ours server {path}: {type(exc).__name__}: {exc}") from exc
    finally:
        conn.close()


def build_tree_json(png_bytes, display, connect_timeout_s=60, read_timeout_s=180):
    """Tree json dict of a PNG screenshot; OursServerUnavailable when the server of `display` cannot be reached."""
    res = _call(display, b"I", png_bytes, connect_timeout_s, read_timeout_s)
    if not res.get("ok"):
        raise RuntimeError(f"ours server error: {res.get('error')}")
    return res["tree"]


def ping(display, connect_timeout_s=5):
    return bool(_call(display, b"P", b"", connect_timeout_s, 10).get("ok"))
