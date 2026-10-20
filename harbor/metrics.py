"""A week of minute-by-minute history (ports, memory, CPU, connections, memory per project) for the
Activity and Insights views. Kept in memory and saved to ~/.harbor/metrics.json every few minutes."""
from __future__ import annotations

import collections
import json
import os
import threading
import time

WEEK = 7 * 86400
EVERY = 60          # one sample a minute
RANGES = {"1h": 3600, "6h": 6 * 3600, "24h": 86400, "7d": WEEK}


def sample_from(snap):
    rows = snap["listeners"]
    dev = [r for r in rows if r["kind"] in ("dev", "service", "tool", "other", "database")]
    by_project = collections.Counter()
    for r in dev:
        by_project[(r["project"] or {}).get("name") or (r["framework"] or {}).get("label") or r["command"]] += r["memMb"] or 0
    top = dict(by_project.most_common(8))
    rest = sum(by_project.values()) - sum(top.values())
    if rest > 0:
        top["other"] = rest
    return {"ts": round(snap["scannedAt"]), "ports": len({r["port"] for r in rows}), "dev": len({r["port"] for r in dev}),
            "memMb": round(sum(r["memMb"] or 0 for r in dev), 1), "cpu": round(sum(r["cpu"] or 0 for r in dev), 1),
            "conns": sum(r["connections"] for r in rows), "idle": snap["summary"].get("idle", 0),
            "exposed": snap["summary"].get("exposed", 0), "apps": snap["summary"].get("appsRunning", 0),
            "byProject": {k: round(v, 1) for k, v in top.items()}}


class Metrics:
    def __init__(self, root):
        self.path = root / "metrics.json"
        self.samples = collections.deque(maxlen=WEEK // EVERY + 10)
        self.lock = threading.Lock()
        self.saved_at = 0.0
        try:
            for s in json.loads(self.path.read_text()):
                if time.time() - s["ts"] < WEEK:
                    self.samples.append(s)
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def add(self, snap, now=None):
        now = now or time.time()
        with self.lock:
            if self.samples and now - self.samples[-1]["ts"] < EVERY:
                return False
            self.samples.append(sample_from(snap))
        if now - self.saved_at > 300:
            self.save()
        return True

    def save(self):
        with self.lock:
            data = list(self.samples)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")))
        os.replace(tmp, self.path)
        self.saved_at = time.time()

    def query(self, seconds, points=240, now=None):
        """Samples in the last `seconds`, averaged into at most `points` buckets."""
        now = now or time.time()
        start = now - seconds
        with self.lock:
            rows = [s for s in self.samples if s["ts"] >= start]
        if len(rows) <= points:
            return rows
        width = seconds / points
        buckets = collections.OrderedDict()
        for s in rows:
            buckets.setdefault(int((s["ts"] - start) // width), []).append(s)
        out = []
        for group in buckets.values():
            n = len(group)
            avg = {k: round(sum(g[k] for g in group) / n, 1) for k in ("ports", "dev", "memMb", "cpu", "conns", "idle", "exposed", "apps")}
            projects = collections.Counter()
            for g in group:
                projects.update(g.get("byProject") or {})
            avg["byProject"] = {k: round(v / n, 1) for k, v in projects.items()}
            avg["ts"] = group[-1]["ts"]
            out.append(avg)
        return out
