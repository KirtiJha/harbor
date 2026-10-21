"""Finding projects in a folder that can be run, with the command and port each one probably uses."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SKIP = {"node_modules", ".git", ".venv", "venv", "dist", "build", ".next", ".nuxt", "target", "__pycache__",
        ".cache", ".turbo", "coverage", ".idea", ".vscode", "Library", "Applications", "Pictures", "Music", "Movies"}
SCRIPT_ORDER = ("dev", "start", "serve", "develop", "preview", "storybook")
MAKE_TARGETS = ("dev", "run", "serve", "start", "up")
PORT_FLAG = re.compile(r"(?:--port[= ]|-p\s+|PORT=|:)(\d{4,5})\b")
DEFAULT_PORTS = [("vite", 5173), ("next", 3000), ("nuxt", 3000), ("astro", 4321), ("react-scripts", 3000),
                 ("storybook", 6006), ("ng serve", 4200), ("remix", 3000), ("webpack", 8080), ("expo", 8081),
                 ("uvicorn", 8000), ("runserver", 8000), ("flask", 5000), ("streamlit", 8501), ("jupyter", 8888),
                 ("mkdocs", 8000), ("hugo", 1313), ("jekyll", 4000), ("gradio", 7860)]


def guess_port(text):
    m = PORT_FLAG.search(text or "")
    if m:
        return int(m.group(1))
    for word, port in DEFAULT_PORTS:
        if word in (text or ""):
            return port
    return None


def package_manager(d):
    for lock, pm in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"), ("bun.lock", "bun")):
        if (d / lock).exists():
            return pm
    return "npm"


def _node(d):
    try:
        pj = json.loads((d / "package.json").read_text(errors="replace"))
    except (OSError, ValueError):
        return []
    scripts = pj.get("scripts") or {}
    pm = package_manager(d)
    out = []
    for name in SCRIPT_ORDER:
        if name in scripts:
            run = f"{pm} run {name}" if pm != "npm" or name not in ("start",) else "npm start"
            out.append({"name": pj.get("name") or d.name, "script": name, "command": run, "detail": scripts[name],
                        "port": guess_port(scripts[name]), "type": "node"})
    return out


def _make(d):
    try:
        text = (d / "Makefile").read_text(errors="replace")
    except OSError:
        return []
    out = []
    for target in MAKE_TARGETS:
        m = re.search(rf"^{target}\s*:[^=\n]*\n((?:\t.*\n?)*)", text, re.M)
        if m:
            recipe = m.group(1).strip()
            out.append({"name": d.name, "script": target, "command": f"make {target}", "detail": recipe[:200],
                        "port": guess_port(recipe), "type": "make"})
    return out


def _python(d):
    out = []
    if (d / "manage.py").exists():
        out.append({"name": d.name, "script": "runserver", "command": "python manage.py runserver {port}",
                    "detail": "Django development server", "port": 8000, "type": "python"})
    for f in ("app.py", "main.py", "streamlit_app.py"):
        p = d / f
        if p.is_file():
            try:
                head = p.read_text(errors="replace")[:4000]
            except OSError:
                continue
            if "FastAPI(" in head:
                out.append({"name": d.name, "script": f, "command": f"uvicorn {f[:-3]}:app --reload --port {{port}}",
                            "detail": "FastAPI app", "port": 8000, "type": "python"})
            elif "Flask(" in head:
                out.append({"name": d.name, "script": f, "command": f"flask --app {f[:-3]} run --port {{port}}",
                            "detail": "Flask app", "port": 5000, "type": "python"})
            elif "import streamlit" in head:
                out.append({"name": d.name, "script": f, "command": f"streamlit run {f} --server.port {{port}}",
                            "detail": "Streamlit app", "port": 8501, "type": "python"})
    return out


def _compose(d):
    """Each service of a docker-compose file, runnable on its own as part of a stack."""
    from . import compose
    f = compose.find_file(d)
    if not f:
        return []
    try:
        svcs = compose.parse(f.read_text(errors="replace"))
    except OSError:
        return []
    return [{"name": name, "script": f"compose: {name}", "command": compose.command(f.name, name),
             "detail": f"{f.name} · {spec.get('image') or 'build'}" + (" · health check" if spec.get("healthcheck") else ""),
             "port": (spec.get("ports") or [None])[0], "type": "docker", "compose": {"service": name, "file": f.name}}
            for name, spec in svcs.items()]


def discover(folder, depth=3, limit=200):
    root = Path(os.path.expanduser(folder or "~")).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a folder.")
    found = []

    def walk(d, level):
        if len(found) >= limit:
            return
        items = []
        if (d / "package.json").is_file():
            items += _node(d)
        if (d / "Makefile").is_file():
            items += _make(d)
        items += _python(d)
        items += _compose(d)
        for it in items:
            it["cwd"] = str(d)
            it["rel"] = str(d.relative_to(root)) if d != root else "."
            found.append(it)
        if level >= depth:
            return
        try:
            subs = sorted(p for p in d.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in SKIP)
        except (PermissionError, OSError):
            return
        for s in subs:
            walk(s, level + 1)

    walk(root, 0)
    return {"root": str(root), "items": found[:limit], "truncated": len(found) >= limit}
