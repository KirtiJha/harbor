"""Git branch and worktree of a folder, read straight from .git (no git process on the scan path)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

_cache = {}


def _head(gitdir):
    try:
        text = (Path(gitdir) / "HEAD").read_text().strip()
    except OSError:
        return None
    m = re.match(r"ref: refs/heads/(.+)", text)
    return m.group(1) if m else (text[:8] if text else None)


def info(path):
    """{branch, worktree, root, repo, common} for the git checkout containing `path`, or None."""
    if not path:
        return None
    p = Path(path)
    for d in [p, *p.parents]:
        dotgit = d / ".git"
        if dotgit.is_dir():
            gitdir, common, worktree = dotgit, dotgit, False
        elif dotgit.is_file():
            m = re.match(r"gitdir:\s*(.+)", dotgit.read_text(errors="replace").strip())
            if not m:
                return None
            gitdir = (d / m.group(1)).resolve()
            common_file = gitdir / "commondir"
            common = (gitdir / common_file.read_text().strip()).resolve() if common_file.exists() else gitdir
            worktree = True
        else:
            if d == d.parent:
                return None
            continue
        key = (str(d), _mtime(gitdir / "HEAD"))
        if key not in _cache:
            repo_root = Path(common).parent if Path(common).name == ".git" else Path(common)
            _cache[key] = {"branch": _head(gitdir), "worktree": worktree, "root": str(d), "repo": repo_root.name,
                           "common": str(common)}
        return _cache[key]
    return None


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def worktrees(path):
    """[{path, branch, head, main}] for the repository containing `path` (uses `git worktree list`)."""
    git = shutil.which("git")
    if not git:
        return []
    try:
        out = subprocess.run([git, "-C", str(path), "worktree", "list", "--porcelain"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    items, cur = [], {}
    for line in out.stdout.splitlines() + [""]:
        if not line.strip():
            if cur:
                items.append(cur)
            cur = {}
            continue
        k, _, v = line.partition(" ")
        if k == "worktree":
            cur = {"path": v, "branch": None, "head": None, "main": not items}
        elif k == "branch":
            cur["branch"] = v.replace("refs/heads/", "")
        elif k == "HEAD":
            cur["head"] = v[:8]
        elif k == "detached":
            cur["branch"] = cur.get("branch") or f"detached {cur.get('head')}"
    return items
