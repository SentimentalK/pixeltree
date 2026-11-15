"""Upload the detector to a Hugging Face model repository.

    pip install -e ".[hf]"            # huggingface_hub
    hf auth login                     # once; the token stays in the Hugging Face cache, never in this repository
    python hf/upload.py <owner>/<name> [--weights PATH] [--public] [--dry-run]

What it does:
1. verifies the weight file against weights/SHA256SUMS (refuses to upload a mismatch);
2. checks that a Hugging Face login exists (token from `hf auth login` or the HF_TOKEN environment variable);
3. creates the model repository if needed, **private by default** (`--public` only for a new repository; an existing
   repository keeps its visibility);
4. uploads, in one commit: README.md (hf/README.md with the repository id filled in), the weight file,
   SHA256SUMS and LICENSE.

`--dry-run` does steps 1 and 4's file list only: no network, no login needed.
The token is never read into, printed by, or written to any file by this script; huggingface_hub reads it itself.
"""
import argparse
import hashlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ASSET = "pixeltree-detector-v1.pt"
DEFAULT_WEIGHTS = Path.home() / ".cache" / "pixeltree" / ASSET


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def expected_sha(sums_file, name=ASSET):
    for line in Path(sums_file).read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    raise SystemExit(f"{name} not listed in {sums_file}")


def model_card(repo_id):
    text = (REPO / "hf" / "README.md").read_text(encoding="utf-8")
    return text.replace("{{REPO_ID}}", repo_id).encode("utf-8")


def plan(repo_id, weights, sums_file):
    """(path_in_repo, source) pairs uploaded in one commit."""
    return [
        ("README.md", model_card(repo_id)),
        (ASSET, Path(weights)),
        ("SHA256SUMS", Path(sums_file)),
        ("LICENSE", REPO / "LICENSE"),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo_id", help="Hugging Face model repository, e.g. <owner>/pixeltree-detector")
    ap.add_argument("--weights", type=Path,
                    default=Path(os.environ.get("PIXELTREE_WEIGHTS", DEFAULT_WEIGHTS)),
                    help=f"local weight file (default: $PIXELTREE_WEIGHTS or {DEFAULT_WEIGHTS})")
    ap.add_argument("--sha256sums", type=Path, default=REPO / "weights" / "SHA256SUMS")
    ap.add_argument("--public", action="store_true",
                    help="create a NEW repository as public (default: private; never changes an existing one)")
    ap.add_argument("--dry-run", action="store_true", help="verify and list the files, upload nothing")
    ap.add_argument("--message", default="Upload pixeltree detector v1")
    a = ap.parse_args(argv)

    if "/" not in a.repo_id:
        ap.error("repo_id must look like <owner>/<name>")
    if not a.weights.is_file():
        print(f"weights not found: {a.weights}  (python weights/download.py, or pass --weights)", file=sys.stderr)
        return 1
    want, got = expected_sha(a.sha256sums), sha256(a.weights)
    if got != want:
        print(f"sha256 mismatch for {a.weights}: {got} != {want} (weights/SHA256SUMS); not uploading", file=sys.stderr)
        return 1
    print(f"weights OK: {a.weights} ({got})")

    files = plan(a.repo_id, a.weights, a.sha256sums)
    for path_in_repo, src in files:
        size = len(src) if isinstance(src, bytes) else src.stat().st_size
        print(f"  {path_in_repo:<28} {size:>12,} bytes")
    if a.dry_run:
        print("dry run: nothing uploaded")
        return 0

    from huggingface_hub import CommitOperationAdd, HfApi
    from huggingface_hub.errors import RepositoryNotFoundError

    api = HfApi()
    try:
        user = api.whoami()
    except Exception as exc:  # no token, or an invalid one
        print(f"not logged in to Hugging Face ({exc.__class__.__name__}); run `hf auth login` first", file=sys.stderr)
        return 1
    print(f"logged in as {user.get('name')}")

    try:
        info = api.repo_info(a.repo_id, repo_type="model")
        print(f"repository exists ({'private' if info.private else 'PUBLIC'}); visibility left unchanged")
    except RepositoryNotFoundError:
        api.create_repo(a.repo_id, repo_type="model", private=not a.public)
        print(f"created {a.repo_id} ({'PUBLIC' if a.public else 'private'})")

    ops = [CommitOperationAdd(path_in_repo=p, path_or_fileobj=(src if isinstance(src, bytes) else str(src)))
           for p, src in files]
    commit = api.create_commit(a.repo_id, operations=ops, commit_message=a.message, repo_type="model")
    print(f"uploaded: {commit.commit_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
