import json
import os
import re
import shutil

import pytest

from pixeltree.viewer import build as B
from pixeltree.viewer.__main__ import main

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "examples", "episodes")
EXAMPLE_ID = "r5__deepseek__gitg_stage_readme__T_ours__r0"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("traces")
    shutil.copytree(os.path.join(EXAMPLES, EXAMPLE_ID), str(root / EXAMPLE_ID))
    out = tmp_path_factory.mktemp("site")
    assert main(["build", "--traces", str(root), "--out", str(out), "--jobs", "1"]) == 0
    return str(out)


def _read(site, rel):
    with open(os.path.join(site, rel), encoding="utf-8") as f:
        return f.read()


def test_pages_are_generated_and_in_english(site):
    index = _read(site, "index.html")
    assert 'href="ep/%s.html"' % EXAMPLE_ID in index
    assert 'href="task/gitg_stage_readme.html"' in index
    assert not re.search("[\\u4e00-\\u9fff]", index)
    ep = _read(site, "ep/%s.html" % EXAMPLE_ID)
    data = json.loads(re.search(r"window\.PT = (.*?);</script>", ep, re.S).group(1))
    assert data["id"] == EXAMPLE_ID and len(data["steps"]) == 18
    assert data["result"]["ok"] is True
    assert os.path.exists(os.path.join(site, "task", "gitg_stage_readme.html"))


def test_every_image_an_episode_page_references_exists(site):
    ep = _read(site, "ep/%s.html" % EXAMPLE_ID)
    data = json.loads(re.search(r"window\.PT = (.*?);</script>", ep, re.S).group(1))
    img_dir = os.path.normpath(os.path.join(site, "ep", data["img"]))
    n = 0
    for s in data["steps"]:
        if s["has_screen"]:
            assert os.path.getsize(os.path.join(img_dir, s["nn"] + ".webp")) > 0
            n += 1
        if s["has_a"]:
            assert os.path.exists(os.path.join(img_dir, s["nn"] + "_a.webp"))
    assert n == 18
    task = _read(site, "task/gitg_stage_readme.html")
    for src in re.findall(r'src="\.\./(img/[^"]+)"', task):
        assert os.path.exists(os.path.join(site, src))


def test_site_trace_is_self_contained(site):
    d = os.path.join(site, "traces", EXAMPLE_ID)
    with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    assert "path" not in meta["source"]
    with open(os.path.join(d, "steps.jsonl"), encoding="utf-8") as f:
        first = json.loads(f.readline())
    assert os.path.exists(os.path.normpath(os.path.join(d, first["screen"])))


def test_build_is_deterministic(tmp_path):
    root = tmp_path / "t"
    shutil.copytree(os.path.join(EXAMPLES, EXAMPLE_ID), str(root / EXAMPLE_ID))
    outs = []
    for k in range(2):
        out = tmp_path / ("site%d" % k)
        main(["build", "--traces", str(root), "--out", str(out), "--jobs", "1"])
        outs.append(out)
    for rel in ("index.html", "ep/%s.html" % EXAMPLE_ID, "task/gitg_stage_readme.html"):
        assert (outs[0] / rel).read_bytes() == (outs[1] / rel).read_bytes()


def test_same_model_under_two_shells_gets_two_columns(tmp_path):
    root = tmp_path / "t"
    root.mkdir()
    for ep in ("r1__haiku__gitg_commit_readme__S_shot__r0", "r5__haiku__gitg_commit_readme__S_shot__r0"):
        shutil.copytree(os.path.join(EXAMPLES, ep), str(root / ep))
    traces = B.load_trace_dir(str(root))
    layout = B.matrix_layout(traces)
    assert len(layout["models"]) == 2
    assert sorted(layout["names"].values()) == ["Claude Haiku 5.5 · OMP", "Claude Haiku 5.5 · claude -p"]


def test_running_episode_is_skipped(tmp_path):
    root = tmp_path / "t"
    root.mkdir()
    shutil.copytree(os.path.join(EXAMPLES, EXAMPLE_ID), str(root / EXAMPLE_ID))
    os.remove(root / EXAMPLE_ID / "result.json")
    msgs = []
    assert B.load_trace_dir(str(root), log=msgs.append) == []
    assert "no result.json" in msgs[0]


def test_export_renames_ids_and_drops_archive_paths(tmp_path):
    from pixeltree.trace import adapters as A
    from pixeltree.viewer.export import export_trace, public_id
    fx = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(os.path.join(fx, "w2c", "episodes_v1_1.jsonl"), encoding="utf-8") as f:
        row = json.loads(f.readline())
    row["dir"] = os.path.join(fx, row["dir"])
    t = A.build_trace({"source": "w2c", "dir": row["dir"], "row": row, "tasks": {}})
    assert public_id(t["meta"]["id"]) == "r5__deepseek__gitg_stage_readme__H_ours__r0"
    new_id = export_trace(t, str(tmp_path))
    d = tmp_path / new_id
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["source"] == {"kind": "r5"} and meta["id"] == new_id
    text = "".join((d / n).read_text(encoding="utf-8") for n in ("meta.json", "steps.jsonl", "result.json"))
    assert str(fx) not in text and "/hom" + "e/" not in text
    steps = [json.loads(l) for l in (d / "steps.jsonl").read_text(encoding="utf-8").splitlines()]
    assert steps[1]["screen"] == "img/02.webp" and steps[1]["observation"]["image"] == "img/02_a.webp"
    from PIL import Image
    with Image.open(d / "img" / "02.webp") as im:
        assert im.size == (1280, 720) and im.format == "WEBP"
    # the exported directory is itself a valid input for the site build
    out = tmp_path / "site"
    assert main(["build", "--traces", str(tmp_path), "--out", str(out), "--jobs", "1"]) == 0
    assert (out / "ep" / (new_id + ".html")).exists()
