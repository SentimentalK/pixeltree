"""One entry point for every tree source: build_tree(source, ...) -> Tree.

  ours   screenshot PNG bytes -> detectors + OCR              (needs png_bytes)
  omni   screenshot PNG bytes -> OmniParser through bench/perception/omni.py (needs png_bytes; see OMNI_SETUP.md)
  atspi  AT-SPI node list / dump -> accessibility tree        (needs atspi_nodes, process)
"""
import struct
import time

from pixeltree.perceive.tree import Element, make_tree

SOURCES = ("ours", "omni", "atspi")
DEFAULT_SIZE = (1920, 1080)


class SourceUnavailable(RuntimeError):
    """The requested source cannot run here (module missing, bad arguments)."""


def png_size(png_bytes):
    """(width, height) from the IHDR chunk of PNG bytes; DEFAULT_SIZE when it is not a PNG."""
    if png_bytes and png_bytes[:8] == b"\x89PNG\r\n\x1a\n" and len(png_bytes) >= 24:
        w, h = struct.unpack(">II", png_bytes[16:24])
        return int(w), int(h)
    return DEFAULT_SIZE


def _import_omni():
    try:
        from . import omni
    except ModuleNotFoundError as exc:
        if exc.name == f"{__package__}.omni":
            raise SourceUnavailable(
                "source 'omni' needs bench/perception/omni.py (parse(png_bytes) -> "
                "list[dict(role, name, box, interactable)]) and a running OmniParser server; "
                "see bench/perception/OMNI_SETUP.md.") from exc
        raise
    return omni


def build_omni(png_bytes):
    omni = _import_omni()
    t0 = time.perf_counter()
    items = omni.parse(png_bytes)
    parse_s = time.perf_counter() - t0
    elements = [Element(id="", role=str(it.get("role", "")), name=str(it.get("name", "") or ""),
                        box=[int(v) for v in it["box"]], conf=it.get("conf")) for it in items]
    return make_tree("omni", png_size(png_bytes), elements, {"parse_s": parse_s, "total_s": parse_s})


def build_tree(source, png_bytes=None, atspi_nodes=None, process=None):
    """Tree from `source`; raises SourceUnavailable / ValueError with a clear message when inputs are missing."""
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}; choose from {SOURCES}")
    if source == "atspi":
        if atspi_nodes is None:
            raise ValueError("source 'atspi' needs atspi_nodes (desk.atspi_nodes(process) or a dump file)")
        from . import atspi

        t0 = time.perf_counter()
        tree = atspi.build(atspi_nodes, process, image_size=png_size(png_bytes))
        tree.timings["total_s"] = time.perf_counter() - t0
        return tree
    if png_bytes is None:
        raise ValueError(f"source {source!r} needs png_bytes")
    if source == "omni":
        return build_omni(png_bytes)
    from pixeltree.perceive import ours

    return ours.build(png_bytes)
