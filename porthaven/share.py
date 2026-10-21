"""Sharing a dev server for a while: on the local network (a link and QR code for a phone) or publicly through
cloudflared or ngrok when one of them is installed.

The app keeps listening on 127.0.0.1 only. Porthaven opens a small relay for the share, and the relay lets a
request through only with the share's secret: from the link (?ph=…) the first time, from a cookie after that.
Every share ends on its own after the time chosen, and Activity records when it started and ended.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from . import relay

COOKIE = "porthaven_share"
MAX_MINUTES = 8 * 60
TUNNEL_URL = {"cloudflared": re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com"),
              "ngrok": re.compile(r"https://[a-z0-9.-]+\.ngrok(?:-free)?\.(?:app|io|dev)")}


class ShareError(RuntimeError):
    pass


def tunnels():
    """Tunnel programs found on this machine."""
    return [name for name in ("cloudflared", "ngrok") if shutil.which(name)]


def _handler(share):
    class Relay(BaseHTTPRequestHandler):
        server_version = "Porthaven-share"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _deny(self):
            body = (b"<!doctype html><meta charset=utf-8><title>Porthaven</title><body style='font:15px system-ui;padding:40px'>"
                    b"<h2>This link has ended or is not complete.</h2><p>Ask for a new link.</p>")
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def _handle(self):
            if share.ended:
                return self._deny()
            url = urlparse(self.path)
            q = parse_qs(url.query, keep_blank_values=True)
            given = (q.get("ph") or [None])[0]
            if given is not None:
                if not secrets.compare_digest(given, share.token):
                    return self._deny()
                rest = urlencode([(k, v) for k, vs in q.items() if k != "ph" for v in vs])
                self.send_response(302)
                self.send_header("Location", url.path + (f"?{rest}" if rest else ""))
                self.send_header("Set-Cookie", f"{COOKIE}={share.token}; Path=/; HttpOnly; SameSite=Lax"
                                 + ("; Secure" if share.mode == "public" else ""))
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                return
            cookies = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
            if not secrets.compare_digest(cookies.get(COOKIE, ""), share.token):
                return self._deny()
            share.requests += 1
            share.last = time.time()
            host = f"localhost:{share.port}" if share.mode == "public" else None
            if not relay.forward(self, share.port, proto="https" if share.mode == "public" else "http", host=host,
                                 strip_cookie=COOKIE, capture=False):
                body = f"{share.title} is not answering on port {share.port} right now.".encode()
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _handle

    return Relay


class Share:
    def __init__(self, port, title, mode, minutes, lan_ip):
        self.id = secrets.token_hex(4)
        self.port, self.title, self.mode = port, title, mode
        self.token = secrets.token_urlsafe(18)
        self.started = time.time()
        self.expires = self.started + minutes * 60
        self.requests, self.last, self.ended = 0, None, False
        self.public_url, self.tunnel, self.tunnel_name, self.error = None, None, None, None
        bind = lan_ip if mode == "lan" else "127.0.0.1"
        self.server = ThreadingHTTPServer((bind, 0), _handler(self))
        self.server.daemon_threads = True
        self.relay_port = self.server.server_address[1]
        self.host = bind
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True,
                         name=f"porthaven-share-{self.id}").start()

    @property
    def url(self):
        if self.mode == "lan":
            return f"http://{self.host}:{self.relay_port}/?ph={self.token}"
        return f"{self.public_url}/?ph={self.token}" if self.public_url else None

    def open_tunnel(self, name, timeout=25):
        exe = shutil.which(name)
        if not exe:
            raise ShareError(f"{name} is not installed.")
        target = f"http://127.0.0.1:{self.relay_port}"
        args = ([exe, "tunnel", "--no-autoupdate", "--url", target] if name == "cloudflared"
                else [exe, "http", target, "--log", "stdout", "--log-format", "json"])
        from . import system
        self.tunnel = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       text=True, errors="replace", **system.spawn_options())
        self.tunnel_name = name
        found = threading.Event()
        tail = []

        def read():
            for line in self.tunnel.stdout:
                tail.append(line.strip())
                del tail[:-20]
                if not self.public_url:
                    text = line
                    if name == "ngrok":
                        try:
                            text = json.loads(line).get("url") or ""
                        except ValueError:
                            pass
                    m = TUNNEL_URL[name].search(text)
                    if m:
                        self.public_url = m.group(0)
                        found.set()
            found.set()
        threading.Thread(target=read, daemon=True, name=f"porthaven-tunnel-{self.id}").start()
        found.wait(timeout)
        if not self.public_url:
            self.close()
            last = next((t for t in reversed(tail) if t), "no output")
            raise ShareError(f"{name} did not give a public address within {timeout} s ({last[:200]}).")

    def close(self):
        if self.ended:
            return
        self.ended = True
        if self.tunnel and self.tunnel.poll() is None:
            self.tunnel.terminate()
            try:
                self.tunnel.wait(5)
            except subprocess.TimeoutExpired:
                self.tunnel.kill()
        threading.Thread(target=self._stop_server, daemon=True).start()

    def _stop_server(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        except OSError:
            pass

    def summary(self):
        return {"id": self.id, "port": self.port, "title": self.title, "mode": self.mode, "url": self.url, "relayPort": self.relay_port,
                "host": self.host, "publicUrl": self.public_url, "tunnel": self.tunnel_name, "startedAt": self.started,
                "expiresAt": self.expires, "requests": self.requests, "lastRequest": self.last}


class Shares:
    def __init__(self, on_event=None):
        self.items = {}
        self.lock = threading.Lock()
        self.on_event = on_event or (lambda *a: None)

    def start(self, row, mode, minutes, lan_ip, tunnel=None):
        minutes = max(1, min(MAX_MINUTES, int(minutes or 60)))
        if mode not in ("lan", "public"):
            raise ShareError("A share is either on your network (lan) or public.")
        if mode == "lan" and not lan_ip:
            raise ShareError("This machine has no address on a local network right now (no Wi-Fi or Ethernet?).")
        if mode == "public":
            found = tunnels()
            tunnel = tunnel or (found[0] if found else None)
            if not tunnel or tunnel not in found:
                raise ShareError("A public link needs cloudflared or ngrok. Install one (brew install cloudflared) and try again.")
        share = Share(row["port"], row["title"], mode, minutes, lan_ip)
        if mode == "public":
            try:
                share.open_tunnel(tunnel)
            except ShareError:
                share.close()
                raise
        with self.lock:
            self.items[share.id] = share
        self.on_event("shared", share)
        return share

    def stop(self, share_id, why=None):
        with self.lock:
            share = self.items.pop(share_id, None)
        if not share:
            return None
        share.close()
        self.on_event("unshared", share, why)
        return share

    def tick(self, listening_ports):
        """End shares that ran out of time, or whose app stopped listening."""
        now = time.time()
        for s in list(self.items.values()):
            if now >= s.expires:
                self.stop(s.id, "time is up")
            elif s.port not in listening_ports and now - s.started > 10:
                self.stop(s.id, f"nothing listens on :{s.port} any more")
            elif s.tunnel and s.tunnel.poll() is not None:
                self.stop(s.id, f"{s.tunnel_name} exited")

    def stop_all(self):
        for sid in list(self.items):
            self.stop(sid, "Porthaven stopped")

    def summaries(self):
        return [s.summary() for s in self.items.values()]

    def relay_ports(self):
        return {s.relay_port: s for s in self.items.values()}
