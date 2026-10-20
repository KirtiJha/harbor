"""harbor: see and manage every app listening on a port.

  harbor                     open the Harbor dashboard (starts the server)
  harbor ls [--all] [--json] list listening ports
  harbor who <port>          what is on a port
  harbor kill <port> [--app] [-y]   stop what is on a port (--app: the whole app, e.g. `make dev`)
  harbor free [from] [-n N]  the next free ports
  harbor open <port>         open a port in the browser
  harbor service install     start Harbor at login (macOS launchd); `uninstall` / `status`
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import webbrowser

from . import __version__, classify, probe
from .control import ControlError
from .core import Harbor
from .store import Store

DEFAULT_PORT = int(os.environ.get("HARBOR_PORT", "7475"))
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
    h = Harbor(Store())
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


LABEL = "dev.harbor.dashboard"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def cmd_service(args):
    import plistlib
    import subprocess
    from pathlib import Path
    if sys.platform != "darwin":
        print("Start at login is set up with launchd on macOS. On Linux, add `harbor serve --no-open` to a systemd user unit.")
        return 1
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
        print("Harbor will no longer start at login.")
        return 0
    launcher = str(Path(__file__).resolve().parent.parent / "bin" / "harbor")
    logs = Path.home() / ".harbor" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    plist = {"Label": LABEL, "ProgramArguments": [launcher, "serve", "--no-open", "--port", str(args.port)],
             "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False},
             "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin")},
             "StandardOutPath": str(logs / "harbor.out.log"), "StandardErrorPath": str(logs / "harbor.err.log")}
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    with open(PLIST, "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)
    out = subprocess.run(["launchctl", "bootstrap", domain, PLIST], capture_output=True, text=True)
    if out.returncode:
        print(f"Wrote {PLIST} but launchctl refused it: {out.stderr.strip()}")
        return 2
    print(f"Harbor now starts at login on http://localhost:{args.port}/  (undo: harbor service uninstall)")
    return 0


def cmd_serve(args):
    from .server import serve
    port = args.port
    if not probe.port_free(port):
        if probe.probe(port).get("server", "") and "Harbor" in (probe.probe(port).get("server") or ""):
            print(f"Harbor is already running on http://localhost:{port}/")
            if not args.no_open:
                webbrowser.open(f"http://localhost:{port}/")
            return 0
        port = probe.free_ports(port + 1, 1)[0]
    url = f"http://localhost:{port}/"
    h = Harbor(Store(), port)

    def stop(*_):
        print("\nStopping Harbor" + (" and the apps it started" if any(m.alive for m in h.managed.values()) else "") + "…")
        h.shutdown_apps()
        h.stop()
        os._exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"{C['b']}Harbor {__version__}{C['x']}  {C['c']}{url}{C['x']}   {C['dim']}(Ctrl-C to stop){C['x']}", flush=True)
    serve(h, port, ready=(lambda: webbrowser.open(url)) if not args.no_open else None)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="harbor", description="See and manage every app listening on a port.")
    p.add_argument("--version", action="version", version=f"harbor {__version__}")
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
    s = sub.add_parser("service", help="start Harbor at login (macOS)")
    s.add_argument("action", choices=["install", "uninstall", "status"])
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.set_defaults(fn=cmd_service)
    s = sub.add_parser("open", help="open a port in the browser")
    s.add_argument("port", type=int)
    s.set_defaults(fn=cmd_open)
    args = p.parse_args(argv)
    if not args.cmd:
        args = p.parse_args(["serve"] + (argv or sys.argv[1:]))
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
