"""Who talks to whom: a live map of the local services, drawn from the TCP connections between processes.

A node is one service (a saved app, or a project's server) or an outside client such as a browser. An edge is a
client connecting to a server's port. Edges are remembered for half an hour, so a link that carried traffic and
went quiet stays on the map as idle, and a link whose server went away shows as broken. A saved app's
dependencies (dependsOn) are drawn too, before any traffic flows.
"""
from __future__ import annotations

import re
import threading
import time

from . import classify

KEEP = 30 * 60          # how long a quiet or broken link stays on the map
LOOPBACK = re.compile(r"^(127\.|::1$|::ffff:127\.|localhost$)")
HELPER = re.compile(r"\s*(Helper|Renderer|GPU|Plugin|Web Content|Networking)\b.*$", re.I)


def node_key(row):
    """A name for a listening row's service that survives restarts (pids change, apps and folders do not)."""
    if row.get("appId"):
        return f"app:{row['appId']}"
    if row.get("project"):
        return f"proj:{row['project']['root']}"
    return f"cmd:{row['title']}"


def client_name(proc):
    """What to call a process that connects but does not listen: the desktop app it belongs to, or its program."""
    args = (proc or {}).get("args", "")
    bundle = classify.app_bundle(args)
    if bundle:
        return HELPER.sub("", bundle).strip() or bundle
    name = (proc or {}).get("name") or classify.base(args) or "process"
    name = re.sub(r"\.exe$", "", name, flags=re.I)
    return HELPER.sub("", name).strip() or name


class ServiceMap:
    def __init__(self):
        self.seen = {}      # (src key, dst port) -> {"first", "last", "src", "dst", "dstKey"}
        self.lock = threading.Lock()

    def build(self, *args, **kw):
        with self.lock:   # the snapshot is built from the scan thread and from probe threads
            return self._build(*args, **kw)

    def _build(self, rows, procs, links, apps, self_pids, lan_ip=None, now=None):
        now = now or time.time()
        nodes, port_node, pid_node, trees = {}, {}, {}, []
        for r in rows:
            if r["kind"] in ("system",):
                continue
            key = node_key(r)
            n = nodes.setdefault(key, {"id": key, "title": r["title"], "ports": [], "kind": r["kind"], "appId": r.get("appId"),
                                       "framework": (r.get("framework") or {}).get("label"), "project": (r.get("project") or {}).get("name"),
                                       "memMb": 0.0, "pids": [], "self": r["pid"] in self_pids, "client": False})
            if r["port"] not in n["ports"]:
                n["ports"].append(r["port"])
            n["memMb"] = round(n["memMb"] + (r.get("memMb") or 0), 1)
            port_node[r["port"]] = key
            pid_node[r["pid"]] = key   # a listening process is always its own service
            if r["pid"] not in self_pids:   # Porthaven's children are the apps it runs, not part of Porthaven
                trees.append((key, (r.get("root") or {}).get("pid") or r["pid"]))
        for key, root in trees:   # then the launchers and helpers around each server
            for pid in [root] + classify.descendants(root, procs):
                pid_node.setdefault(pid, key)
        for pid, key in pid_node.items():
            nodes[key]["pids"].append(pid)
        local_hosts = {"127.0.0.1", "::1", "localhost", "0.0.0.0", "::"} | ({lan_ip} if lan_ip else set())
        live = {}
        for c in links:
            dport = c["remote"][1]
            # the client side of a connection: its far end is one of our listening ports (the server side's far
            # end is the client's ephemeral port, which nothing listens on)
            if dport not in port_node or not (LOOPBACK.match(c["remote"][0]) or c["remote"][0] in local_hosts):
                continue
            src = pid_node.get(c["pid"])
            if src is None:
                proc = procs.get(c["pid"])
                if not proc:
                    continue
                name = client_name(proc)
                src = f"client:{name}"
                nodes.setdefault(src, {"id": src, "title": name, "ports": [], "kind": "client", "appId": None, "framework": None,
                                       "project": None, "memMb": None, "pids": [], "self": c["pid"] in self_pids, "client": True})
            dst = port_node[dport]
            if src == dst:
                continue
            live[(src, dport)] = live.get((src, dport), 0) + 1
        for (src, dport), n in live.items():
            e = self.seen.setdefault((src, dport), {"first": now})
            e.update(last=now, src=nodes[src]["title"], dst=nodes[port_node[dport]]["title"], dstKey=port_node[dport], srcClient=nodes[src]["client"])
        edges = []
        for (src, dport), e in list(self.seen.items()):
            if (src, dport) in live:
                state = "active"
            elif now - e["last"] > KEEP:
                del self.seen[(src, dport)]
                continue
            elif dport not in port_node:
                state = "broken"
            else:
                state = "idle"
            if src not in nodes:
                if state == "active" or src.startswith("client:"):
                    continue   # a client that went away takes its idle links with it
                nodes[src] = {"id": src, "title": e["src"], "ports": [], "kind": "gone", "appId": None, "framework": None,
                              "project": None, "memMb": None, "pids": [], "self": False, "client": False, "gone": True}
            dst = port_node.get(dport) or e["dstKey"]
            if dst not in nodes:
                nodes[dst] = {"id": dst, "title": e["dst"], "ports": [dport], "kind": "gone", "appId": None, "framework": None,
                              "project": None, "memMb": None, "pids": [], "self": False, "client": False, "gone": True}
            edges.append({"id": f"{src}>{dport}", "from": src, "to": dst, "port": dport, "state": state, "count": live.get((src, dport), 0),
                          "since": e["first"], "last": e["last"], "declared": False})
        by_app = {}
        for n in nodes.values():
            if n.get("appId"):
                by_app[n["appId"]] = n
        for a in apps:
            for ref in a.get("dependsOn") or []:
                dep = next((x for x in apps if x["id"] == ref or (x.get("slug") or "").lower() == str(ref).lower()
                            or x["name"].lower() == str(ref).lower()), None)
                if not dep:
                    continue
                src, dst = f"app:{a['id']}", f"app:{dep['id']}"
                if any(e["from"] == src and e["to"] == dst for e in edges):
                    for e in edges:
                        if e["from"] == src and e["to"] == dst:
                            e["declared"] = True
                    continue
                if src not in nodes and dst not in nodes:
                    continue   # neither runs: nothing to show
                for key, app in ((src, a), (dst, dep)):
                    nodes.setdefault(key, {"id": key, "title": app["name"], "ports": [], "kind": "stopped", "appId": app["id"],
                                           "framework": None, "project": None, "memMb": None, "pids": [], "self": False,
                                           "client": False, "stopped": True})
                state = "broken" if a["id"] in by_app and dep["id"] not in by_app else "declared"
                port = (by_app[dep["id"]]["ports"] or [None])[0] if dep["id"] in by_app else dep.get("port")
                edges.append({"id": f"{src}>{dst}", "from": src, "to": dst, "port": port, "state": state, "count": 0,
                              "since": None, "last": None, "declared": True})
        return {"nodes": sorted(nodes.values(), key=lambda n: (n["client"], n["title"].lower())), "edges": edges}

    @staticmethod
    def describe(m):
        """The map as lines of text, for the command line and coding agents."""
        title = {n["id"]: n["title"] for n in m["nodes"]}
        lines = []
        for e in sorted(m["edges"], key=lambda e: (e["state"] != "broken", title.get(e["from"], ""))):
            what = {"active": f"{e['count']} open connection(s)", "idle": "quiet now", "broken": "BROKEN: the server is gone",
                    "declared": "declared dependency, no traffic seen yet"}[e["state"]]
            if e["state"] == "broken" and e["declared"] and not e["count"]:
                what = "BROKEN: depends on it, but it is not running"
            lines.append(f"{title.get(e['from'], e['from'])} → {title.get(e['to'], e['to'])}" + (f" :{e['port']}" if e.get("port") else "") + f"  ({what})")
        return "\n".join(lines) or "No connections between local services seen yet."
