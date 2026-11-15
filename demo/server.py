"""Public demo: upload a screenshot, get detected boxes and the element tree.

    python -m demo.server        # PORT (default 8080), HOST (default 0.0.0.0)

Images are decoded and processed in memory only; nothing is written to disk and no image bytes, element
names, tree text, IP addresses or request headers are logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

Image.MAX_IMAGE_PIXELS = 12_000_000

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
log = logging.getLogger("pixeltree.demo")

CSP = ("default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
FORMATS = {"PNG", "JPEG", "WEBP"}


@dataclass
class Settings:
    max_bytes: int = 8 * 1024 * 1024
    max_side: int = 4096
    max_pixels: int = 12_000_000
    infer_side: int = 1920
    queue_max: int = 3
    timeout_s: float = 30.0
    ip_rate_per_min: float = 6
    ip_burst: int = 3
    example_path: Path = ROOT / "examples" / "screenshots" / "gitg.png"

    @classmethod
    def from_env(cls):
        s = cls()
        env = os.environ
        if "PIXELTREE_DEMO_MAX_BYTES" in env:
            s.max_bytes = int(env["PIXELTREE_DEMO_MAX_BYTES"])
        if "PIXELTREE_DEMO_QUEUE_MAX" in env:
            s.queue_max = int(env["PIXELTREE_DEMO_QUEUE_MAX"])
        if "PIXELTREE_DEMO_TIMEOUT_S" in env:
            s.timeout_s = float(env["PIXELTREE_DEMO_TIMEOUT_S"])
        if "PIXELTREE_DEMO_IP_RATE_PER_MIN" in env:
            s.ip_rate_per_min = float(env["PIXELTREE_DEMO_IP_RATE_PER_MIN"])
        if "PIXELTREE_DEMO_IP_BURST" in env:
            s.ip_burst = int(env["PIXELTREE_DEMO_IP_BURST"])
        return s


class ApiError(Exception):
    def __init__(self, status, code, message, headers=None):
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def _err(status, code, message, headers=None):
    return JSONResponse({"error": code, "message": message}, status_code=status, headers=headers)


class RateLimiter:
    """Token bucket per client key."""

    def __init__(self, burst, per_min):
        self.burst, self.rate = burst, per_min / 60.0
        self.state = {}  # key -> [tokens, last_update, last_seen]

    def take(self, key, now=None):
        """Returns 0 if allowed, else seconds until the next token."""
        now = time.monotonic() if now is None else now
        if len(self.state) > 10000:
            self.state = {k: v for k, v in self.state.items() if now - v[2] < 600}
        tokens, last, _ = self.state.get(key, (float(self.burst), now, now))
        tokens = min(float(self.burst), tokens + (now - last) * self.rate)
        if tokens >= 1:
            self.state[key] = [tokens - 1, now, now]
            return 0
        self.state[key] = [tokens, now, now]
        return max(1, math.ceil((1 - tokens) / self.rate)) if self.rate > 0 else 3600


def _decode(body, s):
    """Bytes -> RGB PIL image sized for inference, or ApiError. Runs in a worker thread."""
    too_many = ApiError(413, "too_many_pixels", f"Image is too large; max {s.max_side}px per side and "
                        f"{s.max_pixels // 1_000_000} megapixels.")
    try:
        img = Image.open(BytesIO(body))
    except Image.DecompressionBombError:
        raise too_many
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise ApiError(415, "unsupported_type", "Only PNG, JPEG and WebP images are supported.")
    if img.format not in FORMATS:
        raise ApiError(415, "unsupported_type", "Only PNG, JPEG and WebP images are supported.")
    w, h = img.size
    if max(w, h) > s.max_side or w * h > s.max_pixels:
        raise too_many
    try:
        img.load()
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Image.DecompressionBombError:
        raise too_many
    except Exception:
        raise ApiError(400, "invalid_image", "The image could not be decoded.")
    w0, h0 = img.size
    if max(w0, h0) > s.max_side or w0 * h0 > s.max_pixels:
        raise too_many
    if max(w0, h0) > s.infer_side:
        k = s.infer_side / max(w0, h0)
        img = img.resize((max(1, round(w0 * k)), max(1, round(h0 * k))), Image.LANCZOS)
    return img, (w0, h0)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        h = response.headers
        h["Content-Security-Policy"] = CSP
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/api/parse":
            h["Cache-Control"] = "no-store"
        line = (f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {request.method} "
                f"{request.url.path} {response.status_code} {(time.perf_counter() - t0) * 1000:.0f}ms")
        size = getattr(request.state, "log_size", None)
        if size and response.status_code == 200:
            line += f" {size}"
        log.info(line)
        return response


def create_app(infer=None, settings=None, load=None):
    s = settings or Settings()
    if infer is None:
        from demo import engine

        infer = engine.infer
        load = load or engine.load
    ready = threading.Event()
    limiter = RateLimiter(s.ip_burst, s.ip_rate_per_min)
    pool = ThreadPoolExecutor(max_workers=1)  # inference
    decode_pool = ThreadPoolExecutor(max_workers=2)
    state = {"admitted": 0, "sem": None}

    @contextlib.asynccontextmanager
    async def lifespan(app):
        state["sem"] = asyncio.Semaphore(1)
        if load is None:
            ready.set()
        else:
            def run():
                load()
                ready.set()
            threading.Thread(target=run, daemon=True).start()
        yield

    async def healthz(request):
        if ready.is_set():
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": False}, status_code=503)

    async def index(request):
        return FileResponse(STATIC / "index.html")

    async def example(request):
        return FileResponse(s.example_path, media_type="image/png")

    async def parse(request):
        t0 = time.perf_counter()
        loop = asyncio.get_running_loop()
        try:
            cf = (request.headers.get("cf-connecting-ip") or "").strip()
            ip = cf or (request.client.host if request.client else "unknown")
            wait = limiter.take(ip)
            if wait:
                raise ApiError(429, "rate_limited", "Too many requests; try again later.",
                               {"Retry-After": str(wait)})
            # Admission first: at most 1 running + queue_max waiting requests may hold a body in memory.
            if state["admitted"] >= 1 + s.queue_max:
                raise ApiError(429, "busy", "The server is busy; try again in a few seconds.",
                               {"Retry-After": "10"})
            state["admitted"] += 1
            deadline = loop.time() + s.timeout_s
            sem = state["sem"]
            phase = "queued"

            def release():
                state["admitted"] -= 1
                sem.release()

            try:
                cl = request.headers.get("content-length")
                if cl and cl.isdigit() and int(cl) > s.max_bytes:
                    raise ApiError(413, "too_large", f"File is too large; max {s.max_bytes // (1024 * 1024)} MB.")
                chunks, total = [], 0
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > s.max_bytes:
                        raise ApiError(413, "too_large",
                                       f"File is too large; max {s.max_bytes // (1024 * 1024)} MB.")
                    chunks.append(chunk)
                if not total:
                    raise ApiError(400, "empty", "The request body is empty.")
                body = b"".join(chunks)
                del chunks
                img, (w0, h0) = await loop.run_in_executor(decode_pool, _decode, body, s)
                del body
                W, H = img.size
                try:
                    await asyncio.wait_for(sem.acquire(), max(0.0, deadline - loop.time()))
                except asyncio.TimeoutError:
                    raise ApiError(504, "timeout", "Parsing timed out; try a smaller image.")
                phase = "acquired"
                fut = loop.run_in_executor(pool, infer, img)
                # The slot is freed only when the thread really finishes, even if we stop waiting.
                fut.add_done_callback(lambda f: loop.call_soon_threadsafe(release))
                phase = "running"
                try:
                    result = await asyncio.wait_for(asyncio.shield(fut), max(0.0, deadline - loop.time()))
                except asyncio.TimeoutError:
                    fut.add_done_callback(lambda f: f.cancelled() or f.exception())
                    raise ApiError(504, "timeout", "Parsing timed out; try a smaller image.")
                except Exception:
                    raise ApiError(500, "internal", "inference failed")
            except BaseException:
                if phase == "queued":
                    state["admitted"] -= 1
                elif phase == "acquired":
                    release()
                raise
            request.state.log_size = f"{W}x{H}"
            return JSONResponse({"elements": result["elements"], "tree_text": result["tree_text"],
                                 "image_size": [W, H], "original_size": [w0, h0],
                                 "scaled": (W, H) != (w0, h0), "timings": result["timings"],
                                 "elapsed_s": round(time.perf_counter() - t0, 3)})
        except ApiError as e:
            return _err(e.status, e.code, e.message, e.headers)

    routes = [
        Route("/", index),
        Route("/healthz", healthz),
        Route("/example.png", example),
        Route("/api/parse", parse, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
    return Starlette(routes=routes, lifespan=lifespan, middleware=[Middleware(SecurityHeaders)])


def main():
    import uvicorn

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    app = create_app(settings=Settings.from_env())
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8080")),
                access_log=False, proxy_headers=False, server_header=False, log_level="warning")


if __name__ == "__main__":
    main()
