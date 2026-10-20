"""Porthaven's saved state in ~/.porthaven (or $PORTHAVEN_HOME): apps, notes on ports, settings, activity."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

DEFAULT_SETTINGS = {"scanInterval": 2.0, "probeInterval": 15.0, "graceSeconds": 4.0, "showSystem": False,
                    "probeApps": False, "notify": True, "idleHours": 4.0}


def home():
    """~/.porthaven (or $PORTHAVEN_HOME). State from before the rename (~/.harbor) moves over on first use."""
    explicit = os.environ.get("PORTHAVEN_HOME") or os.environ.get("HARBOR_HOME")
    if explicit:
        return Path(explicit)
    new, old = Path.home() / ".porthaven", Path.home() / ".harbor"
    if not new.exists() and (old / "state.json").exists():
        try:
            old.rename(new)
        except OSError:
            return old
    return new


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else home()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(exist_ok=True)
        self.path = self.root / "state.json"
        self.lock = threading.RLock()
        self.data = {"apps": [], "ports": {}, "settings": dict(DEFAULT_SETTINGS), "activity": []}
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text())
                self.data.update({k: v for k, v in saved.items() if k in self.data})
                self.data["settings"] = {**DEFAULT_SETTINGS, **saved.get("settings", {})}
            except (OSError, ValueError):
                self.path.rename(self.path.with_suffix(f".broken-{int(time.time())}.json"))
        self._timer = None

    def save(self, now=False):
        with self.lock:
            if self._timer:
                self._timer.cancel()
            if now:
                self._write()
            else:
                self._timer = threading.Timer(0.5, self._write)
                self._timer.daemon = True
                self._timer.start()

    def _write(self):
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(self.data, indent=1))
                os.replace(tmp, self.path)
            except FileNotFoundError:   # the state folder was removed (tests, or by hand): nothing to keep
                pass

    # ---------------- settings
    @property
    def settings(self):
        return self.data["settings"]

    def update_settings(self, values):
        with self.lock:
            for k, v in values.items():
                if k in DEFAULT_SETTINGS and type(v) in (type(DEFAULT_SETTINGS[k]), int, float, bool):
                    self.data["settings"][k] = v
            self.data["settings"]["scanInterval"] = min(30.0, max(1.0, float(self.data["settings"]["scanInterval"])))
            self.save()
            return self.settings

    # ---------------- per-port notes
    def port_meta(self, port):
        return self.data["ports"].get(str(port), {})

    def update_port(self, port, values):
        with self.lock:
            meta = dict(self.data["ports"].get(str(port), {}))
            for k in ("note", "label", "pinned", "watched", "color"):
                if k in values:
                    meta[k] = values[k]
            meta = {k: v for k, v in meta.items() if v not in (None, "", False)}
            if meta:
                self.data["ports"][str(port)] = meta
            else:
                self.data["ports"].pop(str(port), None)
            self.save()
            return meta

    # ---------------- apps (saved launch profiles)
    def apps(self):
        return self.data["apps"]

    def app(self, app_id):
        return next((a for a in self.data["apps"] if a["id"] == app_id), None)

    def upsert_app(self, values, app_id=None):
        with self.lock:
            fields = {k: values[k] for k in ("name", "cwd", "command", "port", "env", "openPath", "group", "color", "autoRestart", "slug")
                      if k in values}
            if app_id:
                app = self.app(app_id)
                if not app:
                    return None
                app.update(fields)
            else:
                app = {"id": uuid.uuid4().hex[:8], "createdAt": time.time(), "env": {}, "openPath": "/", **fields}
                self.data["apps"].append(app)
            self.save()
            return app

    def delete_app(self, app_id):
        with self.lock:
            before = len(self.data["apps"])
            self.data["apps"] = [a for a in self.data["apps"] if a["id"] != app_id]
            self.save()
            return len(self.data["apps"]) != before

    # ---------------- activity
    def add_activity(self, events, keep=4000):
        if not events:
            return
        with self.lock:
            self.data["activity"] = (self.data["activity"] + events)[-keep:]
            self.save()

    def activity(self):
        return self.data["activity"]

    def log_path(self, app_id):
        return self.root / "logs" / f"{app_id}.log"
