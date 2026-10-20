"""Reading the machine and acting on processes, on macOS, Linux and Windows.

  macOS / Linux   lsof (listening and established sockets, working folders), ps (process table), signals
  Windows         netstat -ano (sockets), PowerShell Get-CimInstance Win32_Process (process table), taskkill

Every parser is a pure function over command output, so it can be tested on any machine.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time

IS_WINDOWS = os.name == "nt"
LSOF = shutil.which("lsof") or "/usr/sbin/lsof"
PS = shutil.which("ps") or "/bin/ps"
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0          # CREATE_NO_WINDOW: no console flashes for helper commands
NEW_GROUP = 0x00000200 if IS_WINDOWS else 0          # CREATE_NEW_PROCESS_GROUP


class SystemError_(RuntimeError):
    pass


def run(args, timeout=5.0):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout, errors="replace",
                             **({"creationflags": NO_WINDOW} if IS_WINDOWS else {}))
    except FileNotFoundError as err:
        need = "netstat and PowerShell" if IS_WINDOWS else "lsof and ps"
        raise SystemError_(f"{args[0]} is not installed: {err}. Harbor needs {need}.") from err
    except subprocess.TimeoutExpired as err:
        raise SystemError_(f"{' '.join(args[:3])} took longer than {timeout}s.") from err
    # lsof exits 1 when nothing matched; that is an empty answer, not a failure.
    return out.stdout


# ---------------------------------------------------------------- listening sockets

def split_address(name):
    """'127.0.0.1:5173' / '[::1]:5173' / '*:5000' -> ('127.0.0.1', 5173)."""
    host, _, port = name.rpartition(":")
    host = host.strip("[]")
    try:
        return host, int(port)
    except ValueError:
        return None


def parse_lsof_fields(text):
    """lsof -F output -> [{pid, command, uid, user, fields: [{n, ...}]}]."""
    procs, cur, fd = [], None, None
    for line in text.splitlines():
        if not line:
            continue
        tag, val = line[0], line[1:]
        if tag == "p":
            cur = {"pid": int(val), "command": "", "uid": None, "user": "", "files": []}
            procs.append(cur)
            fd = None
        elif cur is None:
            continue
        elif tag == "c":
            cur["command"] = val.replace("\\x20", " ")
        elif tag == "u":
            cur["uid"] = int(val) if val.isdigit() else None
        elif tag == "L":
            cur["user"] = val
        elif tag == "f":
            fd = {"fd": val}
            cur["files"].append(fd)
        elif tag == "n" and fd is not None:
            fd["name"] = val
        elif tag == "P" and fd is not None:
            fd["proto"] = val
        elif tag == "T" and fd is not None and val.startswith("ST="):
            fd["state"] = val[3:]
    return procs


def parse_listeners(text):
    """Listening sockets grouped per (pid, port): {(pid, port): {pid, port, command, uid, user, addresses}}."""
    out = {}
    for p in parse_lsof_fields(text):
        for f in p["files"]:
            addr = split_address(f.get("name", ""))
            if not addr:
                continue
            host, port = addr
            key = (p["pid"], port)
            row = out.setdefault(key, {"pid": p["pid"], "port": port, "command": p["command"],
                                       "uid": p["uid"], "user": p["user"], "addresses": []})
            if host not in row["addresses"]:
                row["addresses"].append(host)
    return out


def listeners():
    if IS_WINDOWS:
        return parse_netstat(_netstat())["listen"]
    return parse_listeners(run([LSOF, "-nP", "-iTCP", "-sTCP:LISTEN", "-FpcuLn"]))


def parse_established(text, listening_ports):
    """Count established connections per local listening port (the server side of each connection)."""
    counts = {}
    for p in parse_lsof_fields(text):
        for f in p["files"]:
            local, _, remote = f.get("name", "").partition("->")
            addr = split_address(local)
            if addr and remote and addr[1] in listening_ports:
                counts[addr[1]] = counts.get(addr[1], 0) + 1
    return counts


def established(listening_ports):
    if not listening_ports:
        return {}
    if IS_WINDOWS:
        counts = parse_netstat(_netstat())["established"]
        return {p: n for p, n in counts.items() if p in set(listening_ports)}
    return parse_established(run([LSOF, "-nP", "-iTCP", "-sTCP:ESTABLISHED", "-Fpn"]), set(listening_ports))


# ---------------------------------------------------------------- processes

PS_FIELDS = "pid=,ppid=,pgid=,uid=,%cpu=,rss=,etime=,command="
PS_LINE = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.,]+)\s+(\d+)\s+(\S+)\s(.*)$")


def parse_etime(s):
    """'[[dd-]hh:]mm:ss' -> seconds."""
    days = 0
    if "-" in s:
        d, s = s.split("-", 1)
        days = int(d)
    parts = [int(x) for x in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts
    return days * 86400 + h * 3600 + m * 60 + sec


def parse_ps(text):
    procs = {}
    for line in text.splitlines():
        m = PS_LINE.match(line)
        if not m:
            continue
        pid, ppid, pgid, uid, cpu, rss, et, args = m.groups()
        try:
            elapsed = parse_etime(et)
        except ValueError:
            elapsed = None
        procs[int(pid)] = {"pid": int(pid), "ppid": int(ppid), "pgid": int(pgid), "uid": int(uid),
                           "cpu": float(cpu.replace(",", ".")), "rss_kb": int(rss), "elapsed": elapsed,
                           "args": args.strip()}
    return procs


def processes():
    if IS_WINDOWS:
        return parse_cim(run(CIM_COMMAND, timeout=15), _CPU_STATE)
    return parse_ps(run([PS, "-A", "-ww", "-o", PS_FIELDS]))


def parse_cwds(text):
    out = {}
    for p in parse_lsof_fields(text):
        for f in p["files"]:
            if f.get("fd") == "cwd" and f.get("name"):
                out[p["pid"]] = f["name"]
    return out


def cwds(pids):
    pids = sorted(set(pids))
    if not pids or IS_WINDOWS:   # Windows does not expose another process's working folder without native code
        return {}
    out = {}
    for i in range(0, len(pids), 200):
        chunk = ",".join(str(p) for p in pids[i:i + 200])
        out.update(parse_cwds(run([LSOF, "-a", "-nP", "-p", chunk, "-d", "cwd", "-Fpn"])))
    return out


def is_alive(pid):
    if IS_WINDOWS:
        return _win_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---------------------------------------------------------------- Windows: sockets and processes

_NETSTAT = {"at": 0.0, "text": ""}


def _netstat():
    # listeners() and established() run in the same scan; one netstat call serves both.
    if time.monotonic() - _NETSTAT["at"] > 0.8:
        _NETSTAT["text"] = run(["netstat", "-ano"])
        _NETSTAT["at"] = time.monotonic()
    return _NETSTAT["text"]


def parse_netstat(text):
    """`netstat -ano` -> {"listen": {(pid, port): row}, "established": {port: count}}.
    A listening row has foreign port 0, which also works when Windows prints the state in another language."""
    listen, est = {}, {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4 or not parts[0].upper().startswith("TCP"):
            continue
        local, foreign, pid = split_address(parts[1]), split_address(parts[2]), parts[-1]
        if not local or not pid.isdigit():
            continue
        host, port = local
        state = parts[3].upper() if len(parts) >= 5 else ""
        if foreign and foreign[1] == 0:
            row = listen.setdefault((int(pid), port), {"pid": int(pid), "port": port, "command": "", "uid": None,
                                                       "user": os.environ.get("USERNAME", ""), "addresses": []})
            shown = "*" if host in ("0.0.0.0", "::") else host
            if shown not in row["addresses"]:
                row["addresses"].append(shown)
        elif state == "ESTABLISHED":
            est[port] = est.get(port, 0) + 1
    return {"listen": listen, "established": est}


CIM_COMMAND = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,SessionId,Name,CommandLine,"
               "WorkingSetSize,KernelModeTime,UserModeTime,"
               "@{n='Created';e={if($_.CreationDate){[int64](($_.CreationDate.ToUniversalTime())-[datetime]'1970-01-01').TotalSeconds}else{0}}}"
               " | ConvertTo-Json -Compress"]
_CPU_STATE = {}


def parse_cim(text, cpu_state=None, now=None):
    """PowerShell's Win32_Process JSON -> the same process dicts `parse_ps` returns. CPU % is the change in
    kernel + user time since the previous scan (100 % = one core), like ps on macOS."""
    now = now or time.time()
    try:
        rows = json.loads(text or "[]")
    except ValueError:
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    procs, seen = {}, {}
    for r in rows:
        pid = r.get("ProcessId")
        if pid is None:
            continue
        busy = (r.get("KernelModeTime") or 0) + (r.get("UserModeTime") or 0)   # 100 ns units
        cpu = 0.0
        if cpu_state is not None:
            prev = cpu_state.get(pid)
            if prev and now > prev[1] and busy >= prev[0]:
                cpu = round((busy - prev[0]) / ((now - prev[1]) * 1e7) * 100, 1)
            seen[pid] = (busy, now)
        created = r.get("Created") or 0
        procs[pid] = {"pid": pid, "ppid": r.get("ParentProcessId") or 0, "pgid": pid, "uid": r.get("SessionId"),
                      "cpu": cpu, "rss_kb": int((r.get("WorkingSetSize") or 0) // 1024),
                      "elapsed": int(now - created) if created else None,
                      "args": (r.get("CommandLine") or r.get("Name") or "").strip(), "name": r.get("Name") or ""}
    if cpu_state is not None:
        cpu_state.clear()
        cpu_state.update(seen)
    return procs


def _win_alive(pid):
    """os.kill(pid, 0) would end the process on Windows; ask the kernel instead."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5                  # access denied: it exists
    try:
        code = wintypes.DWORD()
        return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


# ---------------------------------------------------------------- identity, launching and stopping

def my_uid():
    """The owner Harbor compares processes with: the user id on Unix, the login session on Windows."""
    if IS_WINDOWS:
        import ctypes
        sid = ctypes.c_ulong()
        ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
        return sid.value
    return os.getuid()


def shell_argv(command):
    if IS_WINDOWS:
        # A string, not a list: list quoting would escape the command's own quotes in a way cmd.exe misreads.
        return f'"{os.environ.get("COMSPEC", "cmd.exe")}" /d /s /c "{command}"'

    return [os.environ.get("SHELL") or "/bin/sh", "-c", command]


def spawn_options():
    """Start an app detached from Harbor, so it keeps running when Harbor stops."""
    if IS_WINDOWS:
        return {"creationflags": NEW_GROUP | NO_WINDOW}
    return {"start_new_session": True}


def terminate(pid, force=False, tree=False):
    """Ask a process to stop (SIGTERM / taskkill), or force it (SIGKILL / taskkill /F). Raises
    ProcessLookupError when it is gone and PermissionError when it belongs to someone else."""
    if IS_WINDOWS:
        args = ["taskkill", "/PID", str(pid)] + (["/T"] if tree else []) + (["/F"] if force else [])
        out = subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW)
        if out.returncode == 0:
            return
        msg = (out.stderr or out.stdout).lower()
        if "not found" in msg or "128" in msg or not is_alive(pid):
            raise ProcessLookupError(pid)
        if "denied" in msg:
            raise PermissionError(pid)
        if not force:
            raise ChildProcessError(msg.strip())   # cannot be asked politely (a console app): force it later
        return
    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


def terminate_group(pid, force=False):
    """The whole process group (Unix) or process tree (Windows) of a launched app."""
    if IS_WINDOWS:
        try:
            terminate(pid, force=force, tree=True)
        except (ProcessLookupError, PermissionError, ChildProcessError):
            pass
        return
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    if pgid != os.getpgid(0):
        try:
            os.killpg(pgid, signal.SIGKILL if force else signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def group_leader(pid):
    """True when pid still leads its own group, i.e. it is the app Harbor launched and not a reused pid."""
    if IS_WINDOWS:
        return is_alive(pid)
    try:
        return os.getpgid(pid) == pid
    except ProcessLookupError:
        return False
