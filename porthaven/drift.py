"""Port drift: config files that point at a port where the service they mean no longer is.

Porthaven reads the files where projects write down each other's addresses (.env files, vite/next/nuxt configs,
proxy configs, docker-compose files, package.json proxies) and checks every `localhost:PORT` against what is
running now: "Storefront's .env expects the API on :8000, but the API is on :8001".
"""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import time
from pathlib import Path

REF = re.compile(r"(?i)\b(?:https?://|wss?://|//)?(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|host\.docker\.internal)\s*:\s*(\d{2,5})\b")
FILES = [".env", ".env.*", "vite.config.*", "vitest.config.*", "next.config.*", "nuxt.config.*", "astro.config.*", "svelte.config.*",
         "remix.config.*", "webpack.config.*", "rsbuild.config.*", "angular.json", "proxy.conf.*", "setupProxy.*", "package.json",
         "docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml", "Procfile", "Procfile.*",
         "application.properties", "application*.yml", "settings.py", "config.ts", "config.js", "config.json", "playwright.config.*"]
NOT = [".env.example", ".env.sample", ".env.template", ".env.dist", "*.example", "*.sample", "*.template", "*.md"]
SKIP = {"node_modules", ".git", ".venv", "venv", "dist", "build", ".next", ".nuxt", ".svelte-kit", ".output", "target", "__pycache__",
        ".cache", ".turbo", "coverage", ".idea", ".vscode", "vendor", ".tox", ".mypy_cache", ".pytest_cache", "out"}
MAX_FILES, MAX_BYTES, DEPTH = 300, 256 * 1024, 3
ENV_KEY = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def wanted(name):
    return any(fnmatch.fnmatch(name, p) for p in FILES) and not any(fnmatch.fnmatch(name, p) for p in NOT)


def files_in(root):
    """Config files under a project folder (a few levels deep, skipping dependencies and build output)."""
    root = Path(root)
    out = []
    base_depth = len(root.parts)
    for d, dirs, names in os.walk(root):
        depth = len(Path(d).parts) - base_depth
        dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".") and depth < DEPTH]
        for n in names:
            if wanted(n):
                out.append(Path(d) / n)
                if len(out) >= MAX_FILES:
                    return out
    return out


class Scanner:
    def __init__(self):
        self.cache = {}     # path -> (mtime, size, refs)

    def refs(self, path):
        """[{line, col, host, port, text, key}] for every localhost:PORT in a file (cached until it changes)."""
        try:
            st = path.stat()
        except OSError:
            return []
        hit = self.cache.get(str(path))
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            return hit[2]
        out = []
        if st.st_size <= MAX_BYTES:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for i, line in enumerate(text.splitlines()):
                stripped = line.lstrip()
                if stripped.startswith(("#", "//")) and not path.name.startswith(".env"):
                    continue
                if path.name.startswith(".env") and stripped.startswith("#"):
                    continue
                for m in REF.finditer(line):
                    port = int(m.group(2))
                    if not 1 <= port <= 65535:
                        continue
                    k = ENV_KEY.match(line) if path.name.startswith(".env") else None
                    out.append({"line": i + 1, "col": m.start(1) + 1, "host": m.group(1), "port": port,
                                "match": f"{m.group(1)}:{m.group(2)}", "text": line.strip()[:200], "key": k.group(1) if k else None})
        self.cache[str(path)] = (st.st_mtime, st.st_size, out)
        return out


def _rp(p):
    try:
        return os.path.realpath(os.path.expanduser(p)) if p else None
    except OSError:
        return p


def check(projects, apps, rows, activity, porthaven_port=None, scanner=None, now=None):
    """projects: [{root, name, appId?, ports}] where to look. Returns findings, worst first.

    A finding: {id, level, file, line, match, port, key, project, appId, title, detail, fix: {port, target?}}.
    """
    scanner = scanner or Scanner()
    now = now or time.time()
    listening = {}
    for r in rows:
        listening.setdefault(r["port"], r)
    running_ports = {}   # app id -> ports it runs on now
    for r in rows:
        if r.get("appId"):
            running_ports.setdefault(r["appId"], set()).add(r["port"])
    by_port_app = {}
    for a in apps:
        if a.get("port"):
            by_port_app.setdefault(int(a["port"]), []).append(a)
    # where each project was last seen listening, by name: "api used to be on :8000"
    last_seen = {}
    for e in activity:
        if e.get("type") == "opened" and e.get("port") and now - e["ts"] < 7 * 86400:
            for name in {e.get("project"), e.get("title")} - {None, ""}:
                last_seen.setdefault(e["port"], set()).add(name)
    findings, seen = [], set()
    for proj in projects:
        root = proj["root"]
        own_ports = set(proj.get("ports") or [])
        for path in files_in(root):
            rel = os.path.relpath(path, root)
            for ref in scanner.refs(path):
                p = ref["port"]
                if p in own_ports or p == porthaven_port:
                    continue
                key = (str(path), ref["line"], ref["match"])
                if key in seen:
                    continue
                seen.add(key)
                base = {"file": str(path), "rel": rel, "line": ref["line"], "match": ref["match"], "host": ref["host"], "port": p, "key": ref["key"],
                        "text": ref["text"], "project": proj["name"], "projectRoot": root, "appId": proj.get("appId"),
                        "id": f"{path}:{ref['line']}:{ref['match']}"}
                expected = [a for a in by_port_app.get(p, []) if a["id"] != proj.get("appId") and _rp(a["cwd"]) != _rp(root)]
                moved = [(a, sorted(running_ports.get(a["id"], []))) for a in expected if running_ports.get(a["id"]) and p not in running_ports[a["id"]]]
                if moved:
                    a, now_on = moved[0]
                    holder = listening.get(p)
                    findings.append({**base, "level": "warn", "target": {"appId": a["id"], "name": a["name"], "slug": a.get("slug")},
                                     "title": f"{proj['name']} expects {a['name']} on :{p}, but {a['name']} is on :{now_on[0]}",
                                     "detail": f"{rel} line {ref['line']}" + (f"; :{p} is now held by {holder['title']}" if holder else ""),
                                     "fix": {"port": now_on[0]}})
                    continue
                if p in listening or expected:
                    continue   # something answers there, or the app meant to is just not running now
                names = last_seen.get(p, set())
                mover = next((r for r in rows if r["port"] != p and ({(r.get("project") or {}).get("name"), r["title"]} & names)
                              and r.get("project", {}) and _rp((r.get("project") or {}).get("root")) != _rp(root)), None)
                if mover:
                    who = (mover.get("project") or {}).get("name") or mover["title"]
                    findings.append({**base, "level": "warn", "target": {"appId": mover.get("appId"), "name": who},
                                     "title": f"{proj['name']} points at :{p}, where {who} used to be; {who} is now on :{mover['port']}",
                                     "detail": f"{rel} line {ref['line']}", "fix": {"port": mover["port"]}})
                elif proj.get("running"):
                    findings.append({**base, "level": "info", "target": None,
                                     "title": f"{proj['name']} points at :{p}, but nothing is listening there",
                                     "detail": f"{rel} line {ref['line']}", "fix": None})
    findings.sort(key=lambda f: (f["level"] != "warn", f["project"], f["rel"], f["line"]))
    return findings


def apply_fix(path, line, old, new):
    """Replace `old` (e.g. localhost:8000) with `new` on one line of a file; raises ValueError when the line changed."""
    p = Path(path)
    text = p.read_bytes().decode("utf-8")   # bytes, so Windows line endings stay as they are
    lines = text.splitlines(keepends=True)
    if not 1 <= line <= len(lines) or old not in lines[line - 1]:
        raise ValueError(f"Line {line} of {p.name} no longer contains {old}; scan again.")
    lines[line - 1] = lines[line - 1].replace(old, new, 1)
    tmp = p.with_name(p.name + ".porthaven-tmp")
    tmp.write_bytes("".join(lines).encode("utf-8"))
    shutil.copymode(p, tmp)
    os.replace(tmp, p)
    return lines[line - 1].strip()
