"""Stacks: apps that depend on each other, start in order, wait for health, and find each other's ports.

  dependsOn   ["api", "db"]          other apps (by short name or id) that must be up first
  health      "/health"              path that must answer 2xx/3xx before dependants start ("" = port open is enough)
  {port}      in command or env      this app's port;  {url} its http://localhost URL
  {port:api}  {url:api}              another app's current port / URL (whatever port it is on today)
  PORTHAVEN_<APP>_PORT / _URL        set for every saved app in every launch, so apps can find each other
"""
from __future__ import annotations

import re

PLACEHOLDER = re.compile(r"\{(port|url)(?::([a-z0-9][a-z0-9.-]*))?\}")


class StackError(ValueError):
    pass


def key_of(app, slugs):
    return slugs.get(app["id"]) or app["id"]


def resolve(apps, slugs, ref):
    """An app by id, short name or name (case-insensitive)."""
    ref_l = str(ref).lower()
    for a in apps:
        if a["id"] == ref or slugs.get(a["id"]) == ref_l or (a.get("name") or "").lower() == ref_l:
            return a
    return None


def start_order(apps, slugs, target_ids):
    """Apps to start, dependencies first. Raises StackError on unknown dependencies or cycles."""
    order, seen, visiting = [], set(), []

    def visit(app):
        if app["id"] in seen:
            return
        if app["id"] in visiting:
            cycle = " → ".join(a["name"] for a in [resolve(apps, slugs, i) for i in visiting] + [app])
            raise StackError(f"These apps depend on each other in a circle: {cycle}.")
        visiting.append(app["id"])
        for ref in app.get("dependsOn") or []:
            dep = resolve(apps, slugs, ref)
            if not dep:
                raise StackError(f"{app['name']} depends on “{ref}”, but no saved app has that name.")
            visit(dep)
        visiting.pop()
        seen.add(app["id"])
        order.append(app)

    for tid in target_ids:
        app = resolve(apps, slugs, tid)
        if app:
            visit(app)
    return order


def wiring(apps, slugs, ports):
    """{slug: {"port": p, "url": u}} for every saved app, using the port it runs on now (or its saved port)."""
    out = {}
    for a in apps:
        port = ports.get(a["id"]) or a.get("port")
        if port:
            out[key_of(a, slugs)] = {"port": int(port), "url": f"http://localhost:{int(port)}"}
    return out


def expand(text, port, wired):
    """Fill {port}, {url}, {port:api}, {url:api}. Unknown names are left as they are, so mistakes stay visible."""
    def sub(m):
        kind, name = m.group(1), m.group(2)
        if name is None:
            if not port:
                return m.group(0)
            return str(port) if kind == "port" else f"http://localhost:{port}"
        target = wired.get(name)
        return str(target[kind]) if target else m.group(0)
    return PLACEHOLDER.sub(sub, text or "")


def env_for(wired):
    env = {}
    for slug, w in wired.items():
        name = re.sub(r"[^A-Z0-9]", "_", slug.upper())
        env[f"PORTHAVEN_{name}_PORT"] = str(w["port"])
        env[f"PORTHAVEN_{name}_URL"] = w["url"]
    return env
