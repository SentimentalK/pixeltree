import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from PIL import Image
from starlette.testclient import TestClient

from demo.server import Settings, create_app


def png(w, h, fmt="PNG"):
    buf = BytesIO()
    Image.new("RGB", (w, h), (200, 220, 240)).save(buf, fmt)
    return buf.getvalue()


def fake_result(img):
    return {"elements": [{"id": "e1", "role": "aria:button", "name": "OK", "box": [1, 2, 3, 4],
                          "center": [2, 4], "conf": 0.9}],
            "tree_text": f"screen {img.size[0]}x{img.size[1]}, 1 elements", "timings": {"detect_s": 0.1, "ocr_s": 0.2}}


def make(infer=None, **kw):
    return TestClient(create_app(infer=infer or fake_result, settings=Settings(**kw)))


def post(c, body, **headers):
    return c.post("/api/parse", content=body, headers={"Content-Type": "image/png", **headers})


def test_example_flow():
    seen = []

    def infer(img):
        seen.append(img.size)
        return fake_result(img)

    with make(infer) as c:
        example = c.get("/example.png")
        assert example.status_code == 200
        r = post(c, example.content)
        assert r.status_code == 200
        body = r.json()
        w, h = Image.open(BytesIO(example.content)).size
        assert body["image_size"] == [w, h] == list(seen[0])
        assert body["elements"] == fake_result(Image.new("RGB", (w, h)))["elements"]
        assert body["scaled"] is False


def test_non_images_get_415():
    gif = BytesIO()
    Image.new("RGB", (4, 4)).save(gif, "GIF")
    with make(ip_burst=100) as c:
        assert post(c, b"hello").status_code == 415
        assert post(c, gif.getvalue()).status_code == 415
        r = c.post("/api/parse?filename=a.png", content=b"hello", headers={"Content-Type": "image/png"})
        assert r.status_code == 415 and r.json()["error"] == "unsupported_type"


def test_size_limits():
    with make() as c:
        r = post(c, b"x", **{"Content-Length": str(9 * 1024 * 1024)})
        assert r.status_code == 413
    with make(max_bytes=100) as c:
        r = post(c, png(200, 200))
        assert r.status_code == 413 and r.json()["error"] == "too_large"


def test_pixel_limits():
    with make() as c:
        r = post(c, png(5000, 10))
        assert r.status_code == 413 and r.json()["error"] == "too_many_pixels"
        assert post(c, png(3500, 3500)).status_code == 413


def test_large_image_is_scaled():
    seen = []

    def infer(img):
        seen.append(img.size)
        return fake_result(img)

    with make(infer) as c:
        r = post(c, png(3000, 1500))
        assert r.status_code == 200
        body = r.json()
        assert body["image_size"] == [1920, 960] and body["original_size"] == [3000, 1500]
        assert body["scaled"] and seen == [(1920, 960)]


def test_busy_when_queue_full():
    gate = threading.Event()

    def infer(img):
        gate.wait(10)
        return fake_result(img)

    with make(infer, queue_max=1, ip_burst=100) as c:
        data = png(50, 50)
        with ThreadPoolExecutor(3) as ex:
            f1 = ex.submit(post, c, data)
            f2 = ex.submit(post, c, data)
            time.sleep(0.6)
            f3 = ex.submit(post, c, data)
            r3 = f3.result(5)
            assert r3.status_code == 429 and r3.json()["error"] == "busy"
            gate.set()
            assert f1.result(5).status_code == 200 and f2.result(5).status_code == 200


def test_timeout_does_not_overlap_inference():
    lock = threading.Lock()
    state = {"now": 0, "max": 0, "calls": 0}

    def infer(img):
        with lock:
            state["now"] += 1
            state["calls"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(1.0)
        with lock:
            state["now"] -= 1
        return fake_result(img)

    with make(infer, timeout_s=0.2, ip_burst=100) as c:
        data = png(50, 50)
        assert post(c, data).status_code == 504
        r = post(c, data)
        assert r.status_code in (429, 504)
        time.sleep(2.5)
        assert state["max"] == 1


def test_ip_rate_limit():
    with make(ip_burst=2, ip_rate_per_min=1) as c:
        data = png(50, 50)
        h = {"CF-Connecting-IP": "203.0.113.5"}
        assert post(c, data, **h).status_code == 200
        assert post(c, data, **h).status_code == 200
        r = post(c, data, **h)
        assert r.status_code == 429 and r.json()["error"] == "rate_limited"
        assert int(r.headers["Retry-After"]) >= 1
        assert post(c, data, **{"CF-Connecting-IP": "203.0.113.6"}).status_code == 200


def test_security_headers():
    with make() as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert r.headers["x-content-type-options"] == "nosniff"


def test_healthz_waits_for_load():
    gate = threading.Event()
    with TestClient(create_app(infer=fake_result, settings=Settings(), load=lambda: gate.wait(10))) as c:
        r = c.get("/healthz")
        assert r.status_code == 503 and r.json() == {"ok": False}
        gate.set()
        for _ in range(50):
            r = c.get("/healthz")
            if r.status_code == 200:
                break
            time.sleep(0.05)
        assert r.status_code == 200 and r.json() == {"ok": True}


def test_multipart_upload_gets_415():
    c = make()
    r = c.post("/api/parse", files={"image": ("gitg.png", png(64, 48), "image/png")})
    assert r.status_code == 415
    assert r.json()["error"] == "unsupported_type"
    assert "request body" in r.json()["message"]


def test_foreign_open_error_is_415_not_500(monkeypatch):
    # ultralytics replaces Image.open with a wrapper that raises its own exception type on non-images.
    class Wrapped(Exception):
        pass

    def broken_open(*a, **k):
        raise Wrapped("cannot identify image file")

    monkeypatch.setattr("demo.server.Image.open", broken_open)
    r = post(make(), b"hello")
    assert r.status_code == 415


def test_malformed_requests_are_4xx():
    c = make()
    assert post(c, b"").status_code == 400
    assert c.get("/api/parse").status_code == 405
    assert c.put("/api/parse", content=png(8, 8)).status_code == 405
