#!/usr/bin/env python
"""Resident `ours` perception server (R3): detector + OCR loaded once, one request at a time.

    <phase1 venv python> -m bench.variants.tree_first.ours_server --display :150      # from experiments/phase6

One server for all displays (socket /tmp/pixeltree_ours.sock, see ours_client.socket_path; --display only labels it). Every request runs
bench.perception.sources.build_tree("ours", png_bytes=...) exactly as the R1 T_ours condition did (no device / thread
arguments, VAX_OBSERVE_DEVICE is not set here), so the tree is the one the R1 agents saw. Protocol: ours_client docstring.
Prints `ready <socket>` on stderr once the models are loaded and the socket listens; removes the socket on exit.
"""
import argparse
import json
import os
import signal
import socket
import struct
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.variants.tree_first.ours_client import recv_exact, socket_path  # noqa: E402


def default_build(png_bytes):
    from bench.perception import sources
    from pixeltree.perceive.tree import to_json

    return to_json(sources.build_tree("ours", png_bytes=png_bytes))


def _send(conn, obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    conn.sendall(struct.pack(">I", len(data)) + data)


class OursServer:
    """Unix-socket server; `build_fn(png_bytes) -> tree json dict` is injectable (tests)."""

    def __init__(self, path, build_fn=None):
        self.path = str(path)
        self.build_fn = build_fn or default_build
        self.sock = None
        self.served = 0
        self._stop = threading.Event()

    def bind(self):
        probe = socket.socket(socket.AF_UNIX)
        try:
            probe.connect(self.path)
            raise RuntimeError(f"already running on {self.path}")
        except OSError:
            pass
        finally:
            probe.close()
        if os.path.exists(self.path):
            os.unlink(self.path)
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(self.path)
        os.chmod(self.path, 0o600)
        self.sock.listen(32)
        self.sock.settimeout(0.5)

    def handle(self, conn):
        conn.settimeout(120)
        try:
            op = recv_exact(conn, 1)
            (n,) = struct.unpack(">I", recv_exact(conn, 4))
            payload = recv_exact(conn, n) if n else b""
            if op == b"P":
                _send(conn, {"ok": True, "pong": True})
            elif op == b"I":
                t = time.time()
                tree = self.build_fn(payload)
                self.served += 1
                _send(conn, {"ok": True, "tree": tree, "server_sec": round(time.time() - t, 3)})
            else:
                _send(conn, {"ok": False, "error": f"bad opcode {op!r}"})
        except Exception as exc:  # noqa: BLE001  (keep serving)
            traceback.print_exc()
            try:
                _send(conn, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            except Exception:  # noqa: BLE001
                pass
        finally:
            conn.close()

    def serve_forever(self):
        """Serve one request at a time until stop()."""
        try:
            while not self._stop.is_set():
                try:
                    conn, _ = self.sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                self.handle(conn)
        finally:
            self.close()

    def start_thread(self):
        self.bind()
        t = threading.Thread(target=self.serve_forever, daemon=True)
        t.start()
        return t

    def stop(self):
        self._stop.set()

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        try:
            os.unlink(self.path)
        except OSError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--display", required=True, help="display the server belongs to, e.g. :150")
    args = ap.parse_args(argv)
    path = socket_path(args.display)
    server = OursServer(path)
    t0 = time.time()
    from pixeltree.perceive import ours

    ours.warmup()
    print(f"models loaded in {time.time() - t0:.1f}s", file=sys.stderr, flush=True)
    server.bind()
    signal.signal(signal.SIGTERM, lambda *_: server.stop())
    signal.signal(signal.SIGINT, lambda *_: server.stop())
    print(f"ready {path}", file=sys.stderr, flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
