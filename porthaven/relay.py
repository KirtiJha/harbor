"""Forwarding one HTTP request (or websocket) from Porthaven's server to a local app, used by stable names and by
shared links. A raw tunnel, so websockets (hot reload) and streaming work; the first part of the request and of the
answer is kept so the request inspector can show, replay and export it.
"""
from __future__ import annotations

import base64
import itertools
import re
import select
import socket
import ssl
import threading
import time
import zlib

CAPTURE = 32 * 1024          # bytes of each request body and answer kept for the inspector
IDS = itertools.count(1)
HOP = {"connection", "keep-alive", "proxy-connection", "te", "trailer", "upgrade", "transfer-encoding", "content-length"}


def connect(port, timeout=5):
    for host in ("127.0.0.1", "::1"):
        try:
            return socket.create_connection((host, port), timeout=timeout)
        except OSError:
            continue
    return None


def forward(handler, port, proto="http", host=None, strip_cookie=None, capture=True, record=None):
    """Send the request `handler` is answering to 127.0.0.1:port and stream the answer back.

    host          replaces the Host header (a public link's host name is not one the dev server accepts)
    strip_cookie  a cookie name to remove before the app sees the request (the shared link's pass)
    record        called with the entry once the exchange is over (for a websocket: once it is upgraded)
    Returns False when the app could not be reached (nothing has been sent to the client yet).
    """
    upstream = connect(port)
    if not upstream:
        return False
    upstream.settimeout(None)
    websocket = "upgrade" in (handler.headers.get("Connection") or "").lower()
    head = f"{handler.command} {handler.path} {handler.request_version}\r\n"
    req_headers = []
    for k, v in handler.headers.items():
        lk = k.lower()
        if not websocket and lk in ("connection", "keep-alive"):
            continue
        if lk == "host" and host:
            v = host
        if lk == "cookie" and strip_cookie:
            v = "; ".join(c for c in v.split(";") if c.strip().split("=", 1)[0] != strip_cookie)
            if not v.strip():
                continue
        head += f"{k}: {v}\r\n"
        req_headers.append([k, v])
    if not websocket:
        head += "Connection: close\r\n"
    head += f"X-Forwarded-Host: {handler.headers.get('Host')}\r\nX-Forwarded-Proto: {proto}\r\n\r\n"
    handler.close_connection = True
    started = time.monotonic()
    entry = {"id": next(IDS), "t": time.time(), "method": handler.command, "path": handler.path[:2000], "status": None, "ms": None,
             "bytes": 0, "ws": websocket, "port": port, "_reqHeaders": req_headers, "_reqBody": b"", "_resp": b""}
    try:
        upstream.sendall(head.encode("latin-1"))
    except OSError:
        upstream.close()
        return True
    state = {"first": True}

    def to_client(chunk):
        if state["first"]:
            state["first"] = False
            m = re.match(rb"HTTP/\d(?:\.\d)? (\d{3})", chunk)
            entry["status"] = int(m.group(1)) if m else None
            entry["ttfb"] = round((time.monotonic() - started) * 1000)
            if websocket:   # record the upgrade now; the socket may stay open for hours
                entry["ms"] = entry["ttfb"]
                entry["_resp"] = chunk[:CAPTURE]
                if record:
                    record(dict(entry))
        if capture and not websocket and len(entry["_resp"]) < CAPTURE + 8192:
            entry["_resp"] += chunk[:CAPTURE + 8192 - len(entry["_resp"])]
        entry["bytes"] += len(chunk)
        handler.connection.sendall(chunk)

    def to_upstream(chunk):
        if capture and not websocket and len(entry["_reqBody"]) < CAPTURE:
            entry["_reqBody"] += chunk[:CAPTURE - len(entry["_reqBody"])]
        upstream.sendall(chunk)

    try:
        chunked = "chunked" in (handler.headers.get("Transfer-Encoding") or "").lower()
        if isinstance(handler.connection, ssl.SSLSocket) and not chunked:
            _pump_one_thread(handler, upstream, websocket, to_client, to_upstream)
        else:
            _pump_two_threads(handler, upstream, to_client, to_upstream)
    except OSError:
        pass
    finally:
        upstream.close()
        if not websocket:
            entry["ms"] = round((time.monotonic() - started) * 1000)
            if record:
                record(entry)
    return True


def _pump_two_threads(handler, upstream, to_client, to_upstream):
    """Plain sockets: the request body (or websocket frames) flows up in a thread while the answer flows down."""
    def client_to_upstream():
        try:
            while True:
                chunk = handler.rfile.read1(65536)
                if not chunk:
                    break
                to_upstream(chunk)
        except OSError:
            pass
        finally:
            try:
                upstream.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    threading.Thread(target=client_to_upstream, daemon=True).start()
    while True:
        chunk = upstream.recv(65536)
        if not chunk:
            break
        to_client(chunk)


def _pump_one_thread(handler, upstream, websocket, to_client, to_upstream):
    """TLS: an SSL socket must not be read and written from two threads at once, so one thread does both. The
    request body is sent first (its length is known), then the answer is streamed; a websocket is relayed both
    ways with select()."""
    left = int(handler.headers.get("Content-Length") or 0)
    while left > 0:
        chunk = handler.rfile.read(min(65536, left))
        if not chunk:
            break
        left -= len(chunk)
        to_upstream(chunk)
    if not websocket:
        upstream.shutdown(socket.SHUT_WR)
        while True:
            chunk = upstream.recv(65536)
            if not chunk:
                return
            to_client(chunk)
    client = handler.connection
    while True:
        ready = [client] if client.pending() else select.select([client, upstream], [], [], 300)[0]
        if not ready:
            return
        for sock in ready:
            try:
                chunk = sock.recv(65536)
            except ssl.SSLWantReadError:
                continue
            if not chunk:
                return
            (to_upstream if sock is client else to_client)(chunk)


# ---------------------------------------------------------------- reading what was captured

def split_response(raw):
    """Raw bytes of an answer -> (status, reason, [[name, value]], body bytes)."""
    head, sep, body = raw.partition(b"\r\n\r\n")
    if not sep:
        return None, "", [], b""
    lines = head.decode("latin-1").split("\r\n")
    m = re.match(r"HTTP/\S+ (\d{3}) ?(.*)", lines[0])
    headers = [[k.strip(), v.strip()] for k, _, v in (ln.partition(":") for ln in lines[1:]) if k]
    return (int(m.group(1)) if m else None), (m.group(2) if m else ""), headers, body


def header(headers, name):
    name = name.lower()
    return next((v for k, v in headers if k.lower() == name), None)


def dechunk(data):
    out, rest = b"", data
    while rest:
        line, sep, rest = rest.partition(b"\r\n")
        if not sep:
            break
        try:
            n = int(line.split(b";")[0], 16)
        except ValueError:
            break
        if n == 0:
            break
        out += rest[:n]
        rest = rest[n + 2:]
    return out


def body_view(body, headers, truncated=False):
    """{text} for readable bodies, {base64} otherwise, after undoing chunking and gzip where possible."""
    if (header(headers, "transfer-encoding") or "").lower() == "chunked":
        body = dechunk(body)
    enc = (header(headers, "content-encoding") or "").lower()
    note = None
    if enc in ("gzip", "deflate"):
        try:
            body = zlib.decompressobj(wbits=47 if enc == "gzip" else 15).decompress(body)
        except zlib.error:
            note = f"{enc}-compressed" + (" (only the start was kept)" if truncated else "")
    elif enc:
        note = f"{enc}-compressed"
    out = {"size": len(body), "truncated": truncated, "note": note}
    if not body:
        return out
    try:
        if note:
            raise UnicodeDecodeError("x", b"", 0, 1, "compressed")
        out["text"] = body.decode("utf-8")
    except UnicodeDecodeError:
        out["base64"] = base64.b64encode(body).decode()
    return out


def public(entry):
    """An entry without the captured bytes, for lists."""
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def detail(entry):
    """An entry with its headers and bodies, ready for the inspector."""
    status, reason, headers, body = split_response(entry.get("_resp") or b"")
    req_body = entry.get("_reqBody") or b""
    return {**public(entry), "reason": reason, "requestHeaders": entry.get("_reqHeaders") or [],
            "requestBody": body_view(req_body, entry.get("_reqHeaders") or [], len(req_body) >= CAPTURE),
            "responseHeaders": headers,
            "responseBody": body_view(body, headers, entry.get("_truncated", (entry.get("bytes") or 0) > len(entry.get("_resp") or b"")))}


def har(entries, creator_version):
    """HTTP Archive 1.2 of captured entries (what a browser's network tab imports)."""
    out = []
    for e in entries:
        d = detail(e)
        host = header(d["requestHeaders"], "host") or f"localhost:{e['port']}"
        url = f"http://{host}{e['path']}"
        rb, sb = d["requestBody"], d["responseBody"]
        item = {
            "startedDateTime": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(e["t"])) + f".{int(e['t'] % 1 * 1000):03d}Z",
            "time": e.get("ms") or 0,
            "request": {"method": e["method"], "url": url, "httpVersion": "HTTP/1.1",
                        "headers": [{"name": k, "value": v} for k, v in d["requestHeaders"]],
                        "queryString": [{"name": k, "value": v} for k, _, v in (q.partition("=") for q in (e["path"].partition("?")[2]).split("&") if q)],
                        "cookies": [], "headersSize": -1, "bodySize": rb["size"]},
            "response": {"status": e.get("status") or 0, "statusText": d["reason"], "httpVersion": "HTTP/1.1",
                         "headers": [{"name": k, "value": v} for k, v in d["responseHeaders"]], "cookies": [],
                         "content": {"size": sb["size"], "mimeType": header(d["responseHeaders"], "content-type") or "",
                                     **({"text": sb["text"]} if "text" in sb else {"text": sb["base64"], "encoding": "base64"} if "base64" in sb else {})},
                         "redirectURL": header(d["responseHeaders"], "location") or "", "headersSize": -1, "bodySize": e.get("bytes") or 0},
            "cache": {}, "timings": {"send": 0, "wait": e.get("ttfb") or 0, "receive": max(0, (e.get("ms") or 0) - (e.get("ttfb") or 0))},
        }
        if rb["size"]:
            item["request"]["postData"] = {"mimeType": header(d["requestHeaders"], "content-type") or "",
                                           **({"text": rb["text"]} if "text" in rb else {"text": rb.get("base64", ""), "encoding": "base64"})}
        out.append(item)
    return {"log": {"version": "1.2", "creator": {"name": "Porthaven", "version": creator_version}, "entries": out}}


def send(port, method, path, headers, body, timeout=30):
    """Send one request straight to an app (a replay). Returns an entry like the proxy's, with the answer captured."""
    import http.client
    started = time.monotonic()
    entry = {"id": next(IDS), "t": time.time(), "method": method, "path": path, "status": None, "ms": None, "bytes": 0,
             "ws": False, "port": port, "replay": True, "_reqHeaders": headers, "_reqBody": body[:CAPTURE], "_resp": b""}
    last = None
    for host in ("127.0.0.1", "::1"):
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in headers:
                if k.lower() not in HOP:
                    conn.putheader(k, v)
            if body or method in ("POST", "PUT", "PATCH"):
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body or None)
            resp = conn.getresponse()
            data = resp.read(CAPTURE + 1)
            entry["ttfb"] = round((time.monotonic() - started) * 1000)
            entry.update(status=resp.status, bytes=len(data), ms=round((time.monotonic() - started) * 1000))
            head = f"HTTP/1.1 {resp.status} {resp.reason}\r\n" + "".join(
                f"{k}: {v}\r\n" for k, v in resp.getheaders() if k.lower() not in ("transfer-encoding",)) + "\r\n"
            entry["_resp"] = head.encode("latin-1", "replace") + data[:CAPTURE]
            entry["_truncated"] = len(data) > CAPTURE
            return entry
        except ConnectionRefusedError as err:
            last = err
            continue
        except (OSError, http.client.HTTPException) as err:
            raise RuntimeError(f"The replay failed: {err}.") from err
        finally:
            conn.close()
    raise RuntimeError(f"Nothing answers on port {port} ({last}).")
