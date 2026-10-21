"""Docker Compose services as members of a stack: `[apps.db] compose = "postgres"` runs that one service with
`docker compose up`, captures its output, waits for its health check, and stops it with `docker compose stop`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

FILES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")


class ComposeError(RuntimeError):
    pass


def find_file(cwd, name=None):
    """The compose file of a folder: `name` when given (relative to the folder), else the usual names."""
    base = Path(os.path.expanduser(cwd))
    if name:
        p = Path(os.path.expanduser(name))
        p = p if p.is_absolute() else base / p
        return p if p.is_file() else None
    return next((base / f for f in FILES if (base / f).is_file()), None)


def cli():
    """The compose command as a list: `docker compose` (v2), or the older `docker-compose`."""
    docker = shutil.which("docker")
    if docker:
        return [docker, "compose"]
    legacy = shutil.which("docker-compose")
    if legacy:
        return [legacy]
    raise ComposeError("Docker is not installed (no `docker` or `docker-compose` on the PATH).")


def _quote(s):
    return f'"{s}"' if re.search(r"\s", s) else s


def command(file, service):
    """The command Porthaven runs for a compose service: attached, so its output is captured."""
    return f"docker compose -f {_quote(str(file))} up {service}"


def host_port(spec):
    """'127.0.0.1:5432:5432' / '5432:5432/tcp' / '8000-8001:8000-8001' -> 5432 / 5432 / 8000; '5432' -> None."""
    s = str(spec).strip().strip("'\"").split("/")[0]
    parts = s.split(":")
    if len(parts) < 2:
        return None
    host = parts[-2].split("-")[0]
    return int(host) if host.isdigit() else None


def parse(text):
    """The services of a compose file, read without a YAML library: {service: {ports, healthcheck, image}}.
    Covers the short and long port syntax; `docker compose config` is used instead when Docker is there."""
    services, in_services, svc_indent, cur, key_indent, in_ports, item = {}, False, None, None, None, False, None
    for raw in text.splitlines():
        line = raw.split(" #")[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 0:
            in_services = stripped == "services:"
            cur = None
            continue
        if not in_services:
            continue
        if svc_indent is None:
            svc_indent = indent
        if indent == svc_indent and stripped.endswith(":"):
            cur = stripped[:-1].strip("'\"")
            services[cur] = {"ports": [], "healthcheck": False, "image": None}
            key_indent, in_ports = None, False
            continue
        if cur is None or indent <= svc_indent:
            continue
        if key_indent is None:
            key_indent = indent
        if indent == key_indent:
            in_ports = stripped.startswith("ports:")
            if stripped.startswith("healthcheck:"):
                services[cur]["healthcheck"] = True
            if stripped.startswith("image:"):
                services[cur]["image"] = stripped.split(":", 1)[1].strip().strip("'\"")
            inline = re.match(r"ports:\s*\[(.*)\]", stripped)
            if inline:
                for spec in inline.group(1).split(","):
                    p = host_port(spec)
                    if p:
                        services[cur]["ports"].append(p)
            continue
        if in_ports:
            m = re.match(r"-\s*(.*)", stripped)
            if m:
                item = m.group(1)
                p = host_port(item) if item and ":" in item and not item.startswith(("target", "published")) else None
                if p:
                    services[cur]["ports"].append(p)
                    continue
                stripped = item
            m = re.match(r"published:\s*['\"]?(\d+)", stripped)
            if m:
                services[cur]["ports"].append(int(m.group(1)))
    return services


def services(file):
    """{service: {ports, healthcheck, image}} for a compose file."""
    file = Path(file)
    try:
        out = subprocess.run(cli() + ["-f", str(file), "config", "--format", "json"], capture_output=True, text=True,
                             timeout=15, cwd=str(file.parent))
        if out.returncode == 0:
            doc = json.loads(out.stdout)
            res = {}
            for name, spec in (doc.get("services") or {}).items():
                ports = []
                for p in spec.get("ports") or []:
                    pub = p.get("published") if isinstance(p, dict) else host_port(p)
                    if pub and str(pub).split("-")[0].isdigit():
                        ports.append(int(str(pub).split("-")[0]))
                res[name] = {"ports": ports, "healthcheck": bool(spec.get("healthcheck")) and not (spec.get("healthcheck") or {}).get("disable"),
                             "image": spec.get("image")}
            return res
    except (ComposeError, OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return parse(file.read_text(errors="replace"))


def parse_labels(text):
    out = {}
    for part in (text or "").split(","):
        k, _, v = part.partition("=")
        if k:
            out[k.strip()] = v
    return out


def parse_ps(text):
    """`docker ps --format '{{json .}}'` -> [{id, name, image, status, ports: [{host, mapping}], service, project, workdir}]."""
    out = []
    for line in (text or "").splitlines():
        try:
            c = json.loads(line)
        except ValueError:
            continue
        labels = parse_labels(c.get("Labels"))
        ports = []
        for part in (c.get("Ports") or "").split(","):
            part = part.strip()
            if "->" not in part:
                continue
            host = part.split("->")[0]
            try:
                ports.append({"host": int(host.rsplit(":", 1)[-1].split("-")[0]), "mapping": part})
            except ValueError:
                continue
        out.append({"id": c.get("ID"), "name": c.get("Names"), "image": c.get("Image"), "status": c.get("Status") or "",
                    "ports": ports, "service": labels.get("com.docker.compose.service"),
                    "project": labels.get("com.docker.compose.project"),
                    "workdir": labels.get("com.docker.compose.project.working_dir")})
    return out


def ps(timeout=2.5):
    docker = shutil.which("docker")
    if not docker:
        return None
    try:
        out = subprocess.run([docker, "ps", "--format", "{{json .}}"], capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return parse_ps(out.stdout) if out.returncode == 0 else None


def health(status):
    """'Up 3 seconds (health: starting)' -> 'starting'; '(healthy)' -> 'healthy'; no health check -> None."""
    m = re.search(r"\((?:health: )?(healthy|unhealthy|starting)\)", status or "")
    return m.group(1) if m else None


def container_for(containers, app):
    """The running container of a compose app (matched on its folder and service name)."""
    spec = app.get("compose") or {}
    if not spec.get("service") or not containers:
        return None
    here = os.path.realpath(os.path.expanduser(app["cwd"]))
    for c in containers:
        if c.get("service") == spec["service"] and c.get("workdir") and os.path.realpath(c["workdir"]) == here:
            return c
    return None


def stop(app, timeout=60):
    """`docker compose stop <service>` for a compose app (the container stops cleanly instead of being killed)."""
    spec = app.get("compose") or {}
    file = find_file(app["cwd"], spec.get("file"))
    if not file:
        raise ComposeError(f"No compose file for {app['name']} in {app['cwd']}.")
    out = subprocess.run(cli() + ["-f", str(file), "stop", spec["service"]], capture_output=True, text=True, timeout=timeout,
                         cwd=str(file.parent))
    if out.returncode:
        raise ComposeError(f"docker compose stop {spec['service']} failed: {(out.stderr or out.stdout).strip()[:300]}")
    return True
