"""Porthaven's engine: scans the machine on a timer, keeps the live picture, runs saved apps and acts on processes."""
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
from . import agents, compose, drift, gitinfo, history, leaks, logsearch, netmap, relay, share, stacks, teamfile, tls
from .store import Store

SPARK = 60
SLUG = re.compile(r"[^a-z0-9.]+")


def slugify(name):
    return SLUG.sub("-", (name or "").lower()).strip("-")[:40] or "app"


def uuid_hex():
    import uuid
    return uuid.uuid4().hex[:8]


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


class Porthaven:
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
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="porthaven-probe")
        self.docker = {}
        self.docker_at = 0.0
        self.scan_ms = None
        self.error = None
        self._stop = threading.Event()
        self.self_pids = {self.pid}
        self.health = collections.defaultdict(lambda: collections.deque(maxlen=40))
        self.last_active = {}
        self.lan_ip = lan_ip()
        self.requests = collections.defaultdict(lambda: collections.deque(maxlen=300))   # stable name -> recent requests
        self.last_traffic = {}       # app id -> last time it had a connection or a proxied request
        self.critical_seen = set()   # listener ids already reported as critically exposed
        self.metrics = Metrics(self.store.root)
        self.lan_at = time.time()
        self.procs_prev = {}
        self.roots = {}
        self.conns = {}
        self.last_events = []
        self.stopped = collections.OrderedDict()   # pid -> (time, listener row) for apps stopped from Porthaven, so they can run again
        self.links = []                           # established connections touching a listening port (service map)
        self.netmap = netmap.ServiceMap()
        self.history = history.PortHistory(self.store.root)
        self.containers = []                      # running Docker containers, with their compose service
        self.agent_marks = {}                     # pid -> coding-agent session that started it (see agents.py)
        self.agent_checked = set()
        self.sessions = {}                        # "pid@start" -> {label, pid, startedAt, alive, endedAt}
        self.mem_hist = collections.defaultdict(lambda: collections.deque(maxlen=leaks.WINDOW // leaks.EVERY + 5))
        self.mem_at = 0.0
        self.leaks = {}                           # pid -> trend, for servers whose memory keeps growing
        self.leaks_told = set()
        self.drift = {"findings": [], "at": 0.0, "running": False}
        self.drift_scanner = drift.Scanner()
        self.shares = share.Shares(on_event=self._share_event)
        self.tls = tls.Authority(self.store.root)
        self.https = {"enabled": False, "port": None, "error": None, "status": None, "checkedAt": 0.0}
        self._load_agent_marks()

    # ------------------------------------------------------------ scanning

    def start(self):
        self.managed.update(Managed.adopt_all(self.store, self._on_exit))
        self.refresh(initial=True)
        threading.Thread(target=self._loop, daemon=True, name="porthaven-scan").start()

    def stop(self):
        self._stop.set()
        self.wake.set()
        self.shares.stop_all()
        self.history.flush()
        self._save_agent_marks()
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
                self._sleep_idle_apps()
                self._after_scan()
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
            links = system.connections(ports)
        except system.SystemError_:
            links = []
        conns = system.server_counts(links, ports)
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
                    self.history.start(key[0], key[1], self._history_info(events[-1]))
                for key in prev.keys() - found.keys():
                    events.append(self._event("closed", prev[key], self.procs_prev))
                    self.history.end(key[0], key[1], self._history_info(events[-1]))
            else:
                for key, row in found.items():
                    p = procs.get(key[0]) or {}
                    started = now - p["elapsed"] if p.get("elapsed") is not None else now
                    self.history.start(key[0], key[1], {"command": classify.display_command(p.get("args") or row["command"], 200)}, started)
            for key in prev.keys() - found.keys():
                self.first_seen.pop(key, None)
                shown = self._row_for_pid(key[0])   # last published row: lets Restart run a server that stopped by itself
                if shown and shown["port"] == key[1] and key[0] not in self.stopped:
                    self._remember_stopped(key[0], shown)
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
            self.links = links
        self._mark_agents(found, procs, roots)
        self._ready_events(events, found)
        self._schedule_probes(found, procs)
        self.scan_ms = round((time.monotonic() - t0) * 1000)
        if events:
            self.store.add_activity(events)
        self._publish(events)
        self.metrics.add(self.snapshot)
        self._report_exposure()

    def _report_exposure(self):
        """One event (with a desktop notification) the first time a listener is critically exposed."""
        crit = {r["id"]: r for r in self.snapshot["listeners"] if (r.get("exposureRisk") or {}).get("level") == "critical"}
        new = [r for i, r in crit.items() if i not in self.critical_seen]
        self.critical_seen = set(crit)
        if new:
            evs = [{"id": f"{time.time():.6f}-exposed-{r['id']}", "ts": time.time(), "type": "exposed", "port": r["port"], "pid": r["pid"],
                    "title": r["title"], "level": "error", "detail": r["exposureRisk"]["title"], "notify": True} for r in new]
            self.store.add_activity(evs)
            self._publish(evs)

    # ------------------------------------------------------------ after every scan: shares, memory, agents, drift

    def _after_scan(self):
        snap = self.snapshot
        if not snap:
            return
        rows = snap["listeners"]
        self.shares.tick({r["port"] for r in rows})
        for r in rows:
            self.history.update(r["pid"], r["port"], {"title": r["title"], "project": (r["project"] or {}).get("name"),
                                                      "framework": (r["framework"] or {}).get("label"), "app": r.get("appId")})
        changed = self._watch_memory(rows)
        changed = self._watch_agent_sessions(rows) or changed
        if self.store.settings.get("drift", True) and time.time() - self.drift["at"] > 60 and not self.drift["running"]:
            self.drift["running"] = True
            self.pool.submit(self._drift_scan)
        if time.time() - self.https["checkedAt"] > 300 and self.https["enabled"]:
            self.pool.submit(self._https_check)
        if changed:
            self._publish()

    @staticmethod
    def _history_info(ev):
        return {k: ev.get(k) for k in ("title", "project", "framework") if ev.get(k)}

    def port_history(self, port, at=None, since=None, until=None):
        rows = self.history.query(port, since=since, until=until, at=at)
        now_rows = [r for r in (self.snapshot or {}).get("listeners", []) if r["port"] == port]
        return {"port": port, "at": at, "intervals": rows[:500], "now": [{"pid": r["pid"], "title": r["title"]} for r in now_rows],
                "hint": classify.PORT_HINTS.get(port)}

    # ---------------- memory that keeps growing

    def _watch_memory(self, rows):
        now = time.time()
        if now - self.mem_at < leaks.EVERY:
            return False
        self.mem_at = now
        alive, changed = set(), False
        threshold = float(self.store.settings.get("leakMb", 500) or 0)
        for r in rows:
            if r["kind"] not in ("dev", "service", "other", "tool") or r["risk"] in ("self", "foreign") or r["memMb"] is None:
                continue
            alive.add(r["pid"])
            self.mem_hist[r["pid"]].append((now, r["memMb"]))
            found = leaks.trend(list(self.mem_hist[r["pid"]]), min_mb=threshold)
            if found and r["pid"] not in self.leaks:
                changed = True
                if r["pid"] not in self.leaks_told:
                    self.leaks_told.add(r["pid"])
                    self.store.add_activity([{"id": f"{now:.6f}-leak-{r['pid']}", "ts": now, "type": "leak", "port": r["port"], "pid": r["pid"],
                                              "title": r["title"], "appId": r.get("appId"), "level": "warn", "notify": True,
                                              "detail": f"memory +{found['growthMb']} MB in {found['minutes']} min, still growing"}])
            elif not found and r["pid"] in self.leaks:
                changed = True
            if found:
                self.leaks[r["pid"]] = found
            else:
                self.leaks.pop(r["pid"], None)
        for pid in list(self.mem_hist):
            if pid not in alive:
                self.mem_hist.pop(pid, None)
                self.leaks.pop(pid, None)
        return changed

    # ---------------- servers coding agents started

    def _load_agent_marks(self):
        now = time.time()
        try:
            procs = system.processes()
        except system.SystemError_:
            procs = {}
        for pid, mark in (self.store.data.get("agentServers") or {}).items():
            p = procs.get(int(pid))
            if p and mark.get("procStart") is not None and agents.started(p, now) is not None \
                    and abs(agents.started(p, now) - mark["procStart"]) <= 5:
                self.agent_marks[int(pid)] = mark
                self.agent_checked.add(int(pid))

    def _save_agent_marks(self):
        with self.store.lock:
            self.store.data["agentServers"] = {str(pid): m for pid, m in self.agent_marks.items()}
            self.store.save()

    def _mark_agents(self, found, procs, roots):
        now, added = time.time(), False
        for (pid, _port) in found:
            for p in {pid, roots.get(pid, pid)}:
                if p in self.agent_checked:
                    continue
                self.agent_checked.add(p)
                if p in self.self_pids:
                    continue
                sess = agents.find_session(p, procs, now, stop_pids={self.pid})
                if sess:
                    self.agent_marks[p] = {**sess, "procStart": agents.started(procs.get(p), now)}
                    added = True
        gone = [p for p in self.agent_marks if p not in procs]
        for p in gone:
            self.agent_marks.pop(p, None)
        self.agent_checked &= set(procs)
        if added or gone:
            self._save_agent_marks()

    def agent_for(self, row, m=None):
        """The coding-agent session behind a listening row, with whether that session is still running. Porthaven,
        desktop apps and system services are never an agent's leftovers, whoever started them."""
        if row["kind"] in ("tool", "system", "app") or row["risk"] in ("self", "foreign", "system", "app"):
            return None
        sess = self.agent_marks.get(row["pid"]) or self.agent_marks.get((row.get("root") or {}).get("pid")) or (m.agent if m else None)
        if not sess:
            return None
        key = f"{sess['pid']}@{sess.get('startedAt')}"
        st = self.sessions.get(key) or {}
        return {"agent": sess["agent"], "label": sess["label"], "pid": sess["pid"], "startedAt": sess.get("startedAt"),
                "alive": st.get("alive", agents.alive(sess, self.procs, time.time())), "endedAt": st.get("endedAt"), "key": key}

    def _watch_agent_sessions(self, rows):
        now, changed = time.time(), False
        by_session = {}
        for r in rows:
            if r.get("agent"):
                by_session.setdefault(r["agent"]["key"], []).append(r)
        for key, rs in by_session.items():
            a = rs[0]["agent"]
            st = self.sessions.setdefault(key, {"label": a["label"], "pid": a["pid"], "startedAt": a["startedAt"], "alive": True, "endedAt": None})
            alive = agents.alive({"pid": a["pid"], "startedAt": a["startedAt"]}, self.procs, now)
            if st["alive"] and not alive:
                st.update(alive=False, endedAt=now)
                changed = True
                mem = round(sum(r["memMb"] or 0 for r in rs))
                self.store.add_activity([{"id": f"{now:.6f}-agent-{key}", "ts": now, "type": "agent-ended", "title": a["label"],
                                          "level": "warn", "notify": self.store.settings.get("agentCleanup") != "off",
                                          "detail": f"session ended; left {len(rs)} server(s) running ({', '.join(':' + str(r['port']) for r in rs)}, {mem} MB)"}])
            elif alive and not st["alive"]:
                st.update(alive=True, endedAt=None)
        if self.store.settings.get("agentCleanup") == "stop":
            wait = float(self.store.settings.get("agentCleanupMinutes", 15)) * 60
            for key, rs in by_session.items():
                st = self.sessions.get(key) or {}
                if st.get("alive") or not st.get("endedAt") or now - st["endedAt"] < wait:
                    continue
                for r in rs:
                    if r["connections"] or r["risk"]:
                        continue
                    try:
                        self._stop_row(r, actor=f"cleanup after {st['label']}")
                        changed = True
                    except ControlError:
                        pass
        return changed

    def _stop_row(self, r, actor=None):
        if r.get("managed"):
            return self.stop_app(r["managed"])
        return self.kill(r["pid"], mode="app", actor=actor)

    def agent_leftovers(self, session_pid=None, include_live=False):
        rows = [r for r in (self.snapshot or {}).get("listeners", []) if r.get("agent")
                and (include_live or not r["agent"]["alive"]) and (session_pid is None or r["agent"]["pid"] == session_pid)]
        return rows

    def stop_agent_servers(self, session_pid=None, include_live=False, actor=None):
        out, seen = {}, set()
        for r in self.agent_leftovers(session_pid, include_live):
            if r["pid"] in seen or r["risk"]:
                continue
            seen.add(r["pid"])
            try:
                self._stop_row(r, actor=actor)
                out[f":{r['port']} {r['title']}"] = "stopped"
            except ControlError as err:
                out[f":{r['port']} {r['title']}"] = str(err)
        self.wake.set()
        return {"results": out, "stopped": sum(v == "stopped" for v in out.values())}

    # ---------------- port drift

    def _drift_projects(self):
        rows = (self.snapshot or {}).get("listeners", [])
        projects, seen = [], set()
        for a in self.store.apps():
            root = realpath(a["cwd"])
            if not root or root in seen or not os.path.isdir(root):
                continue
            seen.add(root)
            ports = {r["port"] for r in rows if r.get("appId") == a["id"]} | ({int(a["port"])} if a.get("port") else set())
            projects.append({"root": root, "name": a["name"], "appId": a["id"], "ports": sorted(ports),
                             "running": any(r.get("appId") == a["id"] for r in rows)})
        for r in rows:
            if r["kind"] not in ("dev", "service", "other") or not r["project"] or r["risk"] == "foreign":
                continue
            root = realpath(r["project"]["root"])
            if root in seen or not root or root == realpath(str(Path.home())):
                continue
            seen.add(root)
            ports = sorted({x["port"] for x in rows if x["project"] and realpath(x["project"]["root"]) == root})
            projects.append({"root": root, "name": r["project"]["name"], "appId": r.get("appId"), "ports": ports, "running": True})
        return projects[:40]

    def _drift_scan(self):
        try:
            snap = self.snapshot or {}
            found = drift.check(self._drift_projects(), self.store.apps(), snap.get("listeners", []), self.store.activity()[-1500:],
                                porthaven_port=self.port, scanner=self.drift_scanner)
            dismissed = set(self.store.data.get("driftDismissed") or [])
            found = [f for f in found if f["id"] not in dismissed]
            old = {f["id"] for f in self.drift["findings"]}
            self.drift.update(findings=found, at=time.time())
            if {f["id"] for f in found} != old:
                self._publish()
        finally:
            self.drift["running"] = False
        return self.drift

    def drift_scan(self):
        self.drift["running"] = True
        return self._drift_scan()

    def drift_fix(self, finding_id, port=None):
        f = next((x for x in self.drift["findings"] if x["id"] == finding_id), None)
        if not f:
            raise ControlError("That mismatch is not in the latest scan any more; scan again.", status=404)
        new_port = int(port or (f.get("fix") or {}).get("port") or 0)
        if not new_port:
            raise ControlError("Porthaven does not know which port to use; edit the file yourself.")
        if realpath(f["projectRoot"]) not in self.known_paths() or not realpath(f["file"]).startswith(realpath(f["projectRoot"])):
            raise ControlError("Porthaven only edits files inside the projects it shows.", status=403)
        try:
            line = drift.apply_fix(f["file"], f["line"], f["match"], f"{f['host']}:{new_port}")
        except (OSError, ValueError, UnicodeDecodeError) as err:
            raise ControlError(str(err)) from err
        now = time.time()
        self.store.add_activity([{"id": f"{now:.6f}-drift-fix", "ts": now, "type": "fixed", "port": new_port, "title": f["project"],
                                  "level": "info", "detail": f"{f['rel']} line {f['line']}: {f['match']} → :{new_port}"}])
        self.drift["findings"] = [x for x in self.drift["findings"] if x["id"] != finding_id]
        self._publish()
        return {"file": f["file"], "line": f["line"], "text": line}

    def drift_dismiss(self, finding_id):
        with self.store.lock:
            d = self.store.data.setdefault("driftDismissed", [])
            if finding_id not in d:
                d.append(finding_id)
                del d[:-500]
            self.store.save()
        self.drift["findings"] = [x for x in self.drift["findings"] if x["id"] != finding_id]
        self._publish()
        return {"dismissed": finding_id}

    # ---------------- sharing a port

    def _share_event(self, kind, s, why=None):
        now = time.time()
        where = "on your network" if s.mode == "lan" else f"publicly via {s.tunnel_name}"
        detail = (f"shared {where} until {time.strftime('%H:%M', time.localtime(s.expires))}" if kind == "shared"
                  else f"share ended ({why or 'stopped'}) after {s.requests} request(s)")
        self.store.add_activity([{"id": f"{now:.6f}-{kind}-{s.id}", "ts": now, "type": kind, "port": s.port, "title": s.title,
                                  "level": "warn" if kind == "shared" and s.mode == "public" else "info", "detail": detail}])
        self.wake.set()

    def share_start(self, port, mode="lan", minutes=60, tunnel=None):
        row = next((r for r in (self.snapshot or {}).get("listeners", []) if r["port"] == port), None)
        if not row:
            raise ControlError(f"Nothing is listening on :{port}.", status=404)
        if row["risk"] in ("self", "foreign", "system", "app") or row["kind"] not in ("dev", "service", "other"):
            raise ControlError("Porthaven only shares your own dev servers, not desktop apps, system services, databases or itself.", status=403)
        risk = row.get("exposureRisk") or {}
        fid = (row.get("framework") or {}).get("id")
        if risk.get("level") in ("critical", "high") or fid in ("inspector", "jupyter") or \
                set((row.get("probe") or {}).get("flags") or []) & {"werkzeug-debugger", "django-debug"}:
            raise ControlError("This server runs a debugger or debug pages that let visitors run code; Porthaven will not share it.", status=403)
        if not (row.get("probe") or {}).get("ok"):
            raise ControlError(f":{port} does not answer HTTP, so there is nothing to open in a browser.")
        if any(s.port == port and s.mode == mode for s in self.shares.items.values()):
            raise ControlError(f":{port} is already shared that way.", status=409)
        try:
            s = self.shares.start(row, mode, minutes, self.lan_ip, tunnel)
        except (share.ShareError, OSError) as err:
            raise ControlError(str(err)) from err
        self._publish()
        return s.summary()

    def share_stop(self, share_id):
        s = self.shares.stop(share_id, "stopped from Porthaven")
        if not s:
            raise ControlError("No such share.", status=404)
        self._publish()
        return {"stopped": share_id}

    # ---------------- HTTPS for stable names

    def _https_check(self):
        try:
            self.https["status"] = self.tls.status()
        finally:
            self.https["checkedAt"] = time.time()
        self._publish()

    def https_status(self, refresh=False):
        if refresh or not self.https.get("status"):
            self._https_check()
        return {**self.https}

    def https_trust(self):
        """Run the commands that make this system trust the CA. Each one asks for your permission (a password dialog)."""
        try:
            self.tls.ensure_ca()
        except tls.TlsError as err:
            raise ControlError(str(err)) from err
        cmds = self.tls.trust_commands()
        if any(c[0] == "sudo" for c in cmds):
            raise ControlError("On Linux, trusting the CA needs sudo; run `porthaven https trust` in a terminal.", status=409,
                               commands=[" ".join(c) for c in cmds])
        for c in cmds:
            try:
                out = subprocess.run(c, capture_output=True, text=True, timeout=120)
            except (OSError, subprocess.TimeoutExpired) as err:
                raise ControlError(f"{c[0]} failed: {err}") from err
            if out.returncode:
                raise ControlError(f"{' '.join(c[:2])} failed: {(out.stderr or out.stdout).strip()[:300]}")
        self.tls.reset()
        return self.https_status(refresh=True)

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
        found = compose.ps()
        if found is None:
            if not shutil.which("docker"):
                self.docker, self.containers = {}, []
            return
        mapping = {}
        for c in found:
            for p in c["ports"]:
                mapping[p["host"]] = {"id": c["id"], "name": c["name"], "image": c["image"], "status": c["status"],
                                      "mapping": p["mapping"], "service": c["service"], "workdir": c["workdir"]}
        self.docker, self.containers = mapping, found

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
            dk = self.docker.get(port) if fw and fw["id"] == "docker" or (row["command"] or "").startswith(("com.docke", "vpnkit", "OrbStack")) else None
            if m:
                app = m.app_id
            elif dk and dk.get("service"):   # a compose service's port belongs to the saved compose app for that folder
                app = next((a["id"] for a in self.store.apps() if (a.get("compose") or {}).get("service") == dk["service"]
                            and dk.get("workdir") and realpath(a["cwd"]) == realpath(dk["workdir"])), None)
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
                "exposureRisk": self.exposure_risk({"exposure": exposure, "port": port}, args, fw, kind, pr) if row["uid"] == self.uid or kind == "database" else None,
                "stableUrl": f"http://{slugs[app]}.localhost:{self.port}/" if app in slugs and self.port else None,
                "stableHttpsUrl": f"https://{slugs[app]}.localhost:{self.https['port']}/" if app in slugs and self.https["enabled"] else None,
                "leak": self.leaks.get(pid),
            })
        rows = self._merge_workers(rows, procs)
        self._mark_twins(rows)
        for r in rows:   # Porthaven's own ports say what each one is for
            if r["pid"] == self.pid:
                r["title"] = ("Porthaven · dashboard" if r["port"] == self.port else
                              "Porthaven · HTTPS for stable names" if r["port"] == self.https["port"] and self.https["enabled"] else
                              "Porthaven · shared link" if r["port"] in self.shares.relay_ports() else r["title"])
        shares = self.shares.summaries()
        relays = self.shares.relay_ports()
        for r in rows:
            if r["project"]:
                r["project"] = {**r["project"], "git": gitinfo.info(r["project"]["root"])}
            r["agent"] = self.agent_for(r, self.managed.get(r["managed"]) if r["managed"] else None)
            r["shares"] = [x for x in shares if x["port"] == r["port"]]
            if r["port"] in relays:   # Porthaven's own relay for a share: on the network on purpose, for a while
                r["shareRelay"] = relays[r["port"]].id
                r["exposureRisk"] = None
        apps = [self.app_status(a, rows) for a in self.store.apps()]
        with self.lock:
            links = list(self.links)
        service_map = self.netmap.build(rows, procs, links, self.store.apps(), self.self_pids, self.lan_ip, now)
        findings = self.drift["findings"]
        leftovers = [r for r in rows if r.get("agent") and not r["agent"]["alive"]]
        dev = [r for r in rows if r["kind"] in ("dev", "service", "tool", "other", "database")]
        projects = {r["project"]["root"] for r in rows if r["project"]}
        mine = {r["pid"]: r for r in dev}
        return {
            "version": __version__, "scannedAt": time.time(), "scanMs": self.scan_ms, "error": self.error,
            "me": {"pid": self.pid, "port": self.port, "startedAt": self.started_at, "user": os.environ.get("USER"),
                   "home": str(Path.home()), "docker": bool(shutil.which("docker")), "lanIp": self.lan_ip,
                   "cli": str(Path(__file__).resolve().parent.parent / "bin" / ("porthaven.cmd" if system.IS_WINDOWS else "porthaven")),
                   "https": {k: self.https[k] for k in ("enabled", "port", "error", "status")}, "tunnels": share.tunnels()},
            "listeners": rows, "apps": apps, "settings": self.store.settings,
            "summary": {"listening": len({r["port"] for r in rows}), "dev": len({r["port"] for r in dev}),
                        "projects": len(projects), "exposed": len({r["port"] for r in rows if r["exposure"] == "network"}),
                        "system": len({r["port"] for r in rows if r["kind"] in ("system", "app")}),
                        "appsRunning": sum(a["state"] in ("running", "starting", "external") for a in apps),
                        "cpu": round(sum(r["cpu"] or 0 for r in mine.values()), 1),
                        "memMb": round(sum(r["memMb"] or 0 for r in mine.values()), 1),
                        "idle": len([r for r in rows if r["idleFor"]]),
                        "critical": len([r for r in rows if (r.get("exposureRisk") or {}).get("level") == "critical"]),
                        "idleMemMb": round(sum(r["memMb"] or 0 for r in rows if r["idleFor"]), 1),
                        "watchedDown": [int(p) for p, meta in self.store.data["ports"].items()
                                        if meta.get("watched") and int(p) not in {r["port"] for r in rows}],
                        "portClaims": {str(p): names for p, names in teamfile.port_claims(self.store.apps()).items()},
                        "agentLeftovers": len({r["pid"] for r in leftovers}),
                        "agentLeftoverMemMb": round(sum(r["memMb"] or 0 for r in leftovers), 1),
                        "leaks": len([r for r in rows if r.get("leak")]),
                        "drift": len([f for f in findings if f["level"] == "warn"]),
                        "errors": sum(a.get("errors", 0) for a in apps),
                        "brokenLinks": len([e for e in service_map["edges"] if e["state"] == "broken"])},
            "activity": self.store.activity()[-150:],
            "workspaces": self.store.data.get("workspaces", []),
            "map": service_map,
            "drift": {"findings": findings, "at": self.drift["at"]},
            "shares": shares,
        }

    def _health(self, port):
        h = list(self.health.get(port, []))
        if not h:
            return None
        return {"ms": [x[1] for x in h], "status": [x[2] for x in h], "up": sum(1 for x in h if x[2] and x[2] < 500), "n": len(h)}

    def _idle_for(self, port, kind, proc, conns, now, idle_after):
        """Seconds a dev server has gone without a connection and without using CPU, once that passes the
        idle threshold; None while it is in use. Before Porthaven saw a connection, the process start counts."""
        if kind not in ("dev", "other") or conns or (proc.get("cpu") or 0) >= 1 or proc.get("elapsed") is None:
            return None
        since = self.last_active.get(port) or (now - proc["elapsed"])
        idle = now - since
        return round(idle) if idle >= idle_after else None

    def app_slugs(self):
        """Stable names for saved apps: http://<slug>.localhost:<porthaven port>/ always reaches the app,
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
        """(port, name, app id) a stable name points at now: a saved app's current port, or a project's single port."""
        slugs = self.app_slugs()
        rows = (self.snapshot or {}).get("listeners", [])
        for app_id, sl in slugs.items():
            if sl == slug:
                st = next((a for a in (self.snapshot or {}).get("apps", []) if a["id"] == app_id), None)
                ports = (st or {}).get("ports") or []
                web = [r["port"] for r in rows if r["port"] in ports and (r.get("probe") or {}).get("ok")]
                return (web or ports or [None])[0], (st or {}).get("name") or (self.store.app(app_id) or {}).get("name"), app_id
        hits = [r for r in rows if r["project"] and slugify(r["project"]["name"]) == slug and (r.get("probe") or {}).get("ok")]
        if len({r["port"] for r in hits}) == 1:
            return hits[0]["port"], hits[0]["title"], None
        return None, None, None

    # ------------------------------------------------------------ requests seen by the stable-name proxy

    def record_request(self, slug, app_id, entry):
        self.requests[slug].append(entry)
        if app_id:
            self.last_traffic[app_id] = time.time()

    def app_requests(self, app_id):
        slug = self.app_slugs().get(app_id)
        if not slug:
            raise ControlError("No such app.", status=404)
        return {"slug": slug, "requests": [relay.public(e) for e in list(self.requests.get(slug, []))]}

    def _request(self, app_id, rid):
        slug = self.app_slugs().get(app_id)
        if not slug:
            raise ControlError("No such app.", status=404)
        e = next((x for x in list(self.requests.get(slug, [])) if x.get("id") == int(rid)), None)
        if not e:
            raise ControlError("That request is no longer kept (Porthaven keeps the last 300 per app).", status=404)
        return slug, e

    def request_detail(self, app_id, rid):
        return relay.detail(self._request(app_id, rid)[1])

    def replay_request(self, app_id, rid, edits=None):
        """Send a recorded request to the app again, as it was or with changes (method, path, headers, body)."""
        slug, e = self._request(app_id, rid)
        edits = edits or {}
        method = str(edits.get("method") or e["method"]).upper()
        if not re.fullmatch(r"[A-Z]{3,10}", method):
            raise ControlError("A method is a word such as GET or POST.")
        path = str(edits.get("path") or e["path"])
        if not path.startswith("/"):
            raise ControlError("The path must start with /.")
        headers = edits.get("headers")
        headers = [[str(k), str(v)] for k, v in headers] if isinstance(headers, list) else list(e.get("_reqHeaders") or [])
        if any("\r" in k + v or "\n" in k + v for k, v in headers):
            raise ControlError("Header names and values cannot contain line breaks.")
        body = edits["body"].encode() if isinstance(edits.get("body"), str) else (e.get("_reqBody") or b"")
        port, _, _ = self.proxy_target(slug)
        if not port:
            port = self.wake_app(app_id) if self.store.app(app_id) else None
        if not port:
            raise ControlError("The app is not running; start it and replay again.", status=409)
        try:
            entry = relay.send(int(port), method, path, headers, body)
        except RuntimeError as err:
            raise ControlError(str(err)) from err
        entry["replayOf"] = e["id"]
        self.record_request(slug, app_id, entry)
        return relay.detail(entry)

    def requests_har(self, app_id):
        slug = self.app_slugs().get(app_id)
        if not slug:
            raise ControlError("No such app.", status=404)
        return relay.har([e for e in list(self.requests.get(slug, [])) if not e.get("ws")], __version__)

    # ------------------------------------------------------------ searching every app's output

    def log_search(self, query="", app_ids=None, regex=False, case=False, errors_only=False, since=None, limit=500):
        sources = []
        for a in self.store.apps():
            if app_ids and a["id"] not in app_ids:
                continue
            m = self.managed.get(a["id"])
            lines = m.tail(0, 4000) if m else logsearch.file_lines(self.store.log_path(a["id"]))
            sources.append((a, lines))
        try:
            res = logsearch.search(sources, query, regex, case, errors_only, since, max(1, min(2000, int(limit))))
        except ValueError as err:
            raise ControlError(str(err)) from err
        now = time.time()
        res["recentErrors"] = [{"appId": a, "app": (self.store.app(a) or {}).get("name"), "n": len(m.recent_errors(600, now)),
                                "last": (m.recent_errors(600, now) or [(0, 0, None)])[-1][2]}
                               for a, m in self.managed.items() if m.recent_errors(600, now)]
        return res

    # ------------------------------------------------------------ sleep when idle, wake on request

    def _sleep_idle_apps(self):
        now = time.time()
        for app in self.store.apps():
            minutes = int(app.get("sleepAfter") or 0)
            m = self.managed.get(app["id"])
            if not minutes or not m or not m.alive or m.status == "starting":
                continue
            last = max(self.last_traffic.get(app["id"], 0), m.started_at)
            if now - last >= minutes * 60:
                m.sleeping = True
                self.store.add_activity([{"id": f"{now:.6f}-sleep-{app['id']}", "ts": now, "type": "slept", "port": m.port,
                                          "title": app["name"], "appId": app["id"], "level": "info",
                                          "detail": f"no traffic for {minutes} min" + (" · wakes on the next request" if app.get("wake", True) else "")}])
                m.stop(grace=float(self.store.settings["graceSeconds"]), extra_pids=classify.descendants(m.pid, self.procs))
                self.wake.set()

    def wake_app(self, app_id, timeout=60.0):
        """Start a sleeping (or stopped) app for a request to its stable name and wait until it answers."""
        app = self.store.app(app_id)
        if not app or not (app.get("wake", True) and (app.get("sleepAfter") or app.get("wake"))):
            return None
        if self.is_running(app_id):
            ok, _ = self.wait_ready(app, timeout)
        else:
            self.store.add_activity([{"id": f"{time.time():.6f}-woke-{app_id}", "ts": time.time(), "type": "woke", "port": app.get("port"),
                                      "title": app["name"], "appId": app_id, "level": "info", "detail": "a request arrived"}])
            # Windows can hold a killed server's port for a moment, so wait for it, and try once more if the app exits at once.
            deadline = time.time() + 5
            while app.get("port") and not probe.port_free(int(app["port"])) and time.time() < deadline:
                time.sleep(0.1)
            ok = False
            for _ in range(2):
                try:
                    self.start_app(app_id, force=True)
                except ControlError as err:
                    suggest = (err.extra.get("conflict") or {}).get("suggest")
                    if not suggest:
                        return None
                    self.start_app(app_id, port=suggest, force=True)
                self.refresh()
                ok, _ = self.wait_ready(app, timeout)
                m = self.managed.get(app_id)
                if ok or (m and m.alive):
                    break
                time.sleep(0.5)
        self.refresh()
        self.last_traffic[app_id] = time.time()
        if not ok:
            return None
        m = self.managed.get(app_id)   # the scan can lag behind a server that just started listening (Windows' netstat)
        return self.app_ports().get(app_id) or (m.port if m and m.alive else None)

    # ------------------------------------------------------------ git worktrees

    def app_worktrees(self, app_id):
        app = self.store.app(app_id)
        if not app:
            raise ControlError("No such app.", status=404)
        g = gitinfo.info(os.path.expanduser(app["cwd"]))
        if not g:
            raise ControlError(f"{app['name']} is not in a git repository.")
        trees = gitinfo.worktrees(g["root"])
        derived = {realpath(a["cwd"]): a for a in self.store.apps() if a.get("worktreeOf") == app_id}
        rel = os.path.relpath(realpath(app["cwd"]), realpath(g["root"]))
        for t in trees:
            t["appCwd"] = os.path.normpath(os.path.join(t["path"], rel))
            t["current"] = realpath(t["path"]) == realpath(g["root"])
            d = derived.get(realpath(t["appCwd"]))
            t["app"] = {"id": d["id"], "name": d["name"]} if d else None
        return {"repo": g["repo"], "branch": g["branch"], "worktrees": trees}

    def run_in_worktree(self, app_id, worktree, start=True, actor=None, session=None):
        app = self.store.app(app_id)
        info = self.app_worktrees(app_id)
        tree = next((t for t in info["worktrees"] if realpath(t["path"]) == realpath(worktree)), None)
        if not tree:
            raise ControlError(f"{worktree} is not a worktree of {info['repo']}. Worktrees: "
                               + ", ".join(t["path"] for t in info["worktrees"]), status=404)
        if tree["current"]:
            raise ControlError(f"That is {app['name']}'s own checkout; start {app['name']} itself.")
        if not os.path.isdir(tree["appCwd"]):
            raise ControlError(f"{tree['appCwd']} does not exist in that worktree.")
        branch = tree["branch"] or os.path.basename(tree["path"])
        if tree["app"]:
            derived = self.store.app(tree["app"]["id"])
        else:
            used = {r["port"] for r in (self.snapshot or {}).get("listeners", [])} | {a.get("port") for a in self.store.apps()}
            base = int(app.get("port") or 3000)
            port = next(p for p in probe.free_ports(base + 1, 20) if p not in used)
            base_slug = self.app_slugs().get(app_id) or slugify(app["name"])
            derived = self.store.upsert_app({
                "name": f"{app['name']} ({branch})", "cwd": tree["appCwd"], "command": app["command"], "port": port,
                "env": app.get("env") or {}, "openPath": app.get("openPath", "/"), "group": app.get("group"),
                "color": app.get("color"), "health": app.get("health"), "dependsOn": app.get("dependsOn") or [],
                "slug": f"{slugify(branch.split('/')[-1])}.{base_slug}", "worktreeOf": app_id, "branch": branch})
        run = self.start_app(derived["id"], force=True, actor=actor, session=session) if start and not self.is_running(derived["id"]) else None
        self._publish()
        st = next((a for a in self.snapshot["apps"] if a["id"] == derived["id"]), derived)
        return {"app": st, "run": run, "stableUrl": st.get("stableUrl")}

    # ------------------------------------------------------------ exposure guard

    @staticmethod
    def exposure_risk(row, args, fw, kind, pr):
        if row["exposure"] != "network" and "--inspect=0.0.0.0" not in (args or ""):
            return None
        flags = set((pr or {}).get("flags") or [])
        fid = (fw or {}).get("id")
        if "--inspect" in (args or "") or fid == "inspector" or row["port"] == 9229:
            return {"level": "critical", "title": "Node debugger open to the network",
                    "why": "Anyone who can reach this machine can run code in this process through the inspector.",
                    "fix": "Start Node with --inspect=127.0.0.1:9229 (the default), never --inspect=0.0.0.0."}
        if "werkzeug-debugger" in flags:
            return {"level": "critical", "title": "Werkzeug debug console open to the network",
                    "why": "The interactive debugger runs Python code typed into the browser.",
                    "fix": "Run Flask without --host=0.0.0.0, or turn debug mode off when the server must be reachable."}
        if "django-debug" in flags:
            return {"level": "high", "title": "Django debug pages open to the network",
                    "why": "DEBUG = True pages show settings, paths and parts of your code to anyone on the network.",
                    "fix": "Use `runserver 127.0.0.1:8000`, or DEBUG = False for anything others can reach."}
        if kind == "database" or fid in ("postgres", "mysql", "redis", "mongo", "elastic"):
            return {"level": "high", "title": f"{(fw or {}).get('label', 'Database')} open to the network",
                    "why": "Local databases often have no password or a default one.",
                    "fix": "Bind it to 127.0.0.1 (listen_addresses / bind / bindIp), or put a strong password on it."}
        if fid == "jupyter":
            return {"level": "high", "title": "Jupyter open to the network", "why": "A notebook server runs any code.",
                    "fix": "Start it with --ip=127.0.0.1 and keep the token on."}
        if kind in ("dev", "service", "other"):
            return {"level": "medium", "title": "Dev server reachable from your network",
                    "why": "Others on the same Wi-Fi can open it.", "fix": "Bind to 127.0.0.1 (for Vite, drop --host) unless you test from another device."}
        return None

    @staticmethod
    def _mark_twins(rows):
        """Two separate servers on one port: possible when one listens on IPv4 (127.0.0.1) and the other on IPv6 (::1),
        even with --strictPort. `localhost` then reaches either one, depending on the client, so each row says so."""
        by_port = {}
        for r in rows:
            by_port.setdefault(r["port"], []).append(r)
        for port_rows in by_port.values():
            if len({r["pid"] for r in port_rows}) < 2:
                continue
            for r in port_rows:
                others = [x for x in port_rows if x["pid"] != r["pid"]]
                older = all((r["uptime"] or 0) >= (x["uptime"] or 0) for x in others)
                r["twins"] = {"older": older, "others": [{"pid": x["pid"], "title": x["title"], "addresses": x["addresses"],
                                                         "uptime": x["uptime"], "id": x["id"]} for x in others]}

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
        if not (m and m.alive) and not mine and m and getattr(m, "sleeping", False):
            state = "sleeping"
        holder = None
        if expected and expected not in ports:
            h = next((r for r in rows if r["port"] == expected), None)
            if h:
                holder = {"pid": h["pid"], "title": h["title"], "command": h["display"], "risk": h["risk"]}
        container = compose.container_for(self.containers, app) if app.get("compose") else None
        if container and state in ("stopped", "exited", "crashed"):
            state = "external"   # started with `docker compose up -d` outside Porthaven
        slug = self.app_slugs().get(app["id"])
        errs = m.recent_errors() if m else []
        return {**app, "state": state, "ports": ports, "pids": sorted({r["pid"] for r in mine}),
                "stableUrl": f"http://{slug}.localhost:{self.port}/" if slug and self.port else None, "slugName": slug,
                "stableHttpsUrl": f"https://{slug}.localhost:{self.https['port']}/" if slug and self.https["enabled"] else None,
                "errors": len(errs), "lastError": errs[-1][2] if errs else None,
                "container": {"name": container["name"], "status": container["status"], "health": compose.health(container["status"])} if container else None,
                "drift": bool(expected and ports and expected not in ports), "conflict": holder,
                "run": m.summary() if m else None, "logLines": m.seq if m else 0,
                "logFile": str(self.store.log_path(app["id"])) if self.store.log_path(app["id"]).exists() else None}

    # ------------------------------------------------------------ actions

    def _row_for_pid(self, pid, stopped=False):
        row = next((r for r in (self.snapshot or {}).get("listeners", []) if r["pid"] == pid), None)
        if row is None and stopped and pid in self.stopped:
            row = self.stopped[pid][1]
        return row

    def kill(self, pid, mode="process", force=True, confirm=False, actor=None):
        procs = self.procs
        if pid not in procs:
            raise ControlError(f"Process {pid} is not running any more.", status=404)
        known = {r["pid"] for r in self.snapshot["listeners"]} | {r["root"]["pid"] for r in self.snapshot["listeners"] if r["root"]}
        known |= {d for k in list(known) for d in classify.descendants(k, procs)}
        if pid not in known:
            raise ControlError(f"Process {pid} is not one of the listening apps Porthaven shows, so Porthaven will not stop it.", status=403)
        row = self._row_for_pid(pid)
        p = procs[pid]
        kind = row["kind"] if row else "dev"
        risk = self.risk(pid, kind, p["uid"])
        if risk == "self":
            raise ControlError("That is Porthaven itself. Stop Porthaven from its terminal (Ctrl-C) instead.", status=403)
        if risk == "foreign":
            raise ControlError(f"Process {pid} belongs to another user; stopping it needs sudo, which Porthaven never uses.", status=403)
        if risk in ("system", "app") and not confirm:
            raise ControlError("This is a desktop app or a system service. Confirm to stop it.", status=409, needsConfirm=risk)
        if row:   # before signalling: the scan can drop the port while the stop still waits for the processes to exit
            self._remember_stopped(pid, row)
        m = self.managed_for(pid)
        if m:
            m.stopping = True   # stopped on purpose from Porthaven: not a crash
        if m and mode == "app":
            res = m.stop(grace=float(self.store.settings["graceSeconds"]), extra_pids=classify.descendants(m.pid, procs))
            return self._after_kill(res, pid, "app", row, actor)
        if mode == "app":
            root = (row["root"] or {}).get("pid") if row and row.get("root") else pid
            pids = [root] + classify.descendants(root, procs)
        else:
            pids = [pid]
        pids = [x for x in pids if x not in self.self_pids and procs.get(x, {}).get("uid") == self.uid]
        res = signal_and_wait(pids, grace=float(self.store.settings["graceSeconds"]), force=force)
        return self._after_kill(res, pid, mode, row, actor)

    def _remember_stopped(self, pid, row):
        """Keep the row of an app stopped from Porthaven for an hour, so Restart can run it again once its port is gone."""
        self.stopped[pid] = (time.time(), row)
        while len(self.stopped) > 50 or time.time() - next(iter(self.stopped.values()))[0] > 3600:
            self.stopped.popitem(last=False)

    def _after_kill(self, res, pid, mode, row, actor=None):
        ev = {"id": f"{time.time():.6f}-kill-{pid}", "ts": time.time(), "type": "killed", "pid": pid,
              "port": row["port"] if row else None, "title": row["title"] if row else str(pid), "level": "info",
              "detail": f"{len(res['exited']) + len(res['killed'])} process(es) stopped" + (f", {len(res['killed'])} forced" if res["killed"] else "")
              + (f" · by {actor}" if actor else "")}
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
        if getattr(m, "sleeping", False):   # put to sleep on purpose; the "slept" event already says so
            self.wake.set()
            return
        ev = {"id": f"{time.time():.6f}-exit-{m.app_id}", "ts": time.time(), "type": m.status, "pid": m.pid, "port": m.port,
              "title": m.name, "appId": m.app_id, "level": "error" if m.status == "crashed" else "info",
              "detail": f"exit code {m.exit_code}" if m.exit_code is not None else None, "notify": m.status == "crashed"}
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

    # ------------------------------------------------------------ starting apps and stacks

    def app_ports(self):
        """{app id: the port it runs on now} for running apps. An app Porthaven just started may not be in the
        last scan yet; the port it was started on counts until then."""
        out = {a["id"]: a["ports"][0] for a in (self.snapshot or {}).get("apps", []) if a.get("ports")}
        for app_id, m in list(self.managed.items()):
            if app_id not in out and m.port and m.alive:
                out[app_id] = int(m.port)
        return out

    def is_running(self, app_id):
        st = next((a for a in (self.snapshot or {}).get("apps", []) if a["id"] == app_id), None)
        m = self.managed.get(app_id)
        return bool((m and m.alive) or (st and st["state"] in ("running", "starting", "external")))

    def start_app(self, app_id, port=None, force=False, take_over=False, with_deps=True, actor=None, session=None):
        app = self.store.app(app_id)
        if not app:
            raise ControlError("No such app.", status=404)
        if with_deps and app.get("dependsOn"):
            try:
                order = stacks.start_order(self.store.apps(), self.app_slugs(), [app_id])
            except stacks.StackError as err:
                raise ControlError(str(err)) from err
            waiting = [a for a in order[:-1] if not self.is_running(a["id"])]
            if waiting:
                threading.Thread(target=self._start_stack, args=(order, {app_id: port}, take_over, actor, session), daemon=True,
                                 name=f"porthaven-stack-{app_id}").start()
                return {"stack": [a["name"] for a in order], "starting": [a["name"] for a in waiting] + [app["name"]]}
        return self._launch(app, port, force, take_over, actor, session)

    def _launch(self, app, port=None, force=False, take_over=False, actor=None, session=None):
        app_id = app["id"]
        current = self.managed.get(app_id)
        if current and current.alive:
            raise ControlError(f"{app['name']} is already running (pid {current.pid}).", status=409)
        status = self.app_status(app, self.snapshot["listeners"] if self.snapshot else [])
        if status["state"] == "external" and not force:
            raise ControlError(f"{app['name']} is already running outside Porthaven on port {', '.join(map(str, status['ports']))}.",
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
        ports = self.app_ports()
        if want:
            ports[app_id] = int(want)
        wired = stacks.wiring(self.store.apps(), self.app_slugs(), ports)
        agent = agents.from_header(session, self.procs, time.time()) if session else None
        m = Managed(app, int(want) if want else None, self.store.log_path(app_id), self._on_exit, self.store.root / "run", wired=wired,
                    agent=agent)
        self.managed[app_id] = m
        self.store.add_activity([{"id": f"{time.time():.6f}-start-{app_id}", "ts": time.time(), "type": "started", "pid": m.pid,
                                  "port": m.port, "title": app["name"], "appId": app_id, "level": "info",
                                  **({"detail": f"by {actor}"} if actor else {})}])
        self.wake.set()
        return m.summary()

    def wait_ready(self, app, timeout=90.0):
        """Until the app listens and, when it has a health path, that path answers 2xx/3xx."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = self.managed.get(app["id"])
            if m and not m.alive:
                return False, f"{app['name']} exited (code {m.exit_code}) before it was ready"
            port = self.app_ports().get(app["id"]) or (m.port if m else None)
            if app.get("compose"):   # a compose service is ready when its container's health check passes
                c = compose.container_for(compose.ps() or [], app)
                h = compose.health(c["status"]) if c else None
                if c and h in ("healthy", None) and (h == "healthy" or not port or not probe.port_free(int(port))) and not app.get("health"):
                    return True, None
                if not c or h in ("starting", "unhealthy"):
                    time.sleep(0.5)
                    continue
            if port and not probe.port_free(int(port)):
                if not app.get("health"):
                    return True, None
                r = probe.probe(int(port), path=app["health"])
                if r.get("ok") and r.get("status", 500) < 400:
                    return True, None
            time.sleep(0.5)
        return False, f"{app['name']} was not ready within {int(timeout)} s"

    def _start_stack(self, order, ports=None, take_over=False, actor=None, session=None):
        """Start `order` (dependencies first). Wait for an app's health only when a later app needs it, and when an
        app fails, skip just the apps that depend on it."""
        ports = ports or {}
        apps, slugs = self.store.apps(), self.app_slugs()
        deps = {a["id"]: {d["id"] for d in (stacks.resolve(apps, slugs, r) for r in a.get("dependsOn") or []) if d} for a in order}
        needed = {d for ds in deps.values() for d in ds}
        failed, ok_all = {}, True
        for app in order:
            blocked = [failed[d] for d in deps[app["id"]] if d in failed]
            if blocked:
                failed[app["id"]] = app["name"]
                self._stack_event(app, "crashed", f"not started: it needs {', '.join(blocked)}", "error")
                ok_all = False
                continue
            if not self.is_running(app["id"]):
                try:
                    self._launch(app, ports.get(app["id"]), take_over=take_over, actor=actor, session=session)
                except ControlError as err:
                    failed[app["id"]] = app["name"]
                    self._stack_event(app, "crashed", f"could not start: {err}", "error")
                    ok_all = False
                    continue
            if app["id"] in needed:
                self.refresh()
                ok, why = self.wait_ready(app)
                if not ok:
                    failed[app["id"]] = app["name"]
                    self._stack_event(app, "crashed", f"{why}; apps that need it were not started", "error")
                    ok_all = False
                    continue
                self._stack_event(app, "ready", "healthy" + (f" ({app['health']})" if app.get("health") else ""), "info")
        return ok_all

    def _stack_event(self, app, kind, detail, level):
        self.store.add_activity([{"id": f"{time.time():.6f}-stack-{app['id']}", "ts": time.time(), "type": kind,
                                  "port": self.app_ports().get(app["id"]) or app.get("port"), "title": app["name"],
                                  "appId": app["id"], "level": level, "detail": detail, "notify": level == "error"}])
        self.wake.set()

    def stop_app(self, app_id):
        app = self.store.app(app_id)
        if not app:
            raise ControlError("No such app.", status=404)
        m = self.managed.get(app_id)
        if app.get("compose") and (m and m.alive or compose.container_for(self.containers, app)):
            if m:
                m.stopping = True
            try:   # stop the container cleanly first; the attached `docker compose up` then ends by itself
                compose.stop(app)
            except (compose.ComposeError, OSError, subprocess.TimeoutExpired) as err:
                if not (m and m.alive):
                    raise ControlError(str(err)) from err
            self.docker_at = 0
            if not (m and m.alive):
                self.wake.set()
                return {"stopped": [app["name"]]}
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
        row = self._row_for_pid(pid, stopped=True)
        if not row:
            raise ControlError("That process is not listening on a port any more.", status=404)
        if row.get("appId") and self.store.app(row["appId"]):
            return self.store.app(row["appId"])   # Porthaven runs it already: reuse that app, not a copy
        root = row["root"] or {"pid": pid, "args": row["args"], "cwd": row["cwd"]}
        cwd = root.get("cwd") or row["cwd"]
        if not cwd:
            raise ControlError("Porthaven could not read that process's folder, so it cannot run it again.")
        command = classify.rerunnable(root["args"])
        for a in self.store.apps():
            if realpath(a["cwd"]) == realpath(cwd) and a["command"] in (root["args"], command):
                return a
        if (row["framework"] or {}).get("id") == "vite" and "--port" not in command and root["pid"] == pid:
            command += " --port {port} --strictPort"
        default = (row["project"] or {}).get("name") or row["title"]
        return self.store.upsert_app({"name": name or default, "cwd": cwd, "command": command, "port": row["port"]})

    def restart_process(self, pid):
        app = self.app_from_process(pid)
        row = self._row_for_pid(pid)
        if row:
            self.kill(pid, mode="app", confirm=True)
        else:   # already stopped (or still stopping): run it again once the port is released
            row = self._row_for_pid(pid, stopped=True)
            if row.get("risk") in ("self", "foreign", "system", "app"):
                raise ControlError("Porthaven only runs again the dev servers it shows as yours.", status=403)
        deadline = time.time() + float(self.store.settings["graceSeconds"]) + 5   # a stop may wait out the grace period
        while time.time() < deadline and not probe.port_free(row["port"]):
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
            raise ControlError("Porthaven only opens folders of apps it shows.", status=403)
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
                    if self.is_running(a["id"]):
                        out[a["name"]] = "already running"
                        continue
                    out[a["name"]] = "started"
                else:
                    self.stop_app(a["id"])
                    out[a["name"]] = "stopped"
            except ControlError as err:
                out[a["name"]] = str(err)
        if action == "start":
            try:
                order = stacks.start_order(self.store.apps(), self.app_slugs(), [a["id"] for a in apps])
            except stacks.StackError as err:
                raise ControlError(str(err)) from err
            threading.Thread(target=self._start_stack, args=(order,), daemon=True, name=f"porthaven-group-{group}").start()
        self.wake.set()
        return {"group": group, "results": out}

    def export_apps(self):
        keep = ("name", "cwd", "command", "port", "env", "openPath", "group", "color", "autoRestart", "slug")
        return {"porthaven": __version__, "exportedAt": time.time(),
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
        return {"range": rng, "seconds": seconds, "now": now, "porthavenStarted": self.started_at,
                "samples": self.metrics.query(seconds, 240, now),
                "activity": [e for e in self.store.activity() if e["ts"] >= now - seconds],
                "health": health}

    # ------------------------------------------------------------ porthaven.toml

    def import_teamfile(self, path):
        found = teamfile.find(path)
        if not found:
            raise ControlError(f"No {teamfile.NAME} in {path} or the folders above it.", status=404)
        try:
            apps = teamfile.load(found)
        except (teamfile.TeamfileError, OSError) as err:
            raise ControlError(str(err)) from err
        key_to_slug = {a["source"]["key"]: a["slug"] for a in apps}
        added, updated, ids = [], [], []
        for spec in apps:
            spec["dependsOn"] = [key_to_slug.get(d, d) for d in spec.get("dependsOn") or []]
            existing = next((a for a in self.store.apps() if (a.get("source") or {}) == spec["source"]), None)
            if not existing:   # an app saved by hand for the same folder and name becomes this file's app instead of a twin
                existing = next((a for a in self.store.apps() if not a.get("source")
                                 and realpath(a["cwd"]) == realpath(spec["cwd"])
                                 and (a.get("slug") == spec["slug"] or a["name"].lower() == spec["name"].lower())), None)
            if existing:
                saved = self.store.upsert_app(spec, existing["id"])
                updated.append(saved["name"])
            else:
                saved = self.store.upsert_app(spec)
                added.append(saved["name"])
            ids.append(saved["id"])
        self._publish()
        claims = {p: names for p, names in teamfile.port_claims(self.store.apps()).items()
                  if any(n in names for n in added + updated)}
        return {"file": str(found), "added": added, "updated": updated, "ids": ids, "claims": claims}

    def teamfile_up(self, path, actor=None, session=None):
        res = self.import_teamfile(path)
        try:
            order = stacks.start_order(self.store.apps(), self.app_slugs(), res["ids"])
        except stacks.StackError as err:
            raise ControlError(str(err)) from err
        threading.Thread(target=self._start_stack, args=(order, None, False, actor, session), daemon=True, name="porthaven-up").start()
        return {**res, "order": [a["name"] for a in order]}

    def teamfile_down(self, path):
        found = teamfile.find(path)
        if not found:
            raise ControlError(f"No {teamfile.NAME} in {path} or the folders above it.", status=404)
        mine = [a for a in self.store.apps() if (a.get("source") or {}).get("file") == str(found)]
        stopped = []
        for a in reversed(mine):
            if self.is_running(a["id"]):
                try:
                    self.stop_app(a["id"])
                    stopped.append(a["name"])
                except ControlError:
                    pass
        return {"file": str(found), "stopped": stopped}

    def export_teamfile(self, group=None, folder=None):
        apps = [a for a in self.store.apps() if (group is None or (a.get("group") or "") == group)]
        if folder:
            base = realpath(folder)
            apps = [a for a in apps if (realpath(a["cwd"]) or "").startswith(base)]
        if not apps:
            raise ControlError("No saved apps to export.", status=404)
        base = folder or os.path.commonpath([realpath(a["cwd"]) for a in apps])
        return {"base": base, "toml": teamfile.dump(apps, base)}

    # ------------------------------------------------------------ workspaces

    def save_workspace(self, name):
        running = [a for a in self.store.apps() if self.is_running(a["id"])]
        if not running:
            raise ControlError("No saved apps are running, so there is nothing to save.")
        ws = {"id": uuid_hex(), "name": (name or "Workspace").strip()[:60], "apps": [a["id"] for a in running], "createdAt": time.time()}
        with self.store.lock:
            self.store.data.setdefault("workspaces", []).append(ws)
            self.store.save()
        self._publish()
        return ws

    def restore_workspace(self, ws_id, stop_others=False, actor=None):
        ws = next((w for w in self.store.data.get("workspaces", []) if w["id"] == ws_id), None)
        if not ws:
            raise ControlError("No such workspace.", status=404)
        stopped = []
        if stop_others:
            for a in self.store.apps():
                if a["id"] not in ws["apps"] and self.is_running(a["id"]):
                    try:
                        self.stop_app(a["id"])
                        stopped.append(a["name"])
                    except ControlError:
                        pass
        ids = [i for i in ws["apps"] if self.store.app(i)]
        try:
            order = stacks.start_order(self.store.apps(), self.app_slugs(), ids)
        except stacks.StackError as err:
            raise ControlError(str(err)) from err
        threading.Thread(target=self._start_stack, args=(order, None, False, actor), daemon=True, name="porthaven-workspace").start()
        self.store.add_activity([{"id": f"{time.time():.6f}-ws-{ws_id}", "ts": time.time(), "type": "started", "title": ws["name"],
                                  "level": "info", "detail": f"workspace: {len(order)} app(s)" + (f", stopped {len(stopped)} other(s)" if stopped else "")}])
        return {"workspace": ws["name"], "starting": [a["name"] for a in order], "stopped": stopped}

    def delete_workspace(self, ws_id):
        with self.store.lock:
            before = len(self.store.data.get("workspaces", []))
            self.store.data["workspaces"] = [w for w in self.store.data.get("workspaces", []) if w["id"] != ws_id]
            self.store.save()
        self._publish()
        if before == len(self.store.data["workspaces"]):
            raise ControlError("No such workspace.", status=404)
        return {"deleted": ws_id}

    def shutdown_apps(self):
        for m in self.managed.values():
            if m.alive:
                m.stop(grace=2.0)
