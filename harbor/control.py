"""Stopping processes and running saved apps with their output captured."""
from __future__ import annotations

import collections
import os
import re
import signal
import subprocess
import threading
import time

from .system import is_alive

ANSI_OSC = re.compile(r"\x1b\][^\x07]*\x07")


class ControlError(RuntimeError):
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def signal_and_wait(pids, grace=4.0, force=True, sig=signal.SIGTERM):
    """Send `sig` to every pid, wait up to `grace` seconds, then SIGKILL survivors when `force`."""
    result = {"signalled": [], "exited": [], "killed": [], "survivors": [], "errors": {}}
    for pid in pids:
        try:
            os.kill(pid, sig)
            result["signalled"].append(pid)
        except ProcessLookupError:
            result["exited"].append(pid)
        except PermissionError:
            result["errors"][pid] = "not permitted (owned by another user)"
    deadline = time.monotonic() + (grace if sig != signal.SIGKILL else 1.0)
    pending = list(result["signalled"])
    while pending and time.monotonic() < deadline:
        time.sleep(0.1)
        pending = [p for p in pending if is_alive(p) and not _zombie_reaped(p)]
    result["exited"] += [p for p in result["signalled"] if p not in pending]
    if pending and force and sig != signal.SIGKILL:
        for pid in pending:
            try:
                os.kill(pid, signal.SIGKILL)
                result["killed"].append(pid)
            except ProcessLookupError:
                result["exited"].append(pid)
            except PermissionError:
                result["errors"][pid] = "not permitted"
        time.sleep(0.2)
        pending = [p for p in pending if is_alive(p) and not _zombie_reaped(p)]
    result["survivors"] = pending
    return result


def _zombie_reaped(pid):
    """Our own children linger as zombies until waited for; reap them so they stop counting as alive."""
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == pid
    except ChildProcessError:
        return False


# ---------------------------------------------------------------- saved apps run by Harbor

def expand_command(command, port):
    return command.replace("{port}", str(port)) if port else command


def launch_env(app, port):
    env = dict(os.environ)
    path = env.get("PATH", "")
    for extra in ("/opt/homebrew/bin", "/usr/local/bin"):
        if extra not in path.split(":"):
            path = f"{path}:{extra}" if path else extra
    env["PATH"] = path
    env.update({"FORCE_COLOR": "1", "BROWSER": "none", "HARBOR_APP": app["id"]})
    for k, v in (app.get("env") or {}).items():
        env[str(k)] = str(v)
    if port:
        env["PORT"] = str(port)
    return env


class Managed:
    """One running (or finished) launch of a saved app."""

    def __init__(self, app, port, log_path, on_exit):
        self.app_id = app["id"]
        self.name = app.get("name") or app["id"]
        self.port = port
        self.command = expand_command(app["command"], port)
        self.cwd = os.path.expanduser(app["cwd"])
        self.lines = collections.deque(maxlen=4000)
        self.seq = 0
        self.cond = threading.Condition()
        self.status = "starting"
        self.exit_code = None
        self.stopping = False
        self.started_at = time.time()
        self.ended_at = None
        self.log_path = log_path
        self.on_exit = on_exit
        if not os.path.isdir(self.cwd):
            raise ControlError(f"The folder {self.cwd} does not exist. Edit the app and choose an existing folder.")
        shell = os.environ.get("SHELL") or "/bin/zsh"
        self.log = open(log_path, "a", buffering=1, errors="replace")
        self.log.write(f"\n── {time.strftime('%Y-%m-%d %H:%M:%S')}  $ {self.command}\n")
        try:
            self.proc = subprocess.Popen([shell, "-c", self.command], cwd=self.cwd, env=launch_env(app, port),
                                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         start_new_session=True)
        except OSError as err:
            self.log.close()
            raise ControlError(f"Could not start '{self.command}': {err}.") from err
        self.pid = self.proc.pid
        self._add(f"$ {self.command}", "harbor")
        threading.Thread(target=self._read, daemon=True, name=f"harbor-log-{self.app_id}").start()

    def _add(self, text, stream="out"):
        with self.cond:
            self.seq += 1
            self.lines.append({"seq": self.seq, "t": time.time(), "text": text, "stream": stream})
            self.cond.notify_all()

    def _read(self):
        for raw in iter(self.proc.stdout.readline, b""):
            text = ANSI_OSC.sub("", raw.decode("utf-8", "replace").rstrip("\r\n"))
            for part in text.split("\r")[-1:]:
                self._add(part)
                try:
                    self.log.write(re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", part) + "\n")
                except ValueError:
                    pass
        code = self.proc.wait()
        self.exit_code = code
        self.ended_at = time.time()
        self.status = "stopped" if self.stopping else ("exited" if code == 0 else "crashed")
        self._add(f"process ended with exit code {code}" + (" (stopped from Harbor)" if self.stopping else ""), "harbor")
        try:
            self.log.close()
        except OSError:
            pass
        self.on_exit(self)

    @property
    def alive(self):
        return self.proc.poll() is None

    def stop(self, grace=4.0, extra_pids=()):
        self.stopping = True
        pids = []
        try:
            pgid = os.getpgid(self.pid)
        except ProcessLookupError:
            pgid = None
        if pgid and pgid != os.getpgid(0):
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        pids = [self.pid] + [p for p in extra_pids if p != self.pid]
        result = signal_and_wait(pids, grace=grace)
        if pgid and self.alive:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        return result

    def summary(self):
        return {"pid": self.pid, "status": self.status, "exitCode": self.exit_code, "startedAt": self.started_at,
                "endedAt": self.ended_at, "port": self.port, "command": self.command, "lines": self.seq}

    def tail(self, after=0, limit=1000):
        with self.cond:
            return [ln for ln in self.lines if ln["seq"] > after][-limit:]
