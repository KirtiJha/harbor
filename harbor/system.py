"""Reading the machine: listening sockets (lsof), the process table (ps), working directories.

Every parser here is a pure function over command output, so it can be tested without a machine.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

LSOF = shutil.which("lsof") or "/usr/sbin/lsof"
PS = shutil.which("ps") or "/bin/ps"


class SystemError_(RuntimeError):
    pass


def run(args, timeout=5.0):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout, errors="replace")
    except FileNotFoundError as err:
        raise SystemError_(f"{args[0]} is not installed: {err}. Harbor needs lsof and ps.") from err
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
    return parse_ps(run([PS, "-axww", "-o", PS_FIELDS]))


def parse_cwds(text):
    out = {}
    for p in parse_lsof_fields(text):
        for f in p["files"]:
            if f.get("fd") == "cwd" and f.get("name"):
                out[p["pid"]] = f["name"]
    return out


def cwds(pids):
    pids = sorted(set(pids))
    if not pids:
        return {}
    out = {}
    for i in range(0, len(pids), 200):
        chunk = ",".join(str(p) for p in pids[i:i + 200])
        out.update(parse_cwds(run([LSOF, "-a", "-nP", "-p", chunk, "-d", "cwd", "-Fpn"])))
    return out


def is_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
