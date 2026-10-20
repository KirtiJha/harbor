"""porthaven: see and manage every app listening on a port.

  porthaven                     open the Porthaven dashboard (starts the server)
  porthaven ls [--all] [--json] list listening ports
  porthaven who <port>          what is on a port
  porthaven kill <port> [--app] [-y]   stop what is on a port (--app: the whole app, e.g. `make dev`)
  porthaven free [from] [-n N]  the next free ports
  porthaven open <port>         open a port in the browser
  porthaven up [dir]            start the apps in porthaven.toml, dependencies first;  `down` stops them
  porthaven init [dir]          write a porthaven.toml from your saved apps or the projects found there
  porthaven start|stop <app>    start (with its dependencies) or stop a saved app
  porthaven mcp                 Model Context Protocol server for coding agents (Claude Code, Cursor, …)
  porthaven service install     start Porthaven at login (macOS, Linux, Windows); `uninstall` / `status`
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
import webbrowser

from . import __version__, classify, probe
from .control import ControlError
from .core import Porthaven
from .store import Store

DEFAULT_PORT = int(os.environ.get("PORTHAVEN_PORT", "7475"))
C = {"dim": "\x1b[2m", "b": "\x1b[1m", "g": "\x1b[32m", "y": "\x1b[33m", "r": "\x1b[31m", "c": "\x1b[36m", "x": "\x1b[0m"}
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    C = {k: "" for k in C}


def uptime(sec):
    if sec is None:
        return "—"
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if sec >= n:
            return f"{sec // n}{unit}"
    return f"{sec}s"


def snapshot(show_all=False):
    h = Porthaven(Store())
    h.refresh(initial=True)
    deadline = time.time() + 2.0
    while h.probing and time.time() < deadline:
        time.sleep(0.05)
    snap = h.build()
    rows = snap["listeners"]
    if not show_all:
        rows = [r for r in rows if r["kind"] not in ("system", "app")]
    return h, snap, rows


def cmd_ls(args):
    _, snap, rows = snapshot(args.all)
    if args.json:
        print(json.dumps(rows, indent=1))
        return 0
    if not rows:
        print("Nothing is listening" + ("" if args.all else " (apart from system services; --all shows them)") + ".")
        return 0
    print(f"{C['dim']}{'PORT':>6}  {'PID':>6}  {'WHAT':<28} {'PROJECT':<22} {'UP':>5}  {'HTTP':<5} COMMAND{C['x']}")
    seen = set()
    for r in rows:
        if (r["port"], r["pid"]) in seen:
            continue
        seen.add((r["port"], r["pid"]))
        pr = r["probe"] or {}
        status = str(pr.get("status") or ("—" if not pr else "x"))
        color = C["g"] if str(status).startswith("2") else C["y"] if str(status)[:1] in "34" else C["dim"]
        net = f" {C['y']}⚠ network{C['x']}" if r["exposure"] == "network" else ""
        print(f"{C['b']}{r['port']:>6}{C['x']}  {r['pid']:>6}  {r['title'][:28]:<28} {((r['project'] or {}).get('name') or '')[:22]:<22} "
              f"{uptime(r['uptime']):>5}  {color}{status:<5}{C['x']} {C['dim']}{classify.display_command(r['args'], 60)}{C['x']}{net}")
    hidden = len([r for r in snap["listeners"] if r["kind"] in ("system", "app")]) if not args.all else 0
    if hidden:
        print(f"{C['dim']}+ {hidden} system/desktop-app port(s) hidden; --all shows them{C['x']}")
    return 0


def cmd_who(args):
    _, snap, _ = snapshot(True)
    rows = [r for r in snap["listeners"] if r["port"] == args.port]
    if not rows:
        print(f"Port {args.port} is free." + (f" ({classify.PORT_HINTS[args.port]} usually uses it.)" if args.port in classify.PORT_HINTS else ""))
        return 1
    for r in rows:
        pr = r["probe"] or {}
        print(f"{C['b']}{r['port']}{C['x']}  {r['title']}  {C['dim']}({r['kind']}{', ' + r['framework']['label'] if r['framework'] else ''}){C['x']}")
        print(f"  pid      {r['pid']}   up {uptime(r['uptime'])}   cpu {r['cpu']}%   mem {r['memMb']} MB")
        print(f"  command  {r['args']}")
        if r["cwd"]:
            print(f"  folder   {r['cwd']}")
        if r["root"]:
            print(f"  app      pid {r['root']['pid']}: {r['root']['display']} ({r['root']['count']} processes)")
        print(f"  address  {', '.join(r['addresses'])}" + ("  ⚠ reachable from the network" if r["exposure"] == "network" else ""))
        if pr:
            print(f"  http     {pr.get('status') or pr.get('error')} {pr.get('title') or ''} ({pr.get('ms')} ms)")
    return 0


def cmd_kill(args):
    h, snap, _ = snapshot(True)
    h.snapshot = snap
    rows = [r for r in snap["listeners"] if r["port"] == args.port]
    if not rows:
        print(f"Nothing is listening on {args.port}.")
        return 1
    for r in {r["pid"]: r for r in rows}.values():
        target = r["root"] if args.app and r["root"] else None
        what = f"{target['display']} (pid {target['pid']}, {target['count']} processes)" if target else f"{r['display']} (pid {r['pid']})"
        if not args.yes:
            ans = input(f"Stop {what} on port {args.port}? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                print("Left running.")
                continue
        try:
            res = h.kill(r["pid"], mode="app" if args.app else "process", confirm=args.yes)
        except ControlError as err:
            if getattr(err, "extra", {}).get("needsConfirm") and not args.yes:
                print(f"{err} Re-run with -y to confirm.")
                return 2
            print(f"{C['r']}{err}{C['x']}")
            return 2
        forced = f", {len(res['killed'])} forced" if res["killed"] else ""
        left = f"; {C['r']}still running: {res['survivors']}{C['x']}" if res["survivors"] else ""
        print(f"{C['g']}Stopped{C['x']} {len(res['exited']) + len(res['killed'])} process(es){forced}{left}.")
    return 0


def cmd_free(args):
    ports = probe.free_ports(args.start, args.n)
    print(" ".join(map(str, ports)))
    return 0


def cmd_open(args):
    webbrowser.open(f"http://localhost:{args.port}/")
    return 0


def cmd_up(args):
    from .client import Client, ClientError, ensure_server
    try:
        ensure_server(log=print)
        c = Client("cli")
        res = c.call("POST", "/api/teamfile/up", {"path": os.path.abspath(args.dir)})
    except ClientError as err:
        print(f"{C['r']}{err}{C['x']}")
        return 2
    print(f"{C['b']}{res['file']}{C['x']}  {C['dim']}{len(res['added'])} added, {len(res['updated'])} updated{C['x']}")
    for port, names in (res.get("claims") or {}).items():
        print(f"{C['y']}⚠ port {port} is also expected by {', '.join(names)}{C['x']}")
    print(f"{C['dim']}starting in order: {' → '.join(res['order'])}{C['x']}")
    ids, deadline, last = set(res["ids"]), time.time() + 180, {}
    while time.time() < deadline:
        st = {a["id"]: a for a in c.state()["apps"] if a["id"] in ids}
        for a in st.values():
            line = (a["state"], tuple(a["ports"]))
            if last.get(a["id"]) != line:
                last[a["id"]] = line
                where = f"  {a['stableUrl']}" if a.get("stableUrl") and a["ports"] else ""
                color = C["g"] if a["state"] in ("running", "external") else C["r"] if a["state"] == "crashed" else C["dim"]
                print(f"  {color}{a['state']:<9}{C['x']} {a['name']:<24} {':' + str(a['ports'][0]) if a['ports'] else '':<7}{where}")
        if all(a["state"] in ("running", "external") and a["ports"] for a in st.values()):
            print(f"{C['g']}All {len(st)} up.{C['x']}  Dashboard: http://localhost:7475/")
            return 0
        if any(a["state"] == "crashed" for a in st.values()):
            print(f"{C['r']}Something crashed. See its output in the dashboard (Apps) or ~/.porthaven/logs.{C['x']}")
            return 1
        time.sleep(1)
    print("Still starting after 3 minutes; check the dashboard.")
    return 1


def cmd_down(args):
    from .client import Client, ClientError
    try:
        res = Client("cli").call("POST", "/api/teamfile/down", {"path": os.path.abspath(args.dir)})
    except ClientError as err:
        print(f"{C['r']}{err}{C['x']}")
        return 2
    print(f"Stopped {len(res['stopped'])}: {', '.join(res['stopped']) or 'nothing was running'}.")
    return 0


def cmd_init(args):
    from pathlib import Path
    from . import teamfile
    from .discover import discover
    folder = Path(os.path.abspath(args.dir))
    target = folder / teamfile.NAME
    if target.exists() and not args.force:
        print(f"{target} already exists (use --force to overwrite).")
        return 1
    saved = [a for a in Store().apps() if os.path.realpath(os.path.expanduser(a["cwd"])).startswith(str(folder.resolve()))]
    if not saved:
        found = discover(str(folder), 3)["items"]
        seen, saved = set(), []
        for it in found:
            if it["cwd"] in seen:
                continue
            seen.add(it["cwd"])
            saved.append({"name": it["name"], "cwd": it["cwd"], "command": it["command"], "port": it["port"],
                          "slug": re.sub(r"[^a-z0-9-]", "-", (it["rel"] if it["rel"] != "." else it["name"]).lower()).strip("-")})
    if not saved:
        print("No saved apps or runnable projects found here. Add [apps.<name>] tables by hand; see `porthaven init --help`.")
        return 1
    target.write_text(teamfile.dump(saved, folder))
    print(f"Wrote {target} with {len(saved)} app(s): {', '.join(a['name'] for a in saved)}.\nCheck it, commit it, then `porthaven up`.")
    return 0


def _app_call(args, action):
    from .client import Client, ClientError, ensure_server
    try:
        ensure_server(log=print)
        c = Client("cli")
        apps = c.state()["apps"]
        ref = args.app.lower()
        app = next((a for a in apps if ref in (a["id"].lower(), (a.get("slugName") or "").lower(), a["name"].lower())), None)
        if not app:
            print(f"No saved app “{args.app}”. Saved apps: {', '.join(a.get('slugName') or a['name'] for a in apps) or 'none'}.")
            return 1
        res = c.call("POST", f"/api/apps/{app['id']}/{action}", {"port": args.port} if getattr(args, "port", None) else {})
    except ClientError as err:
        print(f"{C['r']}{err}{C['x']}")
        return 2
    if action == "start" and "stack" in res:
        print(f"Starting {' → '.join(res['stack'])} (dependencies first).")
    elif action == "start":
        print(f"{C['g']}Started{C['x']} {app['name']} on :{res.get('port')}  {app.get('stableUrl') or ''}")
    else:
        print(f"Stopped {app['name']}.")
    return 0


def cmd_start(args):
    return _app_call(args, "start")


def cmd_stop(args):
    return _app_call(args, "stop")


def cmd_mcp(args):
    from .mcp import serve_stdio
    return serve_stdio()


LABEL = "dev.porthaven.dashboard"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def cmd_service(args):
    """Start Porthaven at login: launchd on macOS, a systemd user service on Linux, a logon task on Windows."""
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    logs = Path.home() / ".porthaven" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        return _service_launchd(args, root, logs, subprocess)
    if os.name == "nt":
        return _service_windows(args, root, subprocess)
    return _service_systemd(args, root, subprocess)


def _service_launchd(args, root, logs, subprocess):
    import plistlib
    domain = f"gui/{os.getuid()}"
    if args.action == "status":
        out = subprocess.run(["launchctl", "print", f"{domain}/{LABEL}"], capture_output=True, text=True)
        print(f"installed: {os.path.exists(PLIST)}  ({PLIST})")
        print("running" if out.returncode == 0 and "state = running" in out.stdout else "not running under launchd")
        return 0
    if args.action == "uninstall":
        subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)
        if os.path.exists(PLIST):
            os.remove(PLIST)
        print("Porthaven will no longer start at login.")
        return 0
    plist = {"Label": LABEL, "ProgramArguments": [str(root / "bin" / "porthaven"), "serve", "--no-open", "--port", str(args.port)],
             "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False},
             "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin")},
             "StandardOutPath": str(logs / "porthaven.out.log"), "StandardErrorPath": str(logs / "porthaven.err.log")}
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    with open(PLIST, "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)
    out = subprocess.run(["launchctl", "bootstrap", domain, PLIST], capture_output=True, text=True)
    if out.returncode:
        print(f"Wrote {PLIST} but launchctl refused it: {out.stderr.strip()}")
        return 2
    print(f"Porthaven now starts at login on http://localhost:{args.port}/  (undo: porthaven service uninstall)")
    return 0


def _service_systemd(args, root, subprocess):
    unit = os.path.expanduser("~/.config/systemd/user/porthaven.service")
    ctl = ["systemctl", "--user"]
    if args.action == "status":
        out = subprocess.run(ctl + ["is-active", "porthaven"], capture_output=True, text=True)
        print(f"installed: {os.path.exists(unit)}  ({unit})\n{out.stdout.strip() or 'inactive'}")
        return 0
    if args.action == "uninstall":
        subprocess.run(ctl + ["disable", "--now", "porthaven"], capture_output=True)
        if os.path.exists(unit):
            os.remove(unit)
        subprocess.run(ctl + ["daemon-reload"], capture_output=True)
        print("Porthaven will no longer start at login.")
        return 0
    os.makedirs(os.path.dirname(unit), exist_ok=True)
    with open(unit, "w") as f:
        f.write(f"""[Unit]
Description=Porthaven, a dashboard for every local port

[Service]
ExecStart={root / "bin" / "porthaven"} serve --no-open --port {args.port}
Restart=on-failure
Environment=PATH={os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}

[Install]
WantedBy=default.target
""")
    subprocess.run(ctl + ["daemon-reload"], capture_output=True)
    out = subprocess.run(ctl + ["enable", "--now", "porthaven"], capture_output=True, text=True)
    if out.returncode:
        print(f"Wrote {unit} but systemctl refused it: {out.stderr.strip()}")
        return 2
    print(f"Porthaven now starts at login on http://localhost:{args.port}/  (undo: porthaven service uninstall)")
    return 0


def _service_windows(args, root, subprocess):
    task = "Porthaven"
    if args.action == "status":
        out = subprocess.run(["schtasks", "/Query", "/TN", task], capture_output=True, text=True)
        print("installed" if out.returncode == 0 else "not installed")
        return 0
    if args.action == "uninstall":
        subprocess.run(["schtasks", "/Delete", "/TN", task, "/F"], capture_output=True)
        print("Porthaven will no longer start at login.")
        return 0
    launcher = root / "bin" / "porthaven.cmd"
    out = subprocess.run(["schtasks", "/Create", "/TN", task, "/SC", "ONLOGON", "/RL", "LIMITED", "/F",
                          "/TR", f'"{launcher}" serve --no-open --port {args.port}'], capture_output=True, text=True)
    if out.returncode:
        print(f"Task Scheduler refused it: {(out.stderr or out.stdout).strip()}")
        return 2
    print(f"Porthaven now starts when you sign in, on http://localhost:{args.port}/  (undo: porthaven service uninstall)")
    return 0


def cmd_serve(args):
    from .server import serve
    port = args.port
    if not probe.port_free(port):
        if probe.probe(port).get("server", "") and "Porthaven" in (probe.probe(port).get("server") or ""):
            print(f"Porthaven is already running on http://localhost:{port}/")
            if not args.no_open:
                webbrowser.open(f"http://localhost:{port}/")
            return 0
        port = probe.free_ports(port + 1, 1)[0]
    url = f"http://localhost:{port}/"
    h = Porthaven(Store(), port)

    def stop(*_):
        running = [m.name for m in h.managed.values() if m.alive]
        print("\nStopping Porthaven." + (f" Still running: {', '.join(running)} (Porthaven picks them up again next time)." if running else ""))
        h.stop()
        os._exit(0)

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    print(f"{C['b']}Porthaven {__version__}{C['x']}  {C['c']}{url}{C['x']}   {C['dim']}(Ctrl-C to stop){C['x']}", flush=True)
    serve(h, port, ready=(lambda: webbrowser.open(url)) if not args.no_open else None)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="porthaven", description="See and manage every app listening on a port.")
    p.add_argument("--version", action="version", version=f"porthaven {__version__}")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the dashboard (default)")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--no-open", action="store_true", help="do not open the browser")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("ls", help="list listening ports")
    s.add_argument("--all", "-a", action="store_true", help="include system services and desktop apps")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_ls)
    s = sub.add_parser("who", help="what is on a port")
    s.add_argument("port", type=int)
    s.set_defaults(fn=cmd_who)
    s = sub.add_parser("kill", help="stop what is on a port")
    s.add_argument("port", type=int)
    s.add_argument("--app", action="store_true", help="stop the whole app (its launcher and every child)")
    s.add_argument("-y", "--yes", action="store_true", help="do not ask")
    s.set_defaults(fn=cmd_kill)
    s = sub.add_parser("free", help="the next free ports")
    s.add_argument("start", type=int, nargs="?", default=3000)
    s.add_argument("-n", type=int, default=5)
    s.set_defaults(fn=cmd_free)
    s = sub.add_parser("service", help="start Porthaven at login (launchd, systemd or Task Scheduler)")
    s.add_argument("action", choices=["install", "uninstall", "status"])
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.set_defaults(fn=cmd_service)
    s = sub.add_parser("up", help="start the apps in porthaven.toml, dependencies first")
    s.add_argument("dir", nargs="?", default=".")
    s.set_defaults(fn=cmd_up)
    s = sub.add_parser("down", help="stop the apps in porthaven.toml")
    s.add_argument("dir", nargs="?", default=".")
    s.set_defaults(fn=cmd_down)
    s = sub.add_parser("init", help="write a porthaven.toml for this folder")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("start", help="start a saved app (and its dependencies)")
    s.add_argument("app")
    s.add_argument("--port", type=int)
    s.set_defaults(fn=cmd_start)
    s = sub.add_parser("stop", help="stop a saved app")
    s.add_argument("app")
    s.set_defaults(fn=cmd_stop)
    s = sub.add_parser("mcp", help="Model Context Protocol server (stdio) for coding agents")
    s.set_defaults(fn=cmd_mcp)
    s = sub.add_parser("open", help="open a port in the browser")
    s.add_argument("port", type=int)
    s.set_defaults(fn=cmd_open)
    args = p.parse_args(argv)
    if not args.cmd:
        args = p.parse_args(["serve"] + (argv or sys.argv[1:]))
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
