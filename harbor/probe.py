"""Asking a port what it serves: HTTP status, page title, server header and response time."""
from __future__ import annotations

import html
import os
import http.client
import re
import socket
import time

TITLE = re.compile(rb"<title[^>]*>(.*?)</title>", re.I | re.S)
APP_NAME = re.compile(rb'<meta[^>]+(?:name|property)=["\'](?:application-name|og:site_name|apple-mobile-web-app-title)["\'][^>]+content=["\']([^"\']+)', re.I)


def probe(port, host=None, timeout=1.5, path="/"):
    """Ask over IPv4 first, then IPv6: servers that bind `localhost` (Vite, Node 18+) often listen on ::1 only."""
    if host:
        return _probe(port, host, timeout, path)
    first = _probe(port, "127.0.0.1", timeout, path)
    if first.get("ok") or first.get("error") != "refused":
        return first
    second = _probe(port, "::1", timeout, path)
    return second if second.get("ok") else first


def _probe(port, host, timeout, path):
    started = time.monotonic()
    result = {"port": port, "url": f"http://localhost:{port}{path}", "checkedAt": time.time()}
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path, headers={"User-Agent": "Harbor/1.0 (local port manager)", "Accept": "text/html,*/*"})
        resp = conn.getresponse()
        body = resp.read(65536)
        result.update({"ok": True, "status": resp.status, "reason": resp.reason, "server": resp.getheader("Server"),
                       "contentType": (resp.getheader("Content-Type") or "").split(";")[0] or None,
                       "location": resp.getheader("Location"), "ms": round((time.monotonic() - started) * 1000)})
        m = APP_NAME.search(body) or TITLE.search(body)
        if m:
            title = html.unescape(m.group(1).decode("utf-8", "replace")).strip()
            result["title"] = re.sub(r"\s+", " ", title)[:120] or None
        if resp.getheader("x-powered-by"):
            result["poweredBy"] = resp.getheader("x-powered-by")
    except (http.client.HTTPException, ConnectionError, socket.timeout, OSError) as err:
        result.update({"ok": False, "error": _reason(err), "ms": round((time.monotonic() - started) * 1000)})
    finally:
        conn.close()
    return result


def _reason(err):
    if isinstance(err, socket.timeout):
        return "no answer (timed out)"
    if isinstance(err, http.client.BadStatusLine) or isinstance(err, http.client.RemoteDisconnected):
        return "not HTTP"
    if isinstance(err, ConnectionRefusedError):
        return "refused"
    return type(err).__name__


def port_free(port, host="127.0.0.1"):
    """True when nothing accepts connections on the port and it can be bound."""
    for family, addr in ((socket.AF_INET, host), (socket.AF_INET6, "::1")):
        try:
            s = socket.socket(family, socket.SOCK_STREAM)
        except OSError:
            continue
        try:
            s.settimeout(0.2)
            if s.connect_ex((addr, port)) == 0:
                return False
        finally:
            s.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Servers set SO_REUSEADDR, so a port whose old connections linger in TIME_WAIT is free to them.
        if os.name != "nt":   # on Windows SO_REUSEADDR would let us bind a port that is in use
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def free_ports(start, count=5, used=(), limit=65535):
    out, port = [], max(1, start)
    while len(out) < count and port <= limit:
        if port not in used and port_free(port):
            out.append(port)
        port += 1
    return out
