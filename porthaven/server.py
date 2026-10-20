"""Porthaven's local web server: the UI, a JSON API and live updates (server-sent events).

It listens on 127.0.0.1 only. Because a web page on any site can send requests to localhost, every
request must carry Porthaven's own Host header (blocks DNS rebinding) and every change must carry the
session token that only Porthaven's own page can read.
"""
from __future__ import annotations

import html
import json
import mimetypes
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .control import ControlError

WEB = Path(__file__).resolve().parent.parent / "web" / "dist"
MAX_BODY = 256 * 1024


class Api:
    def __init__(self, porthaven, token):
        self.local = threading.local()
        self.h = porthaven
        self.token = token
        self.routes = []
        r = self.route
        r("GET", r"/api/state", lambda q, b: self.h.snapshot or self.h.build())
        r("GET", r"/api/session", lambda q, b: {"token": self.token})
        r("POST", r"/api/refresh", self.refresh)
        r("POST", r"/api/kill", lambda q, b: self.h.kill(int(b["pid"]), b.get("mode", "process"), bool(b.get("force", True)),
                                                       bool(b.get("confirm")), actor=self.actor))
        r("POST", r"/api/restart", lambda q, b: self.h.restart_process(int(b["pid"])))
        r("POST", r"/api/probe/(\d+)", lambda q, b, port: self.h.probe_now(int(port)))
        r("GET", r"/api/ports/(\d+)", lambda q, b, port: self.h.check_port(self._port(port)))
        r("PUT", r"/api/ports/(\d+)", self.update_port)
        r("GET", r"/api/free", lambda q, b: {"ports": self.h.free(self._port(q.get("from", ["3000"])[0]), min(20, int(q.get("count", ["5"])[0])))})
        r("GET", r"/api/process/(\d+)", lambda q, b, pid: self.h.process_detail(int(pid)))
        r("POST", r"/api/apps", self.create_app)
        r("POST", r"/api/apps/from-process", lambda q, b: self.h.app_from_process(int(b["pid"]), b.get("name")))
        r("PUT", r"/api/apps/(\w+)", self.update_app)
        r("DELETE", r"/api/apps/(\w+)", self.delete_app)
        r("POST", r"/api/apps/(\w+)/start", lambda q, b, i: self.h.start_app(i, b.get("port"), bool(b.get("force")), bool(b.get("takeOver")),
                                                                         actor=self.actor))
        r("POST", r"/api/apps/(\w+)/stop", lambda q, b, i: self.h.stop_app(i))
        r("POST", r"/api/apps/(\w+)/restart", lambda q, b, i: self.h.restart_app(i))
        r("GET", r"/api/apps/(\w+)/logs", self.logs)
        r("POST", r"/api/apps/(\w+)/logs/clear", self.clear_logs)
        r("POST", r"/api/discover", lambda q, b: self.h.discover(b.get("folder") or "~", min(5, int(b.get("depth", 3)))))
        r("POST", r"/api/reveal", lambda q, b: self.h.reveal(b["path"], b.get("target", "finder")))
        r("POST", r"/api/docker/stop", lambda q, b: self.h.docker_stop(b["id"]))
        r("PUT", r"/api/settings", lambda q, b: self.h.store.update_settings(b))
        r("POST", r"/api/kill-many", lambda q, b: self.h.kill_many([int(p) for p in b["pids"]][:100], b.get("mode", "process")))
        r("POST", r"/api/groups/(start|stop)", lambda q, b, action: self.h.group_action(str(b["group"]), action))
        r("GET", r"/api/apps/export", lambda q, b: self.h.export_apps())
        r("GET", r"/api/apps/(\w+)/requests", lambda q, b, i: self.h.app_requests(i))
        r("GET", r"/api/apps/(\w+)/worktrees", lambda q, b, i: self.h.app_worktrees(i))
        r("POST", r"/api/apps/(\w+)/worktree", lambda q, b, i: self.h.run_in_worktree(i, b["worktree"], bool(b.get("start", True)), actor=self.actor))
        r("POST", r"/api/workspaces", lambda q, b: self.h.save_workspace(b.get("name")))
        r("POST", r"/api/workspaces/(\w+)/restore", lambda q, b, i: self.h.restore_workspace(i, bool(b.get("stopOthers")), actor=self.actor))
        r("DELETE", r"/api/workspaces/(\w+)", lambda q, b, i: self.h.delete_workspace(i))
        r("POST", r"/api/teamfile/import", lambda q, b: self.h.import_teamfile(b["path"]))
        r("POST", r"/api/teamfile/up", lambda q, b: self.h.teamfile_up(b["path"], actor=self.actor))
        r("POST", r"/api/teamfile/down", lambda q, b: self.h.teamfile_down(b["path"]))
        r("GET", r"/api/teamfile/export", lambda q, b: self.h.export_teamfile(q.get("group", [None])[0], q.get("folder", [None])[0]))
        r("GET", r"/api/insights", lambda q, b: self.h.insights(q.get("range", ["24h"])[0]))
        r("POST", r"/api/apps/import", lambda q, b: self.h.import_apps(b["apps"] if isinstance(b.get("apps"), list) else []))
        r("POST", r"/api/activity/clear", self.clear_activity)

    @property
    def actor(self):
        """Who made the request, when a client says so (the MCP server sends "agent")."""
        return getattr(self.local, "actor", None)

    def route(self, method, pattern, fn):
        self.routes.append((method, re.compile(f"^{pattern}$"), fn))

    @staticmethod
    def _port(v):
        p = int(v)
        if not 1 <= p <= 65535:
            raise ControlError(f"{p} is not a port number (1-65535).")
        return p

    def refresh(self, q, b):
        self.h.refresh()
        return self.h.snapshot

    def update_port(self, q, b, port):
        meta = self.h.store.update_port(self._port(port), b)
        self.h._publish()
        return meta

    def _clean_app(self, b, partial=False):
        out = {}
        for k in ("name", "cwd", "command", "openPath", "group", "color", "slug"):
            if k in b:
                out[k] = str(b[k] or "").strip()
        if out.get("slug") and not re.match(r"^[a-z0-9][a-z0-9-]{0,39}$", out["slug"]):
            raise ControlError("A short name may use lowercase letters, digits and dashes (e.g. shop-web).")
        if "port" in b:
            out["port"] = self._port(b["port"]) if b["port"] not in (None, "") else None
        if "env" in b:
            if not isinstance(b["env"], dict):
                raise ControlError("env must be an object of NAME: value.")
            out["env"] = {str(k): str(v) for k, v in b["env"].items() if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(k))}
        if "autoRestart" in b:
            out["autoRestart"] = bool(b["autoRestart"])
        if "dependsOn" in b:
            deps = b["dependsOn"] or []
            if isinstance(deps, str):
                deps = [d.strip() for d in deps.split(",")]
            out["dependsOn"] = [str(d).strip() for d in deps if str(d).strip()][:20]
        if "health" in b:
            h = str(b["health"] or "").strip()
            if h and not h.startswith("/"):
                raise ControlError("A health check is a path such as /health.")
            out["health"] = h
        if "sleepAfter" in b:
            out["sleepAfter"] = max(0, min(24 * 60, int(b["sleepAfter"] or 0)))
        if "wake" in b:
            out["wake"] = bool(b["wake"])
        if not partial:
            for k in ("name", "cwd", "command"):
                if not out.get(k):
                    raise ControlError(f"An app needs a {k}.")
        if out.get("cwd") and not Path(out["cwd"]).expanduser().is_dir():
            raise ControlError(f"The folder {out['cwd']} does not exist.")
        return out

    def create_app(self, q, b):
        app = self.h.store.upsert_app(self._clean_app(b))
        self.h._publish()
        return app

    def update_app(self, q, b, app_id):
        app = self.h.store.upsert_app(self._clean_app(b, partial=True), app_id)
        if not app:
            raise ControlError("No such app.", status=404)
        self.h._publish()
        return app

    def delete_app(self, q, b, app_id):
        m = self.h.managed.get(app_id)
        if m and m.alive:
            raise ControlError("Stop the app before removing it.", status=409)
        if not self.h.store.delete_app(app_id):
            raise ControlError("No such app.", status=404)
        self.h.managed.pop(app_id, None)
        self.h._publish()
        return {"deleted": app_id}

    def logs(self, q, b, app_id):
        m = self.h.managed.get(app_id)
        after = int(q.get("after", ["0"])[0])
        if m:
            return {"lines": m.tail(after), "seq": m.seq, "live": m.alive}
        path = self.h.store.log_path(app_id)
        if path.exists():
            text = path.read_text(errors="replace").splitlines()[-1000:]
            return {"lines": [{"seq": i + 1, "t": None, "text": t, "stream": "file"} for i, t in enumerate(text)],
                    "seq": len(text), "live": False}
        return {"lines": [], "seq": 0, "live": False}

    def clear_logs(self, q, b, app_id):
        m = self.h.managed.get(app_id)
        if m:
            with m.cond:
                m.lines.clear()
        path = self.h.store.log_path(app_id)
        if path.exists():
            path.write_text("")
        return {"cleared": app_id}

    def clear_activity(self, q, b):
        self.h.store.data["activity"] = []
        self.h.store.save()
        self.h._publish()
        return {"cleared": True}

    def dispatch(self, method, path, query, body):
        for m, rx, fn in self.routes:
            if m == method:
                match = rx.match(path)
                if match:
                    return fn(query, body, *match.groups())
        raise ControlError(f"No API route {method} {path}.", status=404)


def make_handler(api, porthaven, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    proxy_host = re.compile(rf"^([a-z0-9][a-z0-9.-]*)\.localhost:{port}$")

    class Handler(BaseHTTPRequestHandler):
        server_version = "Porthaven"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):   # quiet: the UI shows activity
            pass

        def _send(self, status, payload, ctype="application/json"):
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def _guard(self, mutating):
            if self.headers.get("Host") not in allowed_hosts:
                self._send(403, {"error": "Porthaven only answers requests addressed to localhost."})
                return False
            if mutating and not secrets.compare_digest(self.headers.get("X-Porthaven-Token", ""), api.token):
                self._send(403, {"error": "Missing or wrong Porthaven session token. Reload the Porthaven page."})
                return False
            return True

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ControlError("Request too large.", status=413)
            if not n:
                return {}
            try:
                body = json.loads(self.rfile.read(n))
            except ValueError as err:
                raise ControlError(f"Request body is not JSON: {err}.") from err
            if not isinstance(body, dict):
                raise ControlError("Request body must be a JSON object.")
            return body

        def _api(self, method):
            url = urlparse(self.path)
            if not self._guard(method != "GET"):
                return
            try:
                body = self._body() if method != "GET" else {}
                actor = re.sub(r"[^A-Za-z0-9 ()._-]", "", self.headers.get("X-Porthaven-Actor", ""))[:40]
                api.local.actor = actor or None
                result = api.dispatch(method, url.path, parse_qs(url.query), body)
                self._send(200, result if result is not None else {})
            except ControlError as err:
                self._send(err.status, {"error": str(err), **err.extra})
            except (KeyError, ValueError, TypeError) as err:
                self._send(400, {"error": f"Bad request: {err}."})
            except FileNotFoundError as err:
                self._send(404, {"error": str(err)})

        def _proxied(self):
            m = proxy_host.match((self.headers.get("Host") or "").lower())
            if not m:
                return False
            self._proxy(m.group(1))
            return True

        def _proxy(self, slug):
            """http://<name>.localhost:<porthaven port>/ → the app's current port. A raw tunnel, so websockets
            (hot reload) and streaming work. Each plain HTTP request gets its own upstream connection, so the
            request inspector sees every request; an app that sleeps is woken by the request and then served."""
            target, name, app_id = porthaven.proxy_target(slug)
            if not target and app_id:
                target = porthaven.wake_app(app_id)
            if not target or target == port:
                page = (f"<!doctype html><meta charset=utf-8><title>{html.escape(slug)} · Porthaven</title><body style='font:15px system-ui;"
                        f"background:#080b12;color:#d6deeb;padding:48px'><h2>Nothing called “{html.escape(slug)}” is running.</h2>"
                        f"<p>Start it from <a style='color:#5eead4' href='http://localhost:{port}/'>Porthaven</a> and reload this page.</p>")
                return self._send(502, page.encode(), "text/html; charset=utf-8")
            upstream = None
            for host in ("127.0.0.1", "::1"):
                try:
                    upstream = socket.create_connection((host, target), timeout=5)
                    break
                except OSError:
                    continue
            if not upstream:
                return self._send(502, f"{name or slug} is not accepting connections on port {target}.".encode(), "text/plain")
            upstream.settimeout(None)
            websocket = "upgrade" in (self.headers.get("Connection") or "").lower()
            head = f"{self.command} {self.path} {self.request_version}\r\n"
            for k, v in self.headers.items():
                if not websocket and k.lower() in ("connection", "keep-alive"):
                    continue
                head += f"{k}: {v}\r\n"
            if not websocket:
                head += "Connection: close\r\n"
            head += f"X-Forwarded-Host: {self.headers.get('Host')}\r\nX-Forwarded-Proto: http\r\n\r\n"
            self.close_connection = True
            started = time.monotonic()
            entry = {"t": time.time(), "method": self.command, "path": self.path[:300], "status": None, "ms": None,
                     "bytes": 0, "ws": websocket, "port": target}
            try:
                upstream.sendall(head.encode("latin-1"))
            except OSError:
                upstream.close()
                return

            def client_to_upstream():
                try:
                    while True:
                        chunk = self.rfile.read1(65536)
                        if not chunk:
                            break
                        upstream.sendall(chunk)
                except OSError:
                    pass
                finally:
                    try:
                        upstream.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass

            threading.Thread(target=client_to_upstream, daemon=True).start()
            first = True
            try:
                while True:
                    chunk = upstream.recv(65536)
                    if not chunk:
                        break
                    if first:
                        first = False
                        m = re.match(rb"HTTP/\d(?:\.\d)? (\d{3})", chunk)
                        entry["status"] = int(m.group(1)) if m else None
                        entry["ttfb"] = round((time.monotonic() - started) * 1000)
                        if websocket:   # record the upgrade now; the socket may stay open for hours
                            entry["ms"] = entry["ttfb"]
                            porthaven.record_request(slug, app_id, dict(entry))
                    entry["bytes"] += len(chunk)
                    self.connection.sendall(chunk)
            except OSError:
                pass
            finally:
                upstream.close()
                if not websocket:
                    entry["ms"] = round((time.monotonic() - started) * 1000)
                    porthaven.record_request(slug, app_id, entry)

        def do_GET(self):
            if self._proxied():
                return
            path = urlparse(self.path).path
            if path == "/api/stream":
                return self._stream()
            if re.match(r"^/api/apps/\w+/logs/stream$", path):
                return self._log_stream(path.split("/")[3])
            if path.startswith("/api/"):
                return self._api("GET")
            if not self._guard(False):
                return
            self._static(path)

        def do_POST(self):
            if not self._proxied():
                self._api("POST")

        def do_PUT(self):
            if not self._proxied():
                self._api("PUT")

        def do_DELETE(self):
            if not self._proxied():
                self._api("DELETE")

        def do_PATCH(self):
            self._proxied() or self._send(405, {"error": "Method not allowed."})

        def do_OPTIONS(self):
            self._proxied() or self._send(405, {"error": "Method not allowed."})

        def do_HEAD(self):
            self._proxied() or self._send(405, {"error": "Method not allowed."})

        def _static(self, path):
            if path in ("/welcome", "/about"):
                path = "/welcome.html"
            target = (WEB / path.lstrip("/")).resolve()
            if path in ("", "/") or not target.is_file() or WEB not in target.parents:
                target = WEB / "index.html"
            if not target.exists():
                return self._send(200, NO_BUILD.encode(), "text/html; charset=utf-8")
            data = target.read_bytes()
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if target.suffix == ".webmanifest":
                ctype = "application/manifest+json"
            if target.name == "index.html" and target.parent == WEB:
                data = data.replace(b"</head>", f'<meta name="porthaven-token" content="{api.token}"></head>'.encode(), 1)
                ctype = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            hashed = target.parent.name == "assets"   # Vite's fingerprinted bundles never change
            self.send_header("Cache-Control", "public, max-age=31536000, immutable" if hashed else "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                                        "connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def _sse_start(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.close_connection = True

        def _sse(self, event, data):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()

        def _stream(self):
            if not self._guard(False):
                return
            self._sse_start()
            porthaven.clients += 1
            porthaven.wake.set()
            try:
                seen = -1
                while True:
                    with porthaven.changed:
                        if porthaven.version == seen:
                            porthaven.changed.wait(15)
                        version, snap, events = porthaven.version, porthaven.snapshot, porthaven.last_events
                    if version != seen:
                        if seen >= 0 and events:
                            self._sse("events", events)
                        self._sse("snapshot", snap)
                        seen = version
                    else:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                porthaven.clients -= 1

        def _log_stream(self, app_id):
            if not self._guard(False):
                return
            self._sse_start()
            after = int((parse_qs(urlparse(self.path).query).get("after") or ["0"])[0])
            try:
                while True:
                    m = porthaven.managed.get(app_id)
                    if not m:
                        self.wfile.write(b": waiting\n\n")
                        self.wfile.flush()
                        time.sleep(1)
                        continue
                    if after > m.seq:
                        after = 0   # a new run started
                    with m.cond:
                        if m.seq <= after:
                            m.cond.wait(15)
                        lines = [ln for ln in m.lines if ln["seq"] > after]
                    if lines:
                        after = lines[-1]["seq"]
                        self._sse("lines", {"lines": lines[-500:], "live": m.alive})
                    else:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                    if porthaven.managed.get(app_id) is not m:
                        after = 0
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    return Handler


NO_BUILD = """<!doctype html><meta charset=utf-8><title>Porthaven</title>
<body style="font:15px system-ui;background:#0b0f17;color:#d6deeb;padding:48px">
<h1>Porthaven is running, but its web UI is not built yet.</h1>
<p>Run <code>make -C porthaven build</code> (or <code>cd porthaven/web && npm install && npm run build</code>) and reload.</p>
<p>The API is live: <a style="color:#7dd3fc" href="/api/state">/api/state</a></p>"""


class _Server6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def serve(porthaven, port, host="127.0.0.1", ready=None):
    token = secrets.token_urlsafe(24)
    api = Api(porthaven, token)
    handler = make_handler(api, porthaven, port)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    # Browsers may try localhost over IPv6 (::1) first; answer there too, still loopback only.
    httpd6 = None
    if host == "127.0.0.1" and socket.has_ipv6:
        try:
            httpd6 = _Server6(("::1", port), handler)
            httpd6.daemon_threads = True
            threading.Thread(target=httpd6.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True,
                             name="porthaven-http6").start()
        except OSError:
            httpd6 = None
    porthaven.port = port
    # Answer straight away; the first scan of the machine can take a few seconds on a busy or slow machine.
    threading.Thread(target=porthaven.start, daemon=True, name="porthaven-first-scan").start()
    if ready:
        threading.Timer(0.3, ready).start()
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        if httpd6:
            httpd6.shutdown()
            httpd6.server_close()
    return httpd
