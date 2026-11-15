"""gitg (GTK3) on ~/Projects/demo-repo."""
from pathlib import Path

from bench.env import app_prep, oracle_kit as kit

REPO = "Projects/demo-repo"


def prepare(home: Path) -> None:
    app_prep.make_git_repo(home)           # 5 commits by Test User, fixed dates


APP = {
    "name": "gitg",
    "argv": lambda home: ["gitg", str(home / REPO)],
    "env": {},
    "startup_s": 6,
    "window_title": "demo-repo",
    "process": "gitg",
    "prepare": prepare,
    "close": "wm_close",
    "state_files": [f"{REPO}/.git/HEAD", f"{REPO}/.git/refs/**", f"{REPO}/.git/packed-refs", f"{REPO}/.git/index",
                    ".config/gitg/**", f"{REPO}/*.md", f"{REPO}/src/*", f"{REPO}/docs/*"],
    "tier": "good",
    "atspi_recall_05": 0.530,
}


def _git_setup(home: Path, *args: str) -> None:
    """Prepare the repo with plain git (setup only, never used by the positive scripts)."""
    import os
    import subprocess
    repo = home / REPO
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "GIT_AUTHOR_NAME": "Test User", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "Test User", "GIT_COMMITTER_EMAIL": "test@example.com",
           "GIT_AUTHOR_DATE": "2026-01-06T10:00:00+0000", "GIT_COMMITTER_DATE": "2026-01-06T10:00:00+0000"}
    subprocess.run(["git", "-C", str(repo), *args], env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def setup_branches(home: Path) -> None:
    _git_setup(home, "branch", "release-2026-11", "HEAD~2")
    _git_setup(home, "branch", "docs-refresh", "HEAD~3")


def setup_dirty(home: Path) -> None:
    """README.md and src/util.py modified, docs/CHANGELOG.md new (untracked)."""
    repo = home / REPO
    (repo / "README.md").write_text("# demo\n\nUsage: python src/main.py\n\nNovember notes: run the demo before release.\n")
    (repo / "src" / "util.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "CHANGELOG.md").write_text("# Changelog\n\n- 2026-11: first entry\n")



# ---------------------------------------------------------------------------------------------- oracle helpers
def _g(home, *args):
    out = kit.git(home, REPO, *args)
    return None if out is None else out.strip()


def _lines(text):
    return [ln for ln in (text or "").splitlines() if ln.strip()]


def _head_files(home):
    return sorted(_lines(_g(home, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "HEAD")))


# ---------------------------------------------------------------------------------------------- oracles
def oracle_checkout(home):
    branch = _g(home, "symbolic-ref", "--short", "-q", "HEAD")
    return branch == "release-2026-11", f"HEAD branch={branch!r}"


def oracle_stage_readme(home):
    staged = sorted(_lines(_g(home, "diff", "--cached", "--name-only")))
    count = _g(home, "rev-list", "--count", "HEAD")
    return staged == ["README.md"] and count == "5", f"staged={staged!r} commits={count!r}"


def oracle_create_branch(home):
    tip = _g(home, "rev-parse", "--verify", "-q", "refs/heads/tide-notes")
    main = _g(home, "rev-parse", "--verify", "-q", "refs/heads/main")
    ok = bool(tip) and tip == main
    return ok, f"tide-notes={tip!r} main={main!r}"


def oracle_tag(home):
    names = _g(home, "tag", "-l", "v2026.11")
    commit = _g(home, "rev-parse", "--verify", "-q", "v2026.11^{commit}")
    subject = _g(home, "log", "-1", "--format=%s", commit) if commit else None
    return names == "v2026.11" and subject == "Document usage", f"tag={names!r} points at {subject!r}"


def oracle_commit_readme(home):
    subject = _g(home, "log", "-1", "--format=%s")
    files = _head_files(home)
    count = _g(home, "rev-list", "--count", "HEAD")
    dirty = _g(home, "status", "--porcelain", "--", "README.md")
    ok = subject == "Update usage notes for November" and files == ["README.md"] and count == "6" and dirty == ""
    return ok, f"subject={subject!r} files={files!r} commits={count!r} README status={dirty!r}"


def oracle_commit_two_branch(home):
    subject = _g(home, "log", "-1", "--format=%s")
    files = _head_files(home)
    head = _g(home, "rev-parse", "HEAD")
    branch = _g(home, "rev-parse", "--verify", "-q", "refs/heads/release-2026-12")
    readme = _g(home, "status", "--porcelain", "--", "README.md")
    ok = (subject == "Add changelog and subtract helper" and files == ["docs/CHANGELOG.md", "src/util.py"]
          and branch == head and readme == "M README.md")
    return ok, f"subject={subject!r} files={files!r} branch==HEAD:{branch == head} README status={readme!r}"


# ---------------------------------------------------------------------------------------------- positive scripts
def _history(ep):
    ep.click(1691, 27)                      # "History" toggle in the header bar
    ep.sleep(1.2)


def _commit_view(ep):
    ep.click(1724, 27)                      # "Commit" toggle
    ep.sleep(1.5)


def _row(ep, subject):
    cell = ep.wait_node(role="table cell", name=subject)
    return cell


def _context(ep, node, item):
    ep.click_box(node, button=3)
    ep.sleep(0.6)
    ep.click_node(role="menu item", name=item)
    ep.sleep(1.2)


def _dialog_text_field(ep, title):
    dlg = ep.wait_node(role="dialog", name=title)
    fields = [n for n in ep.nodes_in(dlg, role="text") if n["box"][3] < 60]
    ep.click_box(fields[0])
    return dlg


def _stage_via_menu(ep, label_name, item="Stage changes"):
    node = ep.wait_node(role="table cell", name=label_name)
    ep.click_box(node, button=3)
    ep.sleep(0.6)
    ep.click_node(role="menu item", name=item)
    ep.sleep(1.0)


def _write_message_and_commit(ep, message):
    ep.click_node(role="button", name="Commit")        # bottom-right "Commit" opens the dialog
    ep.sleep(1.2)
    dlg = ep.wait_node(role="dialog", name="Commit")
    area = max(ep.nodes_in(dlg, role="text"), key=lambda n: n["box"][2] * n["box"][3])
    ep.click_box(area)
    ep.type(message)
    ep.sleep(0.5)
    buttons = [n for n in ep.nodes_in(dlg, role="button") if n["name"] == "Commit"]
    ep.click_box(buttons[0])
    ep.sleep(2.0)


def pos_checkout(ep):
    node = ep.wait_node(role="label", name="release-2026-11")
    _context(ep, node, "Checkout")


def pos_stage_readme(ep):
    _commit_view(ep)
    _stage_via_menu(ep, "README.md")


def pos_create_branch(ep):
    _context(ep, _row(ep, "Use util in main"), "Create branch")
    _dialog_text_field(ep, "Create Branch")
    ep.type("tide-notes")
    dlg = ep.wait_node(role="dialog", name="Create Branch")
    create = [n for n in ep.nodes_in(dlg, role="button") if n["name"] == "Create"][0]
    ep.click_box(create)
    ep.sleep(1.5)


def pos_tag(ep):
    _context(ep, _row(ep, "Document usage"), "Create tag")
    _dialog_text_field(ep, "Create Tag")
    ep.type("v2026.11")
    dlg = ep.wait_node(role="dialog", name="Create Tag")
    create = [n for n in ep.nodes_in(dlg, role="button") if n["name"] == "Create"][0]
    ep.click_box(create)
    ep.sleep(1.5)


def pos_commit_readme(ep):
    _commit_view(ep)
    _stage_via_menu(ep, "README.md")
    _write_message_and_commit(ep, "Update usage notes for November")


def pos_commit_two_branch(ep):
    _commit_view(ep)
    _stage_via_menu(ep, "src/util.py")
    _stage_via_menu(ep, "docs/CHANGELOG.md", item="Stage changes")
    _write_message_and_commit(ep, "Add changelog and subtract helper")
    _history(ep)
    _context(ep, _row(ep, "Add changelog and subtract helper"), "Create branch")
    _dialog_text_field(ep, "Create Branch")
    ep.type("release-2026-12")
    dlg = ep.wait_node(role="dialog", name="Create Branch")
    create = [n for n in ep.nodes_in(dlg, role="button") if n["name"] == "Create"][0]
    ep.click_box(create)
    ep.sleep(1.5)


def _both(home):
    setup_branches(home)
    setup_dirty(home)


TASKS = [
    {"id": "gitg_checkout_branch", "difficulty": 1,
     "sentence": "In the gitg window, switch the repository to the existing branch release-2026-11 (check it out).",
     "setup": setup_branches, "oracle": oracle_checkout, "positive": pos_checkout},
    {"id": "gitg_stage_readme", "difficulty": 1,
     "sentence": "In gitg, stage the modified file README.md without committing, and leave src/util.py unstaged.",
     "setup": setup_dirty, "oracle": oracle_stage_readme, "positive": pos_stage_readme},
    {"id": "gitg_create_branch", "difficulty": 2,
     "sentence": "Create a new branch named tide-notes that starts at the newest commit of main, \"Use util in main\".",
     "setup": None, "oracle": oracle_create_branch, "positive": pos_create_branch},
    {"id": "gitg_tag_commit", "difficulty": 2,
     "sentence": "Create a tag named v2026.11 on the commit whose subject is \"Document usage\".",
     "setup": None, "oracle": oracle_tag, "positive": pos_tag},
    {"id": "gitg_commit_readme", "difficulty": 2,
     "sentence": "Commit only the change to README.md, using the commit message: Update usage notes for November",
     "setup": setup_dirty, "oracle": oracle_commit_readme, "positive": pos_commit_readme},
    {"id": "gitg_commit_two_then_branch", "difficulty": 3,
     "sentence": "Commit src/util.py and the new file docs/CHANGELOG.md together (leave README.md uncommitted) with the message "
                 "\"Add changelog and subtract helper\", then create a branch named release-2026-12 at that new commit.",
     "setup": setup_dirty, "oracle": oracle_commit_two_branch, "positive": pos_commit_two_branch},
]
