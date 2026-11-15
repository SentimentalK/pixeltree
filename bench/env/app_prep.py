"""Sandbox-HOME preparation for the apps that need generated input (a git repository, an Obsidian vault) and the
`flatpak run` argv builder with the private-desktop isolation flags."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

GIT_AUTHOR = "Test User"
GIT_EMAIL = "test@example.com"


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_git_repo(home):
    """~/Projects/demo-repo with 5 commits by Test User."""
    repo = Path(home) / "Projects" / "demo-repo"
    shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir(parents=True)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "GIT_AUTHOR_NAME": GIT_AUTHOR,
           "GIT_AUTHOR_EMAIL": GIT_EMAIL, "GIT_COMMITTER_NAME": GIT_AUTHOR,
           "GIT_COMMITTER_EMAIL": GIT_EMAIL, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args, extra=None):
        subprocess.run(["git", "-C", str(repo), *args], env=dict(env, **(extra or {})), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    git("init", "-q", "-b", "main")
    git("config", "user.name", GIT_AUTHOR)
    git("config", "user.email", GIT_EMAIL)
    steps = [("README.md", "# demo\n", "Add readme"),
             ("src/main.py", "print('hello')\n", "Add main script"),
             ("src/util.py", "def add(a, b):\n    return a + b\n", "Add util module"),
             ("README.md", "# demo\n\nUsage: python src/main.py\n", "Document usage"),
             ("src/main.py", "from util import add\nprint(add(1, 2))\n", "Use util in main")]
    for i, (rel, text, msg) in enumerate(steps):
        _write(repo / rel, text)
        git("add", "-A")
        stamp = f"2026-01-0{i + 1}T10:00:00+0000"
        git("commit", "-q", "-m", msg, extra={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
    return repo


def make_vault(home):
    vault = Path(home) / "Documents" / "vault"
    _write(vault / "Welcome.md", "# Welcome\n\nThis vault has three notes. See [[Projects]] and [[Reading list]].\n")
    _write(vault / "Projects.md", "# Projects\n\n- [ ] write report\n- [x] book room\n\nBack to [[Welcome]].\n")
    _write(vault / "Reading list.md", "# Reading list\n\n1. A book\n2. Another book\n\n#reading\n")
    return vault


def make_obsidian_config(home, vault):
    """Obsidian (flatpak) opens the vault listed as open in its obsidian.json."""
    cfg = Path(home) / ".var" / "app" / "md.obsidian.Obsidian" / "config" / "obsidian"
    _write(cfg / "obsidian.json", json.dumps({"vaults": {"0123456789abcdef": {
        "path": str(vault), "ts": 1767225600000, "open": True}}}))


def prep_obsidian(home):
    make_obsidian_config(home, make_vault(home))


# Private-desktop isolation of every `flatpak run`.
# The sandbox only has the private Xvfb and the private session bus, so the sockets of the user's real session
# are taken away: Wayland (an app whose finish-args list "wayland" would get the real compositor, and an app with
# only "fallback-x11" would then NOT get the X socket -> "Missing X server or $DISPLAY", exit 1), PulseAudio,
# the ssh / gpg agents and the smart-card daemon.  --socket=x11 gives every app the private X display (the DISPLAY
# of the caller's environment); --nofilesystem=host drops whole-host access.
FLATPAK_ISOLATION = ["--socket=x11", "--nosocket=wayland", "--nosocket=pulseaudio", "--nosocket=ssh-auth",
                     "--nosocket=gpg-agent", "--nosocket=pcsc", "--nofilesystem=host"]


def flatpak_argv(app_id, *extra, short_tmp_exec=None):
    """flatpak run argv.  short_tmp_exec: path of the Electron binary inside the sandbox, for apps whose wrapper
    script sets TMPDIR to the (long) sandbox cache dir: Chromium then dies with "Socket path too long" (108 bytes)
    for its SingletonSocket.  Those apps are started through sh with TMPDIR=/tmp (a private tmpfs of the sandbox)."""
    head = ["flatpak", "run", "--user", "--env=ACCESSIBILITY_ENABLED=1", "--env=XDG_SESSION_TYPE=x11",
            *FLATPAK_ISOLATION]
    if short_tmp_exec is None:
        return [*head, app_id, *extra]
    script = f'TMPDIR=/tmp exec zypak-wrapper {short_tmp_exec} "$@"'
    return [*head, "--command=sh", app_id, "-c", script, "sh", *extra]
