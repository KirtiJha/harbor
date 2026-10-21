#!/usr/bin/env python3
# <xbar.title>Porthaven</xbar.title>
# <xbar.desc>Every port on your machine in the menu bar: open, stop, see what needs attention.</xbar.desc>
# <xbar.dependencies>python3, a running Porthaven</xbar.dependencies>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
"""Menu-bar companion for SwiftBar / xbar (macOS) and Argos (GNOME). Symlink it into the plugin folder:

    ln -s ~/porthaven/extras/menubar/porthaven.10s.py "$HOME/Library/Application Support/SwiftBar/Plugins/"
"""
import json
import os
import urllib.request

URL = os.environ.get("PORTHAVEN_URL", "http://127.0.0.1:7475")
CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "bin", "porthaven")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

try:
    with opener.open(URL + "/api/state", timeout=3) as r:
        snap = json.load(r)
except OSError:
    print("⚓ –")
    print("---")
    print("Porthaven is not running | color=gray")
    print(f"Start Porthaven | bash={CLI} param1=serve terminal=false refresh=true")
    raise SystemExit

rows = [r for r in snap["listeners"] if r["kind"] not in ("system", "app")]
s = snap["summary"]
alert = s.get("critical", 0) + len(s.get("watchedDown", [])) + s.get("leaks", 0) + s.get("agentLeftovers", 0) + s.get("drift", 0)
print(f"{'⚠️' if alert else '⚓'} {len({r['port'] for r in rows})}")
print("---")
if alert:
    for r in rows:
        risk = r.get("exposureRisk") or {}
        if risk.get("level") == "critical":
            print(f":{r['port']} {risk['title']} | color=#f87171")
    for p in s.get("watchedDown", []):
        print(f":{p} is down (watched) | color=#fbbf24")
    for r in rows:
        if r.get("leak"):
            print(f":{r['port']} {r['title'][:24]} memory +{r['leak']['growthMb']} MB, still growing | color=#fb7185")
    if s.get("agentLeftovers"):
        print(f"{s['agentLeftovers']} server(s) left by coding agents | color=#fbbf24")
        print(f"-- Stop them | bash={CLI} param1=agents param2=--stop terminal=false refresh=true")
    for f in (snap.get("drift") or {}).get("findings", []):
        if f["level"] == "warn":
            print(f"{f['title'][:70]} | color=#fbbf24")
    print("---")
for r in sorted(rows, key=lambda r: r["port"]):
    status = (r.get("probe") or {}).get("status")
    dot = "🟢" if status and status < 400 else "🟡" if status else "⚪️"
    branch = ((r.get("project") or {}).get("git") or {}).get("branch")
    print(f"{dot} :{r['port']}  {r['title'][:32]}" + (f"  ⎇ {branch}" if branch else "") + f" | href=http://localhost:{r['port']}/")
    print(f"-- Open | href=http://localhost:{r['port']}/")
    if r.get("stableUrl"):
        print(f"-- Open {r['stableUrl']} | href={r['stableUrl']}")
    if r.get("risk") not in ("self", "foreign", "system", "app"):
        print(f"-- Stop | bash={CLI} param1=kill param2={r['port']} param3=-y terminal=false refresh=true")
        if r.get("root"):
            print(f"-- Stop whole app | bash={CLI} param1=kill param2={r['port']} param3=--app param4=-y terminal=false refresh=true")
apps = [a for a in snap["apps"] if a["state"] not in ("running", "starting", "external")]
if apps:
    print("---")
    print("Start")
    for a in apps:
        print(f"-- {a['name']} | bash={CLI} param1=start param2={a['id']} terminal=false refresh=true")
print("---")
print(f"Open Porthaven | href={URL}/")
print("Refresh | refresh=true")
