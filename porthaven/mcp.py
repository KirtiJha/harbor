"""Model Context Protocol server: lets coding agents (Claude Code, Cursor, Codex, …) see and manage local servers.

    claude mcp add porthaven -- porthaven mcp

Speaks JSON-RPC 2.0 over stdin/stdout (one message per line) and works through a running Porthaven, starting one
if needed, so every guard rail applies and every action appears in Activity as "by agent".
"""
from __future__ import annotations

import json
import sys
import traceback

from . import __version__
from .client import Client, ClientError, ensure_server

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Porthaven manages the local dev servers on this machine. Before starting a server, call list_ports or port_info "
    "to see what is already running; prefer start_app for saved apps (it starts dependencies, picks a free port when "
    "the usual one is taken and keeps logs) over launching processes yourself. Read app_logs after a start or a crash. "
    "Give each git worktree its own instance with run_in_worktree instead of fighting over the same port. stop_port "
    "refuses desktop apps, system services and other users' processes; ask the user to do those in the dashboard. "
    "Servers you start count as this session's: call my_servers before you finish and stop_my_servers for the ones the "
    "user does not need any more, so nothing is left running. service_map shows which services talk to each other, "
    "port_drift finds config files that point at the wrong port, and search_logs searches every app's output."
)


def _schema(props=None, required=()):
    return {"type": "object", "properties": props or {}, "required": list(required), "additionalProperties": False}


APP = {"type": "string", "description": "Saved app: its short name (e.g. api), name or id"}
PORT = {"type": "integer", "minimum": 1, "maximum": 65535}

TOOLS = [
    ("list_ports", "Every listening port: project, framework, page title, HTTP status, uptime, memory, and whether it is "
                   "exposed to the network.", _schema({"query": {"type": "string", "description": "Filter by text or :port"},
                                                         "include_system": {"type": "boolean"}})),
    ("port_info", "What is on one port: process, command, folder, git branch, the app that launched it, HTTP answer, "
                  "exposure warnings.", _schema({"port": PORT}, ["port"])),
    ("list_apps", "Saved apps with state, ports, stable URL, group, dependencies and sleep settings.", _schema()),
    ("start_app", "Start a saved app (its dependencies first, waiting for their health checks). Picks the next free port "
                  "if the saved one is taken.", _schema({"app": APP, "port": PORT}, ["app"])),
    ("stop_app", "Stop a saved app and every process it started.", _schema({"app": APP}, ["app"])),
    ("restart_app", "Restart a saved app on the port it is using.", _schema({"app": APP}, ["app"])),
    ("app_logs", "The latest output of a saved app (Porthaven captures it).",
     _schema({"app": APP, "lines": {"type": "integer", "minimum": 1, "maximum": 500}, "grep": {"type": "string"}}, ["app"])),
    ("stop_port", "Stop what is listening on a port. whole_app also stops the launcher (npm run dev, make dev) so it does "
                  "not respawn.", _schema({"port": PORT, "whole_app": {"type": "boolean"}}, ["port"])),
    ("find_free_ports", "Ports that are free right now.", _schema({"start": PORT, "count": {"type": "integer", "minimum": 1, "maximum": 20}})),
    ("stack_up", "Start every app in a folder's porthaven.toml, dependencies first.", _schema({"path": {"type": "string"}}, ["path"])),
    ("stack_down", "Stop the apps of a folder's porthaven.toml.", _schema({"path": {"type": "string"}}, ["path"])),
    ("run_in_worktree", "Run a saved app from another git worktree on its own port and stable name "
                        "(e.g. feature-x.shop.localhost).", _schema({"app": APP, "worktree": {"type": "string", "description": "Worktree folder"}},
                                                                     ["app", "worktree"])),
    ("recent_requests", "Recent HTTP requests that reached an app through its stable name (method, path, status, time).",
     _schema({"app": APP, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, ["app"])),
    ("recent_activity", "What happened lately: servers starting, stopping, crashing, port conflicts.",
     _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 100}})),
    ("service_map", "Which local services talk to which (live TCP connections and declared dependencies), including "
                    "broken links where a service is gone.", _schema()),
    ("port_drift", "Config files (.env, vite/next configs, compose files) that point at a port where the service they "
                   "mean no longer is, e.g. the API moved from :8000 to :8001.", _schema({"rescan": {"type": "boolean"}})),
    ("port_history", "Who held a port and when (30 days). `at` takes '15:00', 'yesterday 3pm', '2h ago' or an ISO date.",
     _schema({"port": PORT, "at": {"type": "string"}}, ["port"])),
    ("search_logs", "Search the output of every saved app at once (newest first). errors_only keeps lines that look like errors.",
     _schema({"query": {"type": "string"}, "app": APP, "errors_only": {"type": "boolean"}, "regex": {"type": "boolean"},
              "limit": {"type": "integer", "minimum": 1, "maximum": 300}})),
    ("my_servers", "Servers this agent session started (through Porthaven or its own shell), still running.", _schema()),
    ("stop_my_servers", "Stop the servers this agent session started. Use before finishing, for servers the user does not need.",
     _schema({"ports": {"type": "array", "items": PORT, "description": "Only these ports (default: all of this session's servers)"}})),
]


def agent_session():
    """The coding-agent process this MCP server runs under (Claude Code, Codex, …), found by walking up the
    process tree; None when it is not under a known agent."""
    import os
    import time
    from . import agents, system
    try:
        procs = system.processes()
    except system.SystemError_:
        return None
    sess = agents.find_session(os.getpid(), procs, time.time())
    return sess["pid"] if sess else None


class Tools:
    def __init__(self):
        self.session = agent_session()
        self.c = Client("agent", self.session)
        self.started = False

    def _ready(self):
        if not self.started:
            ensure_server()
            self.started = True

    def _app(self, ref):
        apps = self.c.state()["apps"]
        ref_l = str(ref).lower()
        for a in apps:
            if ref_l in (a["id"].lower(), (a.get("slugName") or "").lower(), a["name"].lower()):
                return a
        names = ", ".join(f"{a['name']} ({a.get('slugName')})" for a in apps) or "none saved yet"
        raise ClientError(f"No saved app “{ref}”. Saved apps: {names}.")

    def call(self, name, args):
        self._ready()
        return getattr(self, "t_" + name)(**args)

    # ---------------------------------------------------------------- tools
    def t_list_ports(self, query="", include_system=False):
        rows = self.c.state()["listeners"]
        q = (query or "").lower()
        out = []
        for r in rows:
            if not include_system and r["kind"] in ("system", "app"):
                continue
            text = f":{r['port']} {r['title']} {(r['project'] or {}).get('name', '')} {(r['framework'] or {}).get('label', '')}".lower()
            if q and q not in text and q.lstrip(":") != str(r["port"]):
                continue
            pr = r.get("probe") or {}
            flags = []
            if r["exposure"] == "network":
                flags.append("NETWORK-EXPOSED")
            if (r.get("exposureRisk") or {}).get("level") == "critical":
                flags.append("CRITICAL: " + r["exposureRisk"]["title"])
            if r.get("idleFor"):
                flags.append("idle")
            git = (r.get("project") or {}).get("git") or {}
            out.append(f":{r['port']}  {r['title']}  [{(r['framework'] or {}).get('label', r['kind'])}]  "
                       f"http {pr.get('status') or pr.get('error') or '-'}  pid {r['pid']}  up {r['uptime']}s  {r['memMb']} MB"
                       + (f"  branch {git['branch']}" if git.get("branch") else "")
                       + (f"  app={r['appId']}" if r.get("appId") else "") + (f"  {' '.join(flags)}" if flags else ""))
        return "\n".join(out) or "Nothing is listening" + (" that matches." if q else ".")

    def t_port_info(self, port):
        rows = [r for r in self.c.state()["listeners"] if r["port"] == port]
        if not rows:
            free = self.c.call("GET", f"/api/ports/{port}")
            return f"Port {port} is free." + (f" ({free['hint']} usually uses it.)" if free.get("hint") else "")
        keep = ("port", "pid", "title", "kind", "framework", "project", "cwd", "args", "addresses", "exposure", "exposureRisk",
                "probe", "root", "appId", "managed", "uptime", "memMb", "cpu", "connections", "stableUrl", "workers")
        return json.dumps([{k: r.get(k) for k in keep} for r in rows], indent=1)

    def t_list_apps(self):
        apps = self.c.state()["apps"]
        if not apps:
            return "No saved apps. The user can save one from the dashboard, or add a porthaven.toml and call stack_up."
        return "\n".join(f"{a['name']} (app={a.get('slugName')})  {a['state']}  ports {a['ports'] or '-'}  saved port {a.get('port') or '-'}"
                         f"  {a.get('stableUrl') or ''}  group {a.get('group') or '-'}"
                         + (f"  depends on {', '.join(a['dependsOn'])}" if a.get("dependsOn") else "")
                         + (f"  sleeps after {a['sleepAfter']} min" if a.get("sleepAfter") else "")
                         + (f"  branch {a['branch']}" if a.get("branch") else "") for a in apps)

    def t_start_app(self, app, port=None):
        a = self._app(app)
        try:
            res = self.c.call("POST", f"/api/apps/{a['id']}/start", {"port": port} if port else {})
        except ClientError as err:
            conflict = err.data.get("conflict")
            if conflict and conflict.get("suggest"):
                res = self.c.call("POST", f"/api/apps/{a['id']}/start", {"port": conflict["suggest"], "force": True})
                return (f"Port {conflict['port']} was taken by {(conflict.get('holder') or {}).get('title', 'another process')}, "
                        f"so {a['name']} started on :{conflict['suggest']} (pid {res.get('pid')}). Its stable URL still works: "
                        f"{a.get('stableUrl')}")
            raise
        if "stack" in res:
            return f"Starting the stack in order: {' → '.join(res['stack'])}. Check list_apps or app_logs in a few seconds."
        return f"Started {a['name']} (pid {res.get('pid')}) on :{res.get('port') or '?'}: `{res.get('command')}`. Stable URL: {a.get('stableUrl')}"

    def t_stop_app(self, app):
        a = self._app(app)
        self.c.call("POST", f"/api/apps/{a['id']}/stop", {})
        return f"Stopped {a['name']}."

    def t_restart_app(self, app):
        a = self._app(app)
        res = self.c.call("POST", f"/api/apps/{a['id']}/restart", {})
        return f"Restarting {a['name']} on :{res.get('port')}."

    def t_app_logs(self, app, lines=80, grep=""):
        a = self._app(app)
        got = self.c.call("GET", f"/api/apps/{a['id']}/logs")["lines"]
        import re
        text = [re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", ln["text"]) for ln in got]
        if grep:
            text = [t for t in text if grep.lower() in t.lower()]
        return "\n".join(text[-lines:]) or "No output yet."

    def t_stop_port(self, port, whole_app=False):
        rows = [r for r in self.c.state()["listeners"] if r["port"] == port]
        if not rows:
            return f"Nothing is listening on {port}."
        r = rows[0]
        try:
            res = self.c.call("POST", "/api/kill", {"pid": r["pid"], "mode": "app" if whole_app else "process", "confirm": False})
        except ClientError as err:
            if err.data.get("needsConfirm"):
                return (f":{port} belongs to {'a system service' if err.data['needsConfirm'] == 'system' else 'a desktop app'} "
                        f"({r['title']}). Agents may not stop it; ask the user to stop it in the Porthaven dashboard.")
            raise
        return (f"Stopped {len(res['exited']) + len(res['killed'])} process(es) on :{port}"
                + (f" ({len(res['killed'])} forced)" if res["killed"] else "") + (f"; still running: {res['survivors']}" if res["survivors"] else "") + ".")

    def t_find_free_ports(self, start=3000, count=5):
        return " ".join(map(str, self.c.call("GET", f"/api/free?from={start}&count={count}")["ports"]))

    def t_stack_up(self, path):
        res = self.c.call("POST", "/api/teamfile/up", {"path": path})
        claims = "; ".join(f"port {p} is also expected by {', '.join(n)}" for p, n in (res.get("claims") or {}).items())
        return f"Starting {' → '.join(res['order'])} from {res['file']}." + (f" Warning: {claims}." if claims else "")

    def t_stack_down(self, path):
        res = self.c.call("POST", "/api/teamfile/down", {"path": path})
        return f"Stopped: {', '.join(res['stopped']) or 'nothing was running'}."

    def t_run_in_worktree(self, app, worktree):
        a = self._app(app)
        res = self.c.call("POST", f"/api/apps/{a['id']}/worktree", {"worktree": worktree, "start": True})
        return f"Started {res['app']['name']} from {worktree} on :{res['app'].get('port')}; stable URL {res['app'].get('stableUrl') or res.get('stableUrl')}."

    def t_recent_requests(self, app, limit=30):
        a = self._app(app)
        reqs = self.c.call("GET", f"/api/apps/{a['id']}/requests")["requests"][-limit:]
        return "\n".join(f"{r['method']} {r['path']} → {r.get('status') or '…'} {r.get('ms', '?')} ms" for r in reqs) or \
            f"No requests yet. Requests are recorded when they go through {a.get('stableUrl')}."

    def t_recent_activity(self, limit=20):
        evs = self.c.state()["activity"][-limit:]
        import time
        return "\n".join(f"{time.strftime('%H:%M:%S', time.localtime(e['ts']))} {e['title']} {e['type']}"
                         + (f" :{e['port']}" if e.get("port") else "") + (f" ({e['detail']})" if e.get("detail") else "") for e in evs) or "No activity."


    def t_service_map(self):
        return self.c.call("GET", "/api/map")["text"]

    def t_port_drift(self, rescan=False):
        res = self.c.call("POST", "/api/drift/scan", {}) if rescan else self.c.call("GET", "/api/drift")
        found = res.get("findings") or []
        if not found:
            return "No config file points at a wrong port." + ("" if rescan else " (Pass rescan=true to check again now.)")
        return "\n".join(f"[{f['level']}] {f['title']}\n    {f['file']}:{f['line']}  {f['text']}"
                         + (f"\n    fix: use :{f['fix']['port']}" if f.get("fix") else "") for f in found)

    def t_port_history(self, port, at=""):
        import time
        from urllib.parse import quote
        res = self.c.call("GET", f"/api/ports/{port}/history" + (f"?at={quote(at)}" if at else "?days=7"))
        fmt = lambda t: time.strftime("%a %d %b %H:%M", time.localtime(t)) if t else "now"
        lines = [f"{fmt(iv['start'])} → {fmt(iv['end'])}  {iv.get('title') or iv.get('command') or '?'}"
                 + (f" ({iv['project']})" if iv.get("project") and iv["project"] != iv.get("title") else "") + f"  pid {iv['pid']}"
                 for iv in res["intervals"][:40]]
        head = f"Port {port}" + (f" at {fmt(res['at'])}" if res.get("at") else ", last 7 days") + ":"
        return head + "\n" + ("\n".join(lines) if lines else "  nothing recorded" + (f" (usually {res['hint']})" if res.get("hint") else ""))

    def t_search_logs(self, query="", app=None, errors_only=False, regex=False, limit=80):
        from urllib.parse import urlencode
        params = {"q": query, "errors": "1" if errors_only else "0", "regex": "1" if regex else "0", "limit": limit}
        if app:
            params["apps"] = self._app(app)["id"]
        res = self.c.call("GET", "/api/logs/search?" + urlencode(params))
        import time
        out = [f"{time.strftime('%H:%M:%S', time.localtime(m['t'])) if m['t'] else '        '} [{m['app']}] {m['text']}" for m in res["matches"]]
        return "\n".join(out) or "No matching lines."

    def _mine(self):
        if not self.session:
            raise ClientError("This MCP server is not running under a coding agent Porthaven recognises, so it cannot tell "
                              "which servers are this session's. Use list_ports instead.")
        return [s for s in self.c.call("GET", "/api/agents")["servers"] if s["agent"]["pid"] == self.session]

    def t_my_servers(self):
        mine = self._mine()
        return "\n".join(f":{s['port']}  {s['title']}  pid {s['pid']}  {s['memMb']} MB  {s['connections']} connection(s)" for s in mine) \
            or "This session has no servers running."

    def t_stop_my_servers(self, ports=None):
        mine = self._mine()
        if ports:
            mine = [s for s in mine if s["port"] in set(ports)]
        if not mine:
            return "Nothing of this session's to stop."
        done = []
        for s in {x["pid"]: x for x in mine}.values():
            try:
                if s.get("managed"):
                    self.c.call("POST", f"/api/apps/{s['managed']}/stop", {})
                else:
                    self.c.call("POST", "/api/kill", {"pid": s["pid"], "mode": "app", "confirm": False})
                done.append(f":{s['port']} {s['title']}")
            except ClientError as err:
                done.append(f":{s['port']} {s['title']} NOT stopped: {err}")
        return "Stopped " + "; ".join(done) + "."


def handle(tools, msg):
    """One JSON-RPC message -> a response dict, or None for notifications."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        want = params.get("protocolVersion")
        return _ok(mid, {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                         "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": {"name": "porthaven", "title": "Porthaven", "version": __version__},
                         "instructions": INSTRUCTIONS})
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in {t[0] for t in TOOLS}:
            return _err(mid, -32602, f"Unknown tool {name}")
        try:
            text = tools.call(name, args)
            return _ok(mid, {"content": [{"type": "text", "text": text}], "isError": False})
        except ClientError as err:
            return _ok(mid, {"content": [{"type": "text", "text": str(err)}], "isError": True})
        except TypeError as err:
            return _ok(mid, {"content": [{"type": "text", "text": f"Bad arguments for {name}: {err}"}], "isError": True})
        except Exception as err:   # report, never crash the session
            traceback.print_exc(file=sys.stderr)
            return _ok(mid, {"content": [{"type": "text", "text": f"{name} failed: {err}"}], "isError": True})
    if method in ("resources/list", "prompts/list"):
        return _ok(mid, {method.split("/")[0]: []})
    return _err(mid, -32601, f"Method not found: {method}")


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve_stdio(stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    tools = Tools()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out = _err(None, -32700, "Parse error")
        else:
            out = [r for r in (handle(tools, m) for m in msg) if r] if isinstance(msg, list) else handle(tools, msg)
        if out:
            stdout.write(json.dumps(out) + "\n")
            stdout.flush()
    return 0
