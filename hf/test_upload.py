"""hf/upload.py: refuses mismatching weights and uploads nothing in --dry-run (no network, no huggingface_hub)."""
import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("hf_upload", ROOT / "hf" / "upload.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_sums(tmp_path, data):
    w = tmp_path / "pixeltree-detector-v1.pt"
    w.write_bytes(data)
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{hashlib.sha256(data).hexdigest()}  pixeltree-detector-v1.pt\n")
    return w, sums


def test_dry_run_lists_files_and_fills_repo_id(tmp_path, capsys):
    up = load()
    w, sums = write_sums(tmp_path, b"weights")
    assert up.main(["owner/name", "--weights", str(w), "--sha256sums", str(sums), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry run: nothing uploaded" in out and "pixeltree-detector-v1.pt" in out
    card = dict(up.plan("owner/name", w, sums))["README.md"].decode()
    assert "owner/name" in card and "{{REPO_ID}}" not in card
    assert card.startswith("---\nlicense: agpl-3.0")


def test_mismatching_weights_are_refused(tmp_path):
    up = load()
    w, sums = write_sums(tmp_path, b"weights")
    w.write_bytes(b"tampered")
    assert up.main(["owner/name", "--weights", str(w), "--sha256sums", str(sums), "--dry-run"]) == 1
