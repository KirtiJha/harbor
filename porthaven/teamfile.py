"""porthaven.toml: a repo's apps, committed so everyone who clones it gets the same setup.

    group = "Shop"                       # optional; defaults to the folder name

    [apps.api]
    command = ".venv/bin/uvicorn main:app --reload --port {port}"
    cwd = "backend"                       # relative to this file
    port = 8000
    health = "/health"

    [apps.web]
    name = "Storefront"
    command = "npm run dev -- --port {port} --strictPort"
    cwd = "frontend"
    port = 5173
    depends_on = ["api"]
    env = { API_URL = "{url:api}" }
    sleep_after = 60                      # minutes without traffic; 0 = never

    [apps.db]
    compose = "postgres"                  # a service of the docker-compose file in cwd (or compose_file)

`porthaven up` imports the file and starts the stack in dependency order; `porthaven down` stops it.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

NAME = "porthaven.toml"
FIELDS = {  # TOML key -> app field
    "name": "name", "command": "command", "port": "port", "cwd": "cwd", "slug": "slug", "health": "health",
    "depends_on": "dependsOn", "env": "env", "sleep_after": "sleepAfter", "wake": "wake", "open_path": "openPath",
    "auto_restart": "autoRestart", "color": "color", "group": "group", "compose": "compose", "compose_file": "composeFile",
}


class TeamfileError(ValueError):
    pass


# ---------------------------------------------------------------- a small TOML reader for this file's needs

def parse_toml(text):
    try:
        import tomllib   # Python 3.11+
        return tomllib.loads(text)
    except ImportError:
        return _mini_toml(text)
    except Exception as err:   # tomllib.TOMLDecodeError
        raise TeamfileError(f"{NAME} is not valid TOML: {err}") from err


def _mini_toml(text):
    doc, table = {}, None
    for n, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        m = re.fullmatch(r"\[([A-Za-z0-9_.-]+)\]", line)
        if m:
            table = doc
            for part in m.group(1).split("."):
                table = table.setdefault(part, {})
            continue
        m = re.fullmatch(r"([A-Za-z0-9_-]+)\s*=\s*(.+)", line)
        if not m:
            raise TeamfileError(f"{NAME} line {n}: expected `key = value` or `[table]`.")
        try:
            value, rest = _value(m.group(2).strip())
        except (ValueError, IndexError) as err:
            raise TeamfileError(f"{NAME} line {n}: {err}") from err
        if rest.strip():
            raise TeamfileError(f"{NAME} line {n}: unexpected text after the value.")
        (table if table is not None else doc)[m.group(1)] = value
    return doc


def _strip_comment(line):
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out)


def _value(s):
    if s.startswith('"'):
        end = 1
        while s[end] != '"':
            end += 2 if s[end] == "\\" else 1
        return json.loads(s[:end + 1]), s[end + 1:]
    if s.startswith("'"):
        end = s.index("'", 1)
        return s[1:end], s[end + 1:]
    if s.startswith("["):
        items, rest = [], s[1:].lstrip()
        while not rest.startswith("]"):
            v, rest = _value(rest)
            items.append(v)
            rest = rest.lstrip()
            if rest.startswith(","):
                rest = rest[1:].lstrip()
        return items, rest[1:]
    if s.startswith("{"):
        table, rest = {}, s[1:].lstrip()
        while not rest.startswith("}"):
            m = re.match(r'([A-Za-z0-9_-]+|"[^"]+")\s*=\s*', rest)
            if not m:
                raise ValueError("expected `key = value` in an inline table")
            v, rest = _value(rest[m.end():])
            table[m.group(1).strip('"')] = v
            rest = rest.lstrip()
            if rest.startswith(","):
                rest = rest[1:].lstrip()
        return table, rest[1:]
    m = re.match(r"(true|false)\b", s)
    if m:
        return m.group(1) == "true", s[m.end():]
    m = re.match(r"[+-]?\d[\d_]*", s)
    if m:
        return int(m.group(0).replace("_", "")), s[m.end():]
    raise ValueError(f"cannot read the value `{s[:20]}`")


# ---------------------------------------------------------------- file <-> apps

def find(start):
    """porthaven.toml in `start` or the nearest folder above it."""
    p = Path(os.path.expanduser(str(start))).resolve()
    if p.is_file():
        return p
    for d in [p, *p.parents]:
        if (d / NAME).is_file():
            return d / NAME
    return None


def load(path):
    path = Path(path)
    doc = parse_toml(path.read_text())
    apps = doc.get("apps")
    if not isinstance(apps, dict) or not apps:
        raise TeamfileError(f"{path} has no [apps.<name>] tables.")
    group = doc.get("group") or path.parent.name
    out = []
    for key, spec in apps.items():
        if not isinstance(spec, dict) or not (spec.get("command") or spec.get("compose")):
            raise TeamfileError(f"[apps.{key}] in {path} needs a command (or a compose service).")
        unknown = set(spec) - set(FIELDS)
        if unknown:
            raise TeamfileError(f"[apps.{key}] in {path}: unknown setting(s) {', '.join(sorted(unknown))}.")
        app = {FIELDS[k]: v for k, v in spec.items()}
        app["cwd"] = str((path.parent / spec.get("cwd", ".")).resolve())
        if app.get("compose"):
            from . import compose
            cfile = compose.find_file(app["cwd"], app.pop("composeFile", None))
            if not cfile:
                raise TeamfileError(f"[apps.{key}] in {path}: no docker-compose file in {app['cwd']}.")
            app["compose"] = {"service": str(app["compose"]), "file": os.path.relpath(cfile, app["cwd"])}
            app.setdefault("command", compose.command(app["compose"]["file"], app["compose"]["service"]))
            if not app.get("port"):
                ports = (compose.services(cfile).get(app["compose"]["service"]) or {}).get("ports") or []
                if ports:
                    app["port"] = ports[0]
        app.pop("composeFile", None)
        app.setdefault("name", key.replace("-", " ").replace("_", " ").title())
        app.setdefault("slug", re.sub(r"[^a-z0-9-]", "-", key.lower()))
        app.setdefault("group", group)
        if isinstance(app.get("dependsOn"), str):
            app["dependsOn"] = [app["dependsOn"]]
        app["env"] = {str(k): str(v) for k, v in (app.get("env") or {}).items()}
        app["source"] = {"file": str(path.resolve()), "key": key}
        if not Path(app["cwd"]).is_dir():
            raise TeamfileError(f"[apps.{key}] in {path}: the folder {app['cwd']} does not exist.")
        out.append(app)
    return out


def dump(apps, base):
    """porthaven.toml text for saved apps (used by `porthaven init` and Export)."""
    base = Path(base).resolve()
    groups = {a.get("group") for a in apps if a.get("group")}
    lines = ["# Porthaven: `porthaven up` starts these apps in dependency order. https://github.com/KirtiJha/porthaven", ""]
    if len(groups) == 1:
        lines += [f"group = {json.dumps(groups.pop())}", ""]
    for a in apps:
        key = a.get("slug") or re.sub(r"[^a-z0-9-]", "-", a["name"].lower())
        lines.append(f"[apps.{key}]")
        if a.get("name") and a["name"].lower() != key:
            lines.append(f"name = {json.dumps(a['name'])}")
        if a.get("compose"):
            lines.append(f"compose = {json.dumps(a['compose']['service'])}")
            if a["compose"].get("file") and os.path.basename(a["compose"]["file"]) not in (
                    "compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml") or "/" in (a["compose"].get("file") or ""):
                lines.append(f"compose_file = {json.dumps(a['compose']['file'])}")
        else:
            lines.append(f"command = {json.dumps(a['command'])}")
        try:
            rel = os.path.relpath(Path(os.path.expanduser(a["cwd"])).resolve(), base)
        except ValueError:
            rel = a["cwd"]
        if rel != ".":
            lines.append(f"cwd = {json.dumps(rel.replace(os.sep, '/'))}")
        for field, key_name in (("port", "port"), ("health", "health"), ("sleepAfter", "sleep_after"), ("openPath", "open_path")):
            v = a.get(field)
            if v not in (None, "", 0, "/"):
                lines.append(f"{key_name} = {json.dumps(v)}")
        if a.get("dependsOn"):
            lines.append(f"depends_on = {json.dumps(a['dependsOn'])}")
        if a.get("env"):
            lines.append("env = { " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in a["env"].items()) + " }")
        if a.get("autoRestart"):
            lines.append("auto_restart = true")
        lines.append("")
    return "\n".join(lines)


def port_claims(apps):
    """{port: [app names]} for ports that more than one saved app (from different folders) expects."""
    by_port = {}
    for a in apps:
        if a.get("port"):
            by_port.setdefault(int(a["port"]), []).append(a)
    return {p: [a["name"] for a in lst] for p, lst in by_port.items()
            if len({os.path.realpath(os.path.expanduser(a["cwd"])) for a in lst}) > 1}
