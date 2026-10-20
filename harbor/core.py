"""Harbor's engine: scans the machine on a timer, keeps the live picture, runs saved apps and acts on processes."""
from __future__ import annotations

import collections
import json
import os
import re
import shutil
import socket
import sys
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__
from . import classify, probe, system
from .control import ControlError, Managed, signal_and_wait
from .discover import discover
from .metrics import RANGES, Metrics
from .store import Store

SPARK = 60
SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name):
    return SLUG.sub("-", (name or "").lower()).strip("-")[:40] or "app"


def lan_ip():
    """This machine's address on the local network (no packet is sent: UDP connect only picks a route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def realpath(p):
    try:
        return os.path.realpath(os.path.expanduser(p)) if p else None
    except OSError:
        return p


class Harbor:
    def __init__(self, store=None, port=None):
        self.store = store or Store()
        self.port = port
        self.uid = system.my_uid()
        self.pid = os.getpid()
        self.started_at = time.time()
        self.lock = threading.RLock()
        self.changed = threading.Condition()
        self.version = 0
        self.snapshot = None
        self.listeners = {}
        self.procs = {}
        self.cwd_cache = {}
        self.probes = {}
        self.probing = set()
        self.spark = collections.defaultdict(lambda: collections.deque(maxlen=SPARK))
        self.first_seen = {}
        self.managed = {}
        self.clients = 0
        self.wake = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="harbor-probe")
        self.docker = {}
        self.docker_at = 0.0
        self.scan_ms = None
        self.error = None
        self._stop = threading.Event()
        self.self_pids = {self.pid}
        self.health = collections.defaultdict(lambda: collections.deque(maxlen=40))
        self.last_active = {}
        self.lan_ip = lan_ip()
        self.metrics = Metrics(self.store.root)
        self.lan_at = time.time()
        self.procs_prev = {}
        self.roots = {}
        self.conns = {}
        self.last_events = []

    # ------------------------------------------------------------ scanning

    def start(self):
        self.managed.update(Managed.adopt_all(self.store, self._on_exit))
        self.refresh(initial=True)
        threading.Thread(target=self._loop, daemon=True, name="harbor-scan").start()

    def stop(self):
        self._stop.set()
        self.wake.set()
        self.store.save(now=True)
        self.metrics.save()

    def _loop(self):
        while not self._stop.is_set():
            interval = float(self.store.settings.get("scanInterval", 2.0)) if self.clients else 8.0
            self.wake.wait(interval)
            self.wake.clear()
            if self._stop.is_set():
                break
            try:
                self.refresh()
            except Exception as err:   # keep scanning; surface the failure in the snapshot instead of dying
                self.error = f"Scan failed: {err}"
                self._publish()

    def refresh(self, initial=False):
        t0 = time.monotonic()
        try:
            found = system.listeners()
            procs = system.processes()
            self.error = None
        except system.SystemError_ as err:
            self.error = str(err)
            self._publish()
            return
        for (pid, _port), row in found.items():   # Windows' netstat names neither the program nor its owner
            if not row["command"] and pid in procs:
                row["command"] = procs[pid].get("name") or classify.base(procs[pid]["args"])
                row["uid"] = procs[pid]["uid"]
        my_tree = {a["pid"] for a in classify.ancestors(self.pid, procs)}
        self.self_pids = {self.pid} | my_tree
        roots = {}
        for (pid, port), row in found.items():
            roots[pid] = classify.app_root(pid, procs, self.uid, stop_pids=self.self_pids - {self.pid})
        need = {p for p in list(roots) + list(roots.values()) if self.cwd_cache.get(p, (None, None))[0] != procs.get(p, {}).get("args")}
        if need:
            got = system.cwds(need)
            for p in need:
                self.cwd_cache[p] = (procs.get(p, {}).get("args"), got.get(p))
        ports = sorted({port for (_, port) in found})
        try:
            conns = system.established(ports)
        except system.SystemError_:
            conns = {}
        self._docker_refresh()
        now = time.time()
        for port, n in conns.items():
            if n:
                self.last_active[port] = now
        if now - self.lan_at > 60:
            self.lan_ip, self.lan_at = lan_ip(), now
        events = []
        with self.lock:
            prev = self.listeners
            self.procs = procs
            self.listeners = found
            now = time.time()
            for key in found:
                self.first_seen.setdefault(key, now)
            if not initial:
                for key in found.keys() - prev.keys():
                    events.append(self._event("opened", found[key], procs))
                for key in prev.keys() - found.keys():
                    events.append(self._event("closed", prev[key], self.procs_prev))
            for key in prev.keys() - found.keys():
                self.first_seen.pop(key, None)
            self.procs_prev = procs
            for (pid, _port) in found:
                p = procs.get(pid)
                if p:
                    self.spark[pid].append((p["cpu"], round(p["rss_kb"] / 1024, 1)))
            for pid in list(self.spark):
                if pid not in procs:
                    self.spark.pop(pid, None)
            self.roots = roots
            self.conns = conns
        self._ready_events(events, found)
        self._schedule_probes(found, procs)
        self.scan_ms = round((time.monotonic() - t0) * 1000)
        if events:
            self.store.add_activity(events)
        self._publish(events)
        self.metrics.add(self.snapshot)

    def _event(self, kind, row, procs):
        meta = self.store.port_meta(row["port"])
        p = procs.get(row["pid"], {})
        fw = classify.framework(p.get("args", ""))
        cwd = self.cwd_cache.get(row["pid"], (None, None))[1]
        proj = classify.project(cwd)
        m = self.managed_for(row["pid"]) if procs is self.procs else None
        shown = next((r for r in (self.snapshot or {}).get("listeners", []) if r["pid"] == row["pid"] and r["port"] == row["port"]), None)
        title = (meta.get("label") or (m.name if m else None) or (shown["title"] if shown else None)
                 or (self.probes.get(row["port"]) or {}).get("title") or (proj or {}).get("name") or (fw or {}).get("label") or row["command"])
        watched = bool(meta.get("watched"))
        kind_of = classify.kind_of(row["command"], p.get("args", ""), row["uid"], self.uid, fw)
        return {"id": f"{time.time():.6f}-{row['pid']}-{row['port']}", "ts": time.time(), "type": kind, "port": row["port"],
                "pid": row["pid"], "title": title, "project": (proj or {}).get("name"),
                "framework": (fw or {}).get("label"), "kind": kind_of,
                "ranFor": p.get("elapsed"), "memMb": round(p.get("rss_kb", 0) / 1024, 1) if p else None,
                "level": "warn" if (kind == "closed" and watched) else "info", "notify": watched}

    def _ready_events(self, events, found):
        for m in list(self.managed.values()):
            if m.status == "starting" and m.alive:
                tree = set([m.pid] + classify.descendants(m.pid, self.procs))
                ports = sorted({port for (pid, port) in found if pid in tree})
                if ports:
                    m.status = "running"
                    events.append({"id": f"{time.time():.6f}-ready-{m.app_id}", "ts": time.time(), "type": "ready",
                                   "port": ports[0], "pid": m.pid, "title": m.name, "appId": m.app_id, "level": "info",
                                   "notify": True})

    def _schedule_probes(self, found, procs):
        interval = float(self.store.settings.get("probeInterval", 15))
        now = time.time()
        holders = {}
        for (pid, port) in found:
            holders.setdefault(port, set()).add(pid)
        for (pid, port), row in sorted(found.items()):
            if pid != min(holders[port]):
                continue   # one check per port, even when workers share the socket
            p = procs.get(pid, {})
            fw = classify.framework(p.get("args", ""))
            kind = classify.kind_of(row["command"], p.get("args", ""), row["uid"], self.uid, fw)
            if kind in ("system", "app") and not self.store.settings.get("probeApps"):
                continue
            if row["uid"] != self.uid or (fw and not fw["http"]):
                continue
            last = self.probes.get(port)
            if port in self.probing or (last and last.get("pid") in holders[port] and now - last["checkedAt"] < interval):
                continue
            self.probing.add(port)
            self.pool.submit(self._probe, port, pid)

    def _probe(self, port, pid):
        try:
            r = probe.probe(port)
            r["pid"] = pid
            old = self.probes.get(port)
            self.probes[port] = r
            self.health[port].append((round(r["checkedAt"]), r.get("ms"), r.get("status") if r.get("ok") else 0))
            if not old or any(old.get(k) != r.get(k) for k in ("status", "title", "ok", "pid")):
                self._publish()
            return r
        finally:
            self.probing.discard(port)

    def probe_now(self, port):
        pid = next((pid for (pid, p) in self.listeners if p == port), None)
        return self._probe(port, pid)

    def _docker_refresh(self):
        if time.time() - self.docker_at < 10:
            return
        self.docker_at = time.time()
        docker = shutil.which("docker")
        if not docker:
            self.docker = {}
            return
        try:
            out = subprocess.run([docker, "ps", "--format", "{{json .}}"], capture_output=True, text=True, timeout=2.5)
        except (subprocess.TimeoutExpired, OSError):
            return
        mapping = {}
        for line in out.stdout.splitlines():
            try:
                c = json.loads(line)
            except ValueError:
                continue
            for part in (c.get("Ports") or "").split(","):
                part = part.strip()
                if "->" not in part:
                    continue
                host = part.split("->")[0]
                try:
                    hp = int(host.rsplit(":", 1)[-1].split("-")[0])
                except ValueError:
                    continue
                mapping[hp] = {"id": c.get("ID"), "name": c.get("Names"), "image": c.get("Image"), "status": c.get("Status"),
                               "mapping": part}
        self.docker = mapping

    # ------------------------------------------------------------ the picture sent to the browser

    def _publish(self, events=None):
        snap = self.build()
        with self.changed:
            self.snapshot = snap
            self.version += 1
            self.last_events = events or []
            self.changed.notify_all()

    def risk(self, pid, kind, uid):
        if pid in self.self_pids:
            return "self"
        if uid is not None and uid != self.uid:
            return "foreign"
        if kind == "system":
            return "system"
        if kind == "app":
            return "app"
        return None

    def managed_for(self, pid):
        for m in self.managed.values():
            if m.alive and (pid == m.pid or pid in classify.descendants(m.pid, self.procs)):
                return m
        return None

    def build(self):
        with self.lock:
            found, procs = dict(self.listeners), self.procs
            roots, conns = self.roots, self.conns
        rows = []
        now = time.time()
        idle_after = float(self.store.settings.get("idleHours", 4)) * 3600
        slugs = self.app_slugs()
        for (pid, port), row in sorted(found.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            p = procs.get(pid, {})
            args = p.get("args", row["command"])
            fw = classify.framework(args)
            kind = classify.kind_of(row["command"], args, row["uid"], self.uid, fw)
            # Without a readable working folder (Windows), take the project folder from paths in the command line.
            cwd = self.cwd_cache.get(pid, (None, None))[1] or classify.dir_from_args(args)
            root = roots.get(pid, pid)
            root_proc = procs.get(root, {})
            root_cwd = self.cwd_cache.get(root, (None, None))[1] or classify.dir_from_args(root_proc.get("args")) or cwd
            proj = classify.project(root_cwd if kind in ("dev", "service", "other", "tool") else None) if root_cwd else None
            if kind in ("dev", "service", "other", "tool") and cwd and not proj:
                proj = classify.project(cwd)
            meta = self.store.port_meta(port)
            pr = self.probes.get(port)
            if pr and pr.get("pid") not in {x for (x, prt) in found if prt == port}:
                pr = None
            m = self.managed_for(pid)
            app = None
            if m:
                app = m.app_id
            else:
                # The app's folder may be where the launcher runs (make dev at the repo root) or where the
                # server itself runs (frontend/), so either counts.
                here = {realpath(root_cwd), realpath(cwd)} - {None}
                for a in self.store.apps():
                    if realpath(a["cwd"]) in here and (not a.get("port") or a.get("port") == port or kind in ("dev", "tool")):
                        app = a["id"]
                        break
            addresses = row["addresses"]
            exposure = "network" if any(a in ("*", "0.0.0.0", "::") for a in addresses) else "local"
            spark = list(self.spark.get(pid, []))
            dk = self.docker.get(port) if fw and fw["id"] == "docker" or (row["command"] or "").startswith(("com.docke", "vpnkit", "OrbStack")) else None
            app_name = (self.store.app(app) or {}).get("name") if app else None
            title = (meta.get("label") or app_name or (dk and dk["name"]) or (pr or {}).get("title") or (proj or {}).get("name")
                     or classify.app_bundle(args) or (fw or {}).get("label") or row["command"])
            rows.append({
                "id": f"{pid}:{port}", "port": port, "pid": pid, "addresses": addresses, "exposure": exposure,
                "user": row["user"], "owned": row["uid"] == self.uid, "command": row["command"], "args": args,
                "display": classify.display_command(args), "cwd": cwd, "project": proj,
                "framework": {"id": fw["id"], "label": fw["label"]} if fw else None, "kind": kind,
                "appBundle": classify.app_bundle(args), "title": title,
                "cpu": p.get("cpu"), "memMb": round(p.get("rss_kb", 0) / 1024, 1) if p else None,
                "uptime": p.get("elapsed"), "connections": conns.get(port, 0), "probe": pr,
                "root": {"pid": root, "args": root_proc.get("args"), "display": classify.display_command(root_proc.get("args", "")),
                         "cwd": root_cwd, "count": 1 + len(classify.descendants(root, procs))} if root != pid else None,
                "managed": m.app_id if m else None, "appId": app, "risk": self.risk(pid, kind, row["uid"]),
                "meta": meta, "hint": classify.PORT_HINTS.get(port), "firstSeen": self.first_seen.get((pid, port)),
                "spark": {"cpu": [s[0] for s in spark], "mem": [s[1] for s in spark]}, "docker": dk,
                "health": self._health(port),
                "lastActive": self.last_active.get(port),
                "idleFor": self._idle_for(port, kind, p, conns.get(port, 0), now, idle_after),
                "lanUrl": f"http://{self.lan_ip}:{port}/" if exposure == "network" and self.lan_ip else None,
                "stableUrl": f"http://{slugs[app]}.localhost:{self.port}/" if app in slugs and self.port else None,
            })
        rows = self._merge_workers(rows, procs)
        apps = [self.app_status(a, rows) for a in self.store.apps()]
        dev = [r for r in rows if r["kind"] in ("dev", "service", "tool", "other", "database")]
        projects = {r["project"]["root"] for r in rows if r["project"]}
        mine = {r["pid"]: r for r in dev}
        return {
            "version": __version__, "scannedAt": time.time(), "scanMs": self.scan_ms, "error": self.error,
            "me": {"pid": self.pid, "port": self.port, "startedAt": self.started_at, "user": os.environ.get("USER"),
                   "home": str(Path.home()), "docker": bool(shutil.which("docker")), "lanIp": self.lan_ip},
            "listeners": rows, "apps": apps, "settings": self.store.settings,
            "summary": {"listening": len({r["port"] for r in rows}), "dev": len({r["port"] for r in dev}),
                        "projects": len(projects), "exposed": len({r["port"] for r in rows if r["exposure"] == "network"}),
                        "system": len({r["port"] for r in rows if r["kind"] in ("system", "app")}),
                        "appsRunning": sum(a["state"] in ("running", "starting", "external") for a in apps),
                        "cpu": round(sum(r["cpu"] or 0 for r in mine.values()), 1),
                        "memMb": round(sum(r["memMb"] or 0 for r in mine.values()), 1),
                        "idle": len([r for r in rows if r["idleFor"]]),
                        "idleMemMb": round(sum(r["memMb"] or 0 for r in rows if r["idleFor"]), 1),
                        "watchedDown": [int(p) for p, meta in self.store.data["ports"].items()
                                        if meta.get("watched") and int(p) not in {r["port"] for r in rows}]},
            "activity": self.store.activity()[-150:],
        }

    def _health(self, port):
        h = list(self.health.get(port, []))
        if not h:
            return None
        return {"ms": [x[1] for x in h], "status": [x[2] for x in h], "up": sum(1 for x in h if x[2] and x[2] < 500), "n": len(h)}

    def _idle_for(self, port, kind, proc, conns, now, idle_after):
        """Seconds a dev server has gone without a connection and without using CPU, once that passes the
        idle threshold; None while it is in use. Before Harbor saw a connection, the process start counts."""
        if kind not in ("dev", "other") or conns or (proc.get("cpu") or 0) >= 1 or proc.get("elapsed") is None:
            return None
        since = self.last_active.get(port) or (now - proc["elapsed"])
        idle = now - since
        return round(idle) if idle >= idle_after else None

    def app_slugs(self):
        """Stable names for saved apps: http://<slug>.localhost:<harbor port>/ always reaches the app,
        whatever port it is on today."""
        out, used = {}, set()
        for a in self.store.apps():
            base = slugify(a.get("slug") or a.get("name"))
            slug, n = base, 2
            while slug in used:
                slug, n = f"{base}-{n}", n + 1
            used.add(slug)
            out[a["id"]] = slug
        return out

    def proxy_target(self, slug):
        """The port a stable name points at now: a saved app's current port, or a project's single port."""
        slugs = self.app_slugs()
        rows = (self.snapshot or {}).get("listeners", [])
        for app_id, sl in slugs.items():
            if sl == slug:
                st = next((a for a in (self.snapshot or {}).get("apps", []) if a["id"] == app_id), None)
                ports = (st or {}).get("ports") or []
                web = [r["port"] for r in rows if r["port"] in ports and (r.get("probe") or {}).get("ok")]
                return (web or ports or [None])[0], (st or {}).get("name")
        hits = [r for r in rows if r["project"] and slugify(r["project"]["name"]) == slug and (r.get("probe") or {}).get("ok")]
        if len({r["port"] for r in hits}) == 1:
            return hits[0]["port"], hits[0]["title"]
        return None, None

    @staticmethod
    def _merge_workers(rows, procs):
        """A socket shared by a parent and its children (uvicorn --reload, gunicorn workers) is one listener:
        keep the topmost process and list the others as its workers."""
        by_port = {}
        for r in rows:
            by_port.setdefault(r["port"], []).append(r)
        out = []
        for port_rows in by_port.values():
            pids = {r["pid"] for r in port_rows}
            for r in port_rows:
                anc = {a["pid"] for a in classify.ancestors(r["pid"], procs)}
                if anc & pids:
                    continue
                workers = [x for x in port_rows if x is not r and r["pid"] in {a["pid"] for a in classify.ancestors(x["pid"], procs)}]
                r["workers"] = [{"pid": w["pid"], "display": w["display"], "cpu": w["cpu"], "memMb": w["memMb"]} for w in workers]
                for w in workers:
                    r["cpu"] = round((r["cpu"] or 0) + (w["cpu"] or 0), 1)
                    r["memMb"] = round((r["memMb"] or 0) + (w["memMb"] or 0), 1)
                    r["connections"] = max(r["connections"], w["connections"])
                out.append(r)
        return sorted(out, key=lambda r: (r["port"], r["pid"]))

    def app_status(self, app, rows):
        m = self.managed.get(app["id"])
        mine = [r for r in rows if r["managed"] == app["id"] or (r["appId"] == app["id"])]
        ports = sorted({r["port"] for r in mine})
        expected = app.get("port")
        if m and m.alive:
            state = m.status
        elif mine:
            state = "external"
        elif m:
            state = m.status
        else:
            state = "stopped"
        holder = None
        if expected and expected not in ports:
            h = next((r for r in rows if r["port"] == expected), None)
            if h:
                holder = {"pid": h["pid"], "title": h["title"], "command": h["display"], "risk": h["risk"]}
        slug = self.app_slugs().get(app["id"])
        return {**app, "state": state, "ports": ports, "pids": sorted({r["pid"] for r in mine}),
                "stableUrl": f"http://{slug}.localhost:{self.port}/" if slug and self.port else None, "slugName": slug,
                "drift": bool(expected and ports and expected not in ports), "conflict": holder,
                "run": m.summary() if m else None, "logLines": m.seq if m else 0,
                "logFile": str(self.store.log_path(app["id"])) if self.store.log_path(app["id"]).exists() else None}

    # ------------------------------------------------------------ actions

    def _row_for_pid(self, pid):
        return next((r for r in (self.snapshot or {}).get("listeners", []) if r["pid"] == pid), None)

    def kill(self, pid, mode="process", force=True, confirm=False):
        procs = self.procs
        if pid not in procs:
            raise ControlError(f"Process {pid} is not running any more.", status=404)
        known = {r["pid"] for r in self.snapshot["listeners"]} | {r["root"]["pid"] for r in self.snapshot["listeners"] if r["root"]}
        known |= {d for k in list(known) for d in classify.descendants(k, procs)}
        if pid not in known:
            raise ControlError(f"Process {pid} is not one of the listening apps Harbor shows, so Harbor will not stop it.", status=403)
        row = self._row_for_pid(pid)
        p = procs[pid]
        kind = row["kind"] if row else "dev"
        risk = self.risk(pid, kind, p["uid"])
        if risk == "self":
            raise ControlError("That is Harbor itself. Stop Harbor from its terminal (Ctrl-C) instead.", status=403)
        if risk == "foreign":
            raise ControlError(f"Process {pid} belongs to another user; stopping it needs sudo, which Harbor never uses.", status=403)
        if risk in ("system", "app") and not confirm:
            raise ControlError("This is a desktop app or a system service. Confirm to stop it.", status=409, needsConfirm=risk)
        m = self.managed_for(pid)
        if m:
            m.stopping = True   # stopped on purpose from Harbor: not a crash
        if m and mode == "app":
            res = m.stop(grace=float(self.store.settings["graceSeconds"]), extra_pids=classify.descendants(m.pid, procs))
            return self._after_kill(res, pid, "app", row)
        if mode == "app":
            root = (row["root"] or {}).get("pid") if row and row.get("root") else pid
            pids = [root] + classify.descendants(root, procs)
        else:
            pids = [pid]
        pids = [x for x in pids if x not in self.self_pids and procs.get(x, {}).get("uid") == self.uid]
        res = signal_and_wait(pids, grace=float(self.store.settings["graceSeconds"]), force=force)
        return self._after_kill(res, pid, mode, row)

    def _after_kill(self, res, pid, mode, row):
        ev = {"id": f"{time.time():.6f}-kill-{pid}", "ts": time.time(), "type": "killed", "pid": pid,
              "port": row["port"] if row else None, "title": row["title"] if row else str(pid), "level": "info",
              "detail": f"{len(res['exited']) + len(res['killed'])} process(es) stopped" + (f", {len(res['killed'])} forced" if res["killed"] else "")}
        self.store.add_activity([ev])
        self.wake.set()
        return {**res, "mode": mode, "event": ev}

    def docker_stop(self, container_id):
        docker = shutil.which("docker")
        if not docker or not any(d["id"] == container_id for d in self.docker.values()):
            raise ControlError("No such running container.", status=404)
        out = subprocess.run([docker, "stop", container_id], capture_output=True, text=True, timeout=30)
        self.docker_at = 0
        self.wake.set()
        if out.returncode:
            raise ControlError(f"docker stop failed: {out.stderr.strip()[:300]}")
        return {"stopped": container_id}

    def _on_exit(self, m):
        ev = {"id": f"{time.time():.6f}-exit-{m.app_id}", "ts": time.time(), "type": m.status, "pid": m.pid, "port": m.port,
              "title": m.name, "appId": m.app_id, "level": "error" if m.status == "crashed" else "info",
              "detail": f"exit code {m.exit_code}", "notify": m.status == "crashed"}
        self.store.add_activity([ev])
        app = self.store.app(m.app_id)
        if app and app.get("autoRestart") and m.status == "crashed":
            recent = [e for e in self.store.activity()[-20:] if e.get("appId") == m.app_id and e["type"] == "crashed" and time.time() - e["ts"] < 120]
            if len(recent) <= 3:
                threading.Timer(1.5, lambda: self._safe_start(m.app_id)).start()
        self.wake.set()

    def _safe_start(self, app_id):
        try:
            self.start_app(app_id, force=True)
        except ControlError as err:
            self.store.add_activity([{"id": f"{time.time():.6f}-x", "ts": time.time(), "type": "crashed", "title": app_id,
                                      "level": "error", "detail": f"auto-restart failed: {err}"}])

    def start_app(self, app_id, port=None, force=False, take_over=False):
        app = self.store.app(app_id)
        if not app:
            raise ControlError("No such app.", status=404)
        current = self.managed.get(app_id)
        if current and current.alive:
            raise ControlError(f"{app['name']} is already running (pid {current.pid}).", status=409)
        status = self.app_status(app, self.snapshot["listeners"] if self.snapshot else [])
        if status["state"] == "external" and not force:
            raise ControlError(f"{app['name']} is already running outside Harbor on port {', '.join(map(str, status['ports']))}.",
                               status=409, external=status["pids"])
        want = port or app.get("port")
        if want and not probe.port_free(int(want)):
            holder = next((r for r in self.snapshot["listeners"] if r["port"] == int(want)), None)
            if take_over and holder:
                self.kill(holder["pid"], mode="app", confirm=False)
                for _ in range(40):
                    if probe.port_free(int(want)):
                        break
                    time.sleep(0.1)
            else:
                alt = probe.free_ports(int(want) + 1, 1)
                self.store.add_activity([{"id": f"{time.time():.6f}-conflict-{app_id}", "ts": time.time(), "type": "conflict",
                                          "port": int(want), "title": app["name"], "appId": app_id, "level": "warn",
                                          "detail": f"held by {holder['title']}" if holder else "port busy"}])
                raise ControlError(f"Port {want} is in use" + (f" by {holder['title']} (pid {holder['pid']})" if holder else "") + ".",
                                   status=409, conflict={"port": int(want), "holder": holder, "suggest": alt[0] if alt else None})
        m = Managed(app, int(want) if want else None, self.store.log_path(app_id), self._on_exit, self.store.root / "run")
        self.managed[app_id] = m
        self.store.add_activity([{"id": f"{time.time():.6f}-start-{app_id}", "ts": time.time(), "type": "started", "pid": m.pid,
                                  "port": m.port, "title": app["name"], "appId": app_id, "level": "info"}])
        self.wake.set()
        return m.summary()

    def stop_app(self, app_id):
        app = self.store.app(app_id)
        if not app:
            raise ControlError("No such app.", status=404)
        m = self.managed.get(app_id)
        if m and m.alive:
            res = m.stop(grace=float(self.store.settings["graceSeconds"]), extra_pids=classify.descendants(m.pid, self.procs))
            self.wake.set()
            return res
        status = self.app_status(app, self.snapshot["listeners"])
        if status["state"] == "external" and status["pids"]:
            out = None
            for pid in status["pids"]:
                if pid in self.procs:
                    out = self.kill(pid, mode="app")
            return out or {"stopped": []}
        raise ControlError(f"{app['name']} is not running.", status=409)

    def restart_app(self, app_id):
        app = self.store.app(app_id)
        st = self.app_status(app, self.snapshot["listeners"]) if app else None
        # Come back on the port it was using, which may not be the saved one (it moved because that was taken).
        m = self.managed.get(app_id)
        port = (m.port if m and m.alive else None) or (st["ports"][0] if st and st["ports"] else None) or (app or {}).get("port")
        if st and st["state"] in ("running", "starting", "external"):
            self.stop_app(app_id)
            for _ in range(50):
                if not port or probe.port_free(int(port)):
                    break
                time.sleep(0.1)
            self.refresh()
        return self.start_app(app_id, port=port, force=True)

    def app_from_process(self, pid, name=None):
        row = self._row_for_pid(pid)
        if not row:
            raise ControlError("That process is not listening on a port any more.", status=404)
        root = row["root"] or {"pid": pid, "args": row["args"], "cwd": row["cwd"]}
        cwd = root.get("cwd") or row["cwd"]
        if not cwd:
            raise ControlError("Harbor could not read that process's folder, so it cannot run it again.")
        for a in self.store.apps():
            if realpath(a["cwd"]) == realpath(cwd) and a["command"] == root["args"]:
                return a
        command = root["args"]
        if (row["framework"] or {}).get("id") == "vite" and "--port" not in command and root["pid"] == pid:
            command += " --port {port} --strictPort"
        default = (row["project"] or {}).get("name") or row["title"]
        return self.store.upsert_app({"name": name or default, "cwd": cwd, "command": command, "port": row["port"]})

    def restart_process(self, pid):
        app = self.app_from_process(pid)
        row = self._row_for_pid(pid)
        self.kill(pid, mode="app", confirm=True)
        for _ in range(50):
            if probe.port_free(row["port"]):
                break
            time.sleep(0.1)
        return {"app": app, "run": self.start_app(app["id"], force=True)}

    def process_detail(self, pid):
        procs = self.procs
        p = procs.get(pid)
        if not p:
            raise ControlError(f"Process {pid} is not running.", status=404)
        by_pid = {}
        for r in self.snapshot["listeners"]:
            by_pid.setdefault(r["pid"], []).append(r["port"])
        def node(x):
            q = procs[x]
            return {"pid": x, "ppid": q["ppid"], "args": q["args"], "display": classify.display_command(q["args"], 160),
                    "cpu": q["cpu"], "memMb": round(q["rss_kb"] / 1024, 1), "uptime": q["elapsed"], "ports": by_pid.get(x, []),
                    "mine": q["uid"] == self.uid}
        anc = [node(a["pid"]) for a in classify.ancestors(pid, procs)][:12]
        root = classify.app_root(pid, procs, self.uid, stop_pids=self.self_pids - {self.pid})
        kids = [node(d) for d in classify.descendants(root, procs) if d in procs][:60]
        return {"process": node(pid), "ancestors": anc, "root": node(root) if root in procs else None, "tree": kids,
                "cwd": self.cwd_cache.get(pid, (None, None))[1]}

    def known_paths(self):
        paths = {r["cwd"] for r in self.snapshot["listeners"] if r["cwd"]}
        paths |= {r["project"]["root"] for r in self.snapshot["listeners"] if r["project"]}
        paths |= {(r["root"] or {}).get("cwd") for r in self.snapshot["listeners"] if r["root"]}
        paths |= {os.path.expanduser(a["cwd"]) for a in self.store.apps()}
        return {realpath(p) for p in paths if p}

    def reveal(self, path, target):
        if realpath(path) not in self.known_paths() or not os.path.isdir(path):
            raise ControlError("Harbor only opens folders of apps it shows.", status=403)
        code = shutil.which("code") or shutil.which("cursor")
        if system.IS_WINDOWS:
            wt = shutil.which("wt")
            cmd = {"editor": [code, path] if code else None,
                   "terminal": [wt, "-d", path] if wt else [os.environ.get("COMSPEC", "cmd.exe"), "/c", "start", "cmd", "/K", f'cd /d "{path}"'],
                   }.get(target, ["explorer", path])
        elif sys.platform == "darwin":
            cmd = {"editor": [code, path] if code else ["open", "-a", "Visual Studio Code", path],
                   "terminal": ["open", "-a", "Terminal", path]}.get(target, ["open", path])
        else:
            term = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal") or shutil.which("konsole")
            cmd = {"editor": [code, path] if code else None,
                   "terminal": [term, "--working-directory", path] if term else None}.get(target, ["xdg-open", path])
        if not cmd or not cmd[0]:
            raise ControlError("No program found to open that folder.")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **system.spawn_options())
        return {"opened": path, "target": target}

    def check_port(self, port):
        rows = [r for r in self.snapshot["listeners"] if r["port"] == port]
        return {"port": port, "free": not rows and probe.port_free(port), "listeners": rows,
                "hint": classify.PORT_HINTS.get(port),
                "next": probe.free_ports(port + 1, 3, used={r["port"] for r in self.snapshot["listeners"]}) if rows else []}

    def free(self, start, count):
        return probe.free_ports(start, count, used={r["port"] for r in self.snapshot["listeners"]})

    def discover(self, folder, depth):
        res = discover(folder, depth)
        saved = {(realpath(a["cwd"]), a["command"]) for a in self.store.apps()}
        for it in res["items"]:
            it["saved"] = (realpath(it["cwd"]), it["command"]) in saved
        return res

    def kill_many(self, pids, mode="process"):
        results = {}
        for pid in pids:
            try:
                results[pid] = {"ok": True, **self.kill(int(pid), mode=mode)}
            except ControlError as err:
                results[pid] = {"ok": False, "error": str(err)}
        return {"results": results, "stopped": sum(r["ok"] for r in results.values())}

    def group_action(self, group, action):
        apps = [a for a in self.store.apps() if (a.get("group") or "") == group]
        if not apps:
            raise ControlError(f"No apps in group '{group}'.", status=404)
        out = {}
        for a in apps:
            try:
                if action == "start":
                    st = self.app_status(a, self.snapshot["listeners"])
                    if st["state"] in ("running", "starting", "external"):
                        out[a["name"]] = "already running"
                        continue
                    self.start_app(a["id"])
                    out[a["name"]] = "started"
                else:
                    self.stop_app(a["id"])
                    out[a["name"]] = "stopped"
            except ControlError as err:
                out[a["name"]] = str(err)
        self.wake.set()
        return {"group": group, "results": out}

    def export_apps(self):
        keep = ("name", "cwd", "command", "port", "env", "openPath", "group", "color", "autoRestart", "slug")
        return {"harbor": __version__, "exportedAt": time.time(),
                "apps": [{k: a[k] for k in keep if k in a} for a in self.store.apps()]}

    def import_apps(self, apps):
        have = {(realpath(a["cwd"]), a["command"]) for a in self.store.apps()}
        added, skipped = [], []
        for a in apps:
            if not isinstance(a, dict) or not a.get("cwd") or not a.get("command") or not a.get("name"):
                skipped.append({"app": a, "why": "needs name, cwd and command"})
                continue
            if (realpath(a["cwd"]), a["command"]) in have:
                skipped.append({"app": a.get("name"), "why": "already saved"})
                continue
            added.append(self.store.upsert_app(a)["name"])
            have.add((realpath(a["cwd"]), a["command"]))
        self._publish()
        return {"added": added, "skipped": skipped}

    def insights(self, rng="24h"):
        seconds = RANGES.get(rng, 86400)
        now = time.time()
        health = {}
        for port, h in self.health.items():
            ms = sorted(x[1] for x in h if x[1] is not None and x[2])
            if not h:
                continue
            health[port] = {"n": len(h), "ok": sum(1 for x in h if x[2] and x[2] < 500),
                            "avg": round(sum(ms) / len(ms)) if ms else None,
                            "p95": ms[min(len(ms) - 1, int(len(ms) * 0.95))] if ms else None}
        return {"range": rng, "seconds": seconds, "now": now, "harborStarted": self.started_at,
                "samples": self.metrics.query(seconds, 240, now),
                "activity": [e for e in self.store.activity() if e["ts"] >= now - seconds],
                "health": health}

    def shutdown_apps(self):
        for m in self.managed.values():
            if m.alive:
                m.stop(grace=2.0)
