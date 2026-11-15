import importlib.util
import io
import os
import tarfile
import zipfile

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "scrub_check", os.path.join(os.path.dirname(__file__), "..", "tools", "scrub_check.py"))
sc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sc)

# The forbidden strings are assembled from pieces so that this file does not trip the check itself.
HOME = "/hom" + "e/someone/project"
USER = "senti" + "mentalk"
MAIL = "jane.doe" + "@" + "mailbox.io"
TOOL = "or" + "ca"
SECRET_OPENAI = "sk" + "-" + "a1B2c3D4e5F6g7H8i9J0"
SECRET_GH = "gh" + "p_" + "A" * 24
SECRET_PAT = "github" + "_pat_" + "B" * 24
SECRET_AWS = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
PRIVATE_KEY = "-----" + "BEGIN RSA PRIVATE KEY-----"
API_ASSIGN = "api" + "_key = 'x'"

TEXT_HITS = [
    ("home-path", "path is %s here" % HOME),
    ("username", "owner %s wrote this" % USER.upper()),
    ("email", "contact %s please" % MAIL),
    ("lifeos", "see Life" + "OS notes"),
    ("ticket", "tracked in PROJECT" + "-125"),
    ("internal-id", "dispatch ctx" + "_af498c96b741"),
    ("internal-id", "handle term" + "_dbaab521-5261"),
    ("secret", SECRET_OPENAI),
    ("secret", SECRET_GH),
    ("secret", SECRET_PAT),
    ("secret", SECRET_AWS),
    ("secret", PRIVATE_KEY),
    ("secret", API_ASSIGN),
    ("claude-dir", "see ~/." + "claude/settings"),
    ("tool-name", "run it in %s now" % TOOL.upper()),
    ("screencast", "screencast" + "_poc/"),
]


def _scan(tmp_path, name, content):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    hits, n = sc.scan_paths([str(p)])
    return hits, n


@pytest.mark.parametrize("rule,line", TEXT_HITS)
def test_every_rule_hits_in_a_text_file(tmp_path, rule, line):
    hits, n = _scan(tmp_path, "notes.txt", "first line\n%s\nlast line\n" % line)
    assert n == 1
    assert [(h[1], h[2]) for h in hits if h[2] == rule] and all(h[1] == 2 for h in hits)


def test_file_name_is_checked_with_every_rule(tmp_path):
    hits, _ = _scan(tmp_path, "report_%s.txt" % USER, "clean\n")
    assert [(h[0], h[1], h[2]) for h in hits] == [("report_%s.txt" % USER, 0, "username")]


def test_project_url_is_allowed_but_other_mentions_on_the_line_are_not(tmp_path):
    url = "github.com/Senti" + "mentalK/pixeltree"
    hits, _ = _scan(tmp_path, "README.md", "Source: https://%s\n" % url)
    assert hits == []
    hits, _ = _scan(tmp_path, "README2.md", "https://%s and %s\n" % (url, USER))
    assert [h[2] for h in hits] == ["username"]
    hits, _ = _scan(tmp_path, "README3.md", "https://%s-fork/pixeltree\n" % url.split("/")[0] + "/" + USER)
    assert [h[2] for h in hits] == ["username"]


def test_author_line_in_license_is_allowed_only_there(tmp_path):
    line = "Copyright (c) 2026 %s\n" % USER
    assert _scan(tmp_path, "LICENSE", line + "Permission is granted.\n")[0] == []
    assert _scan(tmp_path, "NOTICE", line)[0] == []
    assert [h[2] for h in _scan(tmp_path, "docs/credits.md", line)[0]] == ["username"]
    # in LICENSE only lines that carry "Copyright" are exempt
    hits = _scan(tmp_path, "sub/LICENSE", line + "maintained by %s\n" % USER)[0]
    assert [(h[1], h[2]) for h in hits] == [(2, "username")]


def test_github_noreply_addresses_are_allowed(tmp_path):
    ok = "noreply" + "@" + "github.com"
    ok2 = "12345+someone" + "@" + "users.noreply.github.com"
    assert _scan(tmp_path, "a.txt", "%s and %s\n" % (ok, ok2))[0] == []
    hits = _scan(tmp_path, "b.txt", "%s\n" % ("someone" + "@" + "github.com"))[0]
    assert [h[2] for h in hits] == ["email"]


def test_clean_text_has_no_hits(tmp_path):
    hits, n = _scan(tmp_path, "ok.py", "def f(task_id):\n    return task_id  # run_loop, term_count\n")
    assert hits == [] and n == 1


def test_tar_gz_members_are_scanned(tmp_path):
    p = tmp_path / "bundle.tar.gz"
    with tarfile.open(p, "w:gz") as t:
        for name, data in (("data/clean.txt", b"nothing here\n"),
                           ("data/leak.txt", ("x\nowner %s\n" % USER).encode())):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    hits, n = sc.scan_paths([str(p)])
    assert n == 1
    assert hits == [("bundle.tar.gz!data/leak.txt", 2, "username", USER)]


def test_zip_member_names_and_contents_are_scanned(tmp_path):
    p = tmp_path / "bundle.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("%s/readme.txt" % USER, "fine\n")
        z.writestr("code.py", "path = '%s'\n" % HOME)
    hits, _ = sc.scan_paths([str(p)])
    assert sorted((h[0], h[1], h[2]) for h in hits) == sorted([
        ("bundle.zip!%s/readme.txt" % USER, 0, "username"),
        ("bundle.zip!code.py", 1, "home-path"),
    ])


def test_binary_content_is_checked_with_literal_rules_only(tmp_path):
    png = b"\x89PNG\r\n\x1a\n\x00\x00" + SECRET_OPENAI.encode() + MAIL.encode() + TOOL.encode()
    assert _scan(tmp_path, "random.png", png)[0] == []
    leaky = b"\x89PNG\r\n\x1a\n\x00\x00junk" + HOME.encode() + b"junk"
    hits = _scan(tmp_path, "leaky.png", leaky)[0]
    assert [(h[0], h[1], h[2]) for h in hits] == [("leaky.png", 0, "home-path")]
    hits = _scan(tmp_path, "who.webp", b"\x00RIFF" + USER.encode())[0]
    assert [h[2] for h in hits] == ["username"]


def test_skipped_directories_and_weights_are_ignored(tmp_path):
    for d in (".git", ".venv", "venv", "site", "out", "__pycache__"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "x.txt").write_text(HOME)
    (tmp_path / "model.pt").write_bytes(HOME.encode())
    (tmp_path / "kept.txt").write_text("fine\n")
    hits, n = sc.scan_paths([str(tmp_path)])
    assert hits == [] and n == 1


def test_main_exit_codes_and_output(tmp_path, capsys):
    (tmp_path / "a.txt").write_text("fine\n")
    assert sc.main(["--paths", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "scrub_check: 0 hits (1 files)"
    (tmp_path / "b.txt").write_text("x\n%s\n" % HOME)
    assert sc.main(["--paths", str(tmp_path)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("b.txt:2: home-path: ")
    assert out[-1] == "scrub_check: 1 hits (2 files)"


def test_secret_text_is_masked_in_output(tmp_path, capsys):
    (tmp_path / "k.txt").write_text(SECRET_OPENAI + "\n")
    sc.main(["--paths", str(tmp_path)])
    assert SECRET_OPENAI not in capsys.readouterr().out


def _git(repo, *args):
    import subprocess
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@users.noreply.github.com",
                    *args], check=True, capture_output=True)


def test_git_history_finds_removed_content_and_lists_emails(tmp_path):
    import shutil
    if not shutil.which("git"):
        pytest.skip("git not available")
    _git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("path %s\n" % HOME)
    _git(tmp_path, "add", "f.txt")
    _git(tmp_path, "commit", "-q", "-m", "add file for %s" % USER)
    (tmp_path / "f.txt").write_text("clean now\n")
    _git(tmp_path, "commit", "-q", "-a", "-m", "clean up")
    hits, addrs = sc.scan_git_history(str(tmp_path))
    assert sorted({h[2] for h in hits}) == ["home-path", "username"]
    assert addrs == ["t@users.noreply.github.com"]
    # the working tree itself is clean, only the history is not
    assert sc.scan_paths([str(tmp_path)])[0] == []


def test_git_history_of_an_empty_repository(tmp_path):
    import shutil
    if not shutil.which("git"):
        pytest.skip("git not available")
    _git(tmp_path, "init", "-q")
    assert sc.scan_git_history(str(tmp_path)) == ([], [])


def test_reserved_domain_addresses_are_allowed_but_normal_ones_hit(tmp_path):
    ok = ["demo" + "@" + "example.com", "clerk" + "@" + "harbor.example", "a.b" + "@" + "mail.example.org",
          "x" + "@" + "host.test", "noreply" + "@" + "anthropic.com"]
    assert _scan(tmp_path, "ok.txt", "\n".join(ok) + "\n")[0] == []
    bad = ["jane" + "@" + "example.com.evil.io", "jane" + "@" + "notexample.com", "jane" + "@" + "gmail.com"]
    hits = _scan(tmp_path, "bad.txt", "\n".join(bad) + "\n")[0]
    assert [(h[1], h[2]) for h in hits] == [(1, "email"), (2, "email"), (3, "email")]


def test_diff_marker_before_decorator_is_not_an_email(tmp_path):
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("scrub_check", pathlib.Path(__file__).resolve().parents[1] / "tools" / "scrub_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rx = dict((name, pat) for name, _, pat in mod.RULES)["email"] if hasattr(mod, "RULES") else None
    import re
    assert rx is not None
    assert re.search(rx, "+@pytest.mark.parametrize") is None
    assert re.search(rx, "contact: jane.doe" + "@" + "corp.io") is not None
    assert re.search(rx, "+jane.doe" + "@" + "corp.io") is not None  # an added line in a diff
