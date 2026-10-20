"""Stopping processes and running saved apps with their output captured."""
from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import threading
import time

from pathlib import Path

from . import system
from .system import is_alive

ANSI_OSC = re.compile(r"\x1b\][^\x07]*\x07")


class ControlError(RuntimeError):
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def signal_and_wait(pids, grace=4.0, force=True, hard=False, tree=False):
    """Ask every pid to stop, wait up to `grace` seconds, then force the survivors when `force`.
    `hard` forces straight away. Works the same on Unix (SIGTERM, SIGKILL) and Windows (taskkill, /F)."""
    result = {"signalled": [], "exited": [], "killed": [], "survivors": [], "errors": {}}
    impolite = []
    for pid in pids:
        try:
            system.terminate(pid, force=hard, tree=tree)
            result["signalled"].append(pid)
        except ProcessLookupError:
            result["exited"].append(pid)
        except PermissionError:
            result["errors"][pid] = "not permitted (owned by another user)"
        except ChildProcessError:   # Windows console apps cannot be asked politely
            result["signalled"].append(pid)
            impolite.append(pid)
    deadline = time.monotonic() + (1.0 if hard or (impolite and len(impolite) == len(result["signalled"])) else grace)
    pending = list(result["signalled"])
    while pending and time.monotonic() < deadline:
        time.sleep(0.1)
        pending = [p for p in pending if is_alive(p) and not _zombie_reaped(p)]
    result["exited"] += [p for p in result["signalled"] if p not in pending]
    if pending and force and not hard:
        for pid in pending:
            try:
                system.terminate(pid, force=True, tree=tree)
                result["killed"].append(pid)
            except ProcessLookupError:
                result["exited"].append(pid)
            except (PermissionError, ChildProcessError):
                result["errors"][pid] = "not permitted"
        time.sleep(0.2)
        pending = [p for p in pending if is_alive(p) and not _zombie_reaped(p)]
    result["survivors"] = pending
    return result


def _zombie_reaped(pid):
    """Our own children linger as zombies until waited for; reap them so they stop counting as alive."""
    if system.IS_WINDOWS:
        return False
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == pid
    except ChildProcessError:
        return False


# ---------------------------------------------------------------- saved apps run by Porthaven

def expand_command(command, port):
    return command.replace("{port}", str(port)) if port else command


def launch_env(app, port):
    env = dict(os.environ)
    path = env.get("PATH", "")
    for extra in () if system.IS_WINDOWS else ("/opt/homebrew/bin", "/usr/local/bin"):
        if extra not in path.split(os.pathsep):
            path = f"{path}{os.pathsep}{extra}" if path else extra
    env["PATH"] = path
    env.update({"FORCE_COLOR": "1", "BROWSER": "none", "PORTHAVEN_APP": app["id"]})
    for k, v in (app.get("env") or {}).items():
        env[str(k)] = str(v)
    if port:
        env["PORT"] = str(port)
    return env


class Managed:
    """One launch of a saved app. The app writes straight to its log file in its own session, so it keeps
    running when Porthaven stops or restarts; Porthaven follows the file and picks the app up again on start."""

    def __init__(self, app, port, log_path, on_exit, run_dir, adopt=None):
        self.app_id = app["id"]
        self.name = app.get("name") or app["id"]
        self.lines = collections.deque(maxlen=4000)
        self.seq = 0
        self.cond = threading.Condition()
        self.exit_code = None
        self.stopping = False
        self.ended_at = None
        self.log_path = log_path
        self.on_exit = on_exit
        self.run_file = Path(run_dir) / f"{self.app_id}.json"
        self.proc = None
        if adopt:
            self.pid, self.port, self.command = adopt["pid"], adopt.get("port"), adopt["command"]
            self.cwd, self.started_at, self.status = adopt.get("cwd"), adopt["startedAt"], "running"
            size = log_path.stat().st_size if log_path.exists() else 0
            self.offset = max(adopt.get("offset", 0), size - 200_000)
            self._add(f"Porthaven restarted; {self.name} kept running (pid {self.pid})", "porthaven")
        else:
            self.port = port
            self.command = expand_command(app["command"], port)
            self.cwd = os.path.expanduser(app["cwd"])
            self.started_at = time.time()
            self.status = "starting"
            if not os.path.isdir(self.cwd):
                raise ControlError(f"The folder {self.cwd} does not exist. Edit the app and choose an existing folder.")
            with open(log_path, "ab") as f:
                f.write(f"\n── {time.strftime('%Y-%m-%d %H:%M:%S')}  $ {self.command}\n".encode())
                self.offset = f.tell()
            out = open(log_path, "ab")
            try:
                self.proc = subprocess.Popen(system.shell_argv(self.command), cwd=self.cwd, env=launch_env(app, port),
                                             stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                             **system.spawn_options())
            except OSError as err:
                raise ControlError(f"Could not start '{self.command}': {err}.") from err
            finally:
                out.close()   # the app holds its own copy of the file
            self.pid = self.proc.pid
            self._add(f"$ {self.command}", "porthaven")
            self._save_run()
        threading.Thread(target=self._follow, daemon=True, name=f"porthaven-log-{self.app_id}").start()

    @classmethod
    def adopt_all(cls, store, on_exit):
        """Apps Porthaven started before it last stopped and that are still running."""
        run_dir = store.root / "run"
        out = {}
        for f in run_dir.glob("*.json"):
            try:
                info = json.loads(f.read_text())
                alive = is_alive(info["pid"]) and system.group_leader(info["pid"])
            except (OSError, ValueError, KeyError):
                alive = False
            app = store.app(f.stem)
            if not alive or not app:
                f.unlink(missing_ok=True)
                continue
            out[app["id"]] = cls(app, info.get("port"), store.log_path(app["id"]), on_exit, run_dir, adopt=info)
        return out

    def _save_run(self):
        self.run_file.parent.mkdir(parents=True, exist_ok=True)
        self.run_file.write_text(json.dumps({"pid": self.pid, "port": self.port, "command": self.command, "cwd": self.cwd,
                                             "startedAt": self.started_at, "offset": self.offset}))

    def _add(self, text, stream="out"):
        with self.cond:
            self.seq += 1
            self.lines.append({"seq": self.seq, "t": time.time(), "text": text, "stream": stream})
            self.cond.notify_all()

    def _follow(self):
        buf = b""
        with open(self.log_path, "rb") as f:
            f.seek(self.offset)
            while True:
                try:
                    if os.path.getsize(self.log_path) < f.tell():
                        f.seek(0)   # the log was cleared
                except OSError:
                    pass
                chunk = f.read(65536)
                if chunk:
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for raw in lines:
                        # Windows ends lines with \r\n; a bare \r inside a line is a progress redraw: keep the last one.
                        text = ANSI_OSC.sub("", raw.decode("utf-8", "replace")).rstrip("\r").split("\r")[-1]
                        self._add(text)
                    continue
                if not self.alive:
                    break
                time.sleep(0.25)
        if buf:
            self._add(buf.decode("utf-8", "replace"))
        code = self.proc.wait() if self.proc else None
        self.exit_code = code
        self.ended_at = time.time()
        self.status = "stopped" if self.stopping else ("exited" if code in (0, None) else "crashed")
        ended = f"exit code {code}" if code is not None else "it ended"
        self._add(f"process ended ({ended})" + (" · stopped from Porthaven" if self.stopping else ""), "porthaven")
        try:
            self.run_file.unlink()
        except OSError:
            pass
        self.on_exit(self)

    @property
    def alive(self):
        if self.proc:
            return self.proc.poll() is None
        return is_alive(self.pid) and not _zombie_reaped(self.pid)

    def stop(self, grace=4.0, extra_pids=()):
        self.stopping = True
        system.terminate_group(self.pid)
        # On Windows the launched cmd.exe must take its children with it (taskkill /T).
        result = signal_and_wait([self.pid] + [p for p in extra_pids if p != self.pid], grace=grace, tree=system.IS_WINDOWS)
        if self.alive:
            system.terminate_group(self.pid, force=True)
        return result

    def summary(self):
        return {"pid": self.pid, "status": self.status, "exitCode": self.exit_code, "startedAt": self.started_at,
                "endedAt": self.ended_at, "port": self.port, "command": self.command, "lines": self.seq}

    def tail(self, after=0, limit=1000):
        with self.cond:
            return [ln for ln in self.lines if ln["seq"] > after][-limit:]
