# syntax=docker/dockerfile:1.7
#
# Image of the public try-it page (demo/). arm64 is what the hosted page runs on; the file builds for amd64 too.
# Build from the repository root (the context is filtered by demo/Dockerfile.dockerignore):
#
#   docker buildx build --platform linux/arm64 --load -f demo/Dockerfile -t pixeltree-demo:$(git rev-parse --short HEAD) .
#   docker run --rm -p 8080:8080 --read-only --tmpfs /tmp pixeltree-demo:<tag>      # then open http://localhost:8080
#
# The detector weights are downloaded from the v0.1.0 release and checked against weights/SHA256SUMS; the OCR
# models ship inside the rapidocr wheel, so the container needs no network at run time.

FROM python:3.11-slim-bookworm AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PATH=/opt/venv/bin:$PATH
RUN python -m venv /opt/venv
# CPU-only torch (the same versions as the published numbers' environment).
RUN pip install torch==2.15.0 torchvision==0.29.2 --index-url https://download.pytorch.org/whl/cpu
# The `perceive` and `demo` extras of pyproject.toml, listed here so this layer is cached across code changes.
RUN pip install "ultralytics==8.4.182" "rapidocr==3.10.0" "onnx==1.23.2" "onnxruntime==1.31.0" \
        "opencv-python-headless==5.0.0.93" "starlette>=0.40" "uvicorn>=0.30" "Pillow>=10" "numpy>=1.26" \
    # ultralytics pulls the GUI build of OpenCV (needs libGL); keep only the headless one.
    && pip uninstall -y opencv-python \
    && pip install --force-reinstall --no-deps "opencv-python-headless==5.0.0.93"
ADD --chmod=644 --checksum=sha256:0847a507c9ec449915cd04a810d43623cee47507739747bfd3820defad5a3aec \
    https://github.com/SentimentalK/pixeltree/releases/download/v0.1.0/pixeltree-detector-v1.pt \
    /opt/pixeltree/pixeltree-detector-v1.pt

FROM deps AS build
WORKDIR /app
COPY pyproject.toml README.md ./
COPY pixeltree ./pixeltree
RUN pip install --no-deps .
COPY demo ./demo
COPY examples/screenshots/gitg.png ./examples/screenshots/gitg.png
# The OCR models ship inside the rapidocr wheel; fail the build if they are missing. Models are loaded and
# warmed up when the server starts (no inference here: under qemu it takes tens of minutes). Byte-compile
# everything because the root file system is read-only at run time.
RUN python -c "from pixeltree.perceive.ocr import _model_path as m; m('PP-OCRv6_det_small.onnx'); m('PP-OCRv6_rec_small.onnx'); import demo.server" \
    && python -m compileall -q /app/demo \
    # a few third-party files (test fixtures) do not compile; skipping them only costs a slower first import
    && (python -m compileall -q /opt/venv > /dev/null || true)

FROM python:3.11-slim-bookworm
RUN groupadd --gid 10001 pixeltree \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin pixeltree
COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/pixeltree /opt/pixeltree
COPY --from=build /app /app
WORKDIR /app
ENV PATH=/opt/venv/bin:$PATH \
    PIXELTREE_WEIGHTS=/opt/pixeltree/pixeltree-detector-v1.pt \
    PIXELTREE_DEVICE=cpu \
    PIXELTREE_THREADS=3 \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    YOLO_OFFLINE=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    HOME=/tmp \
    TMPDIR=/tmp \
    MALLOC_ARENA_MAX=2 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
EXPOSE 8080
USER 10001:10001
CMD ["python", "-m", "demo.server"]
