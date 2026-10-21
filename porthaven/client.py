"""Talking to a running Porthaven from the command line or the MCP server, starting one when needed."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import system

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never send localhost through a proxy


class ClientError(RuntimeError):
    def __init__(self, message, status=0, data=None):
        super().__init__(message)
        self.status = status
        self.data = data or {}


def base_url():
    return os.environ.get("PORTHAVEN_URL") or f"http://127.0.0.1:{os.environ.get('PORTHAVEN_PORT', '7475')}"


def _raw(method, path, body=None, headers=None, timeout=30):
    req = urllib.request.Request(base_url() + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as err:
        with err:
            data = json.loads(err.read() or b"{}")
        raise ClientError(data.get("error") or f"HTTP {err.code}", err.code, data) from None
    except (urllib.error.URLError, OSError) as err:
        raise ClientError(f"Porthaven is not running at {base_url()} ({getattr(err, 'reason', err)}).") from None


def running():
    try:
        _raw("GET", "/api/session", timeout=2)
        return True
    except ClientError:
        return False


def ensure_server(log=None):
    """Start Porthaven in the background if it isn't running, and wait until it answers."""
    if running():
        return False
    root = str(Path(__file__).resolve().parent.parent)
    env = {**os.environ, "PYTHONPATH": root + os.pathsep + os.environ.get("PYTHONPATH", "")}
    subprocess.Popen([sys.executable, "-m", "porthaven", "serve", "--no-open"], env=env, cwd=root,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **system.spawn_options())
    if log:
        log("Started Porthaven in the background.")
    for _ in range(60):
        if running():
            return True
        time.sleep(0.25)
    raise ClientError("Porthaven did not start within 15 seconds. Run `porthaven serve` to see why.")


class Client:
    def __init__(self, actor="cli", session=None):
        self.actor = actor
        self.session = session   # the coding-agent session (process id) an MCP client runs under
        self.token = None

    def call(self, method, path, body=None, timeout=30):
        headers = {"X-Porthaven-Actor": self.actor}
        if self.session:
            headers["X-Porthaven-Session"] = str(self.session)
        if method != "GET":
            if not self.token:
                self.token = _raw("GET", "/api/session")["token"]
            headers["X-Porthaven-Token"] = self.token
        return _raw(method, path, body, headers, timeout)

    def state(self):
        return self.call("GET", "/api/state")
