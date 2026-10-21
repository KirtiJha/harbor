"""Who held each port, and when: one line per stretch a process listened on a port, kept for 30 days in
~/.porthaven/history.jsonl, so "what was on :3000 yesterday at 3 pm?" has an answer.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time

KEEP_DAYS = 30
MAX_BYTES = 5 * 1024 * 1024


class PortHistory:
    def __init__(self, root):
        self.path = root / "history.jsonl"
        self.lock = threading.Lock()
        self.open = {}      # (pid, port) -> interval still running

    def start(self, pid, port, info, started=None):
        with self.lock:
            if (pid, port) not in self.open:
                self.open[(pid, port)] = {"port": port, "pid": pid, "start": round(started or time.time(), 1), "end": None, **info}

    def update(self, pid, port, info):
        with self.lock:
            iv = self.open.get((pid, port))
            if iv:
                iv.update({k: v for k, v in info.items() if v})

    def end(self, pid, port, info=None, ended=None, reason=None):
        with self.lock:
            iv = self.open.pop((pid, port), None)
        if not iv:
            return None
        iv.update({k: v for k, v in (info or {}).items() if v})
        iv["end"] = round(ended or time.time(), 1)
        if reason:
            iv["until"] = reason
        self._append([iv])
        return iv

    def flush(self):
        """Porthaven is stopping: write what is still running, marked as such (the next start picks it up again)."""
        with self.lock:
            items = [{**iv, "end": round(time.time(), 1), "until": "porthaven stopped"} for iv in self.open.values()]
        self._append(items)

    def _append(self, items):
        if not items:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                for iv in items:
                    f.write(json.dumps(iv, separators=(",", ":")) + "\n")
            if self.path.stat().st_size > MAX_BYTES:
                self.prune()
        except OSError:
            pass

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def prune(self):
        cutoff = time.time() - KEEP_DAYS * 86400
        keep = [iv for iv in self._read() if (iv.get("end") or time.time()) >= cutoff]
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for iv in keep[-20000:]:
                f.write(json.dumps(iv, separators=(",", ":")) + "\n")
        os.replace(tmp, self.path)

    def query(self, port=None, since=None, until=None, at=None):
        """Intervals for a port (or every port), newest first. `at` keeps the ones that covered that moment.
        A process seen again after Porthaven restarted is one stretch, not two."""
        with self.lock:
            running = [dict(iv) for iv in self.open.values()]
        rows = [iv for iv in self._read() + running if port is None or iv.get("port") == port]
        merged = {}
        for iv in sorted(rows, key=lambda x: x["start"]):
            key = (iv["pid"], iv["port"])
            prev = merged.get(key)
            if prev and prev[-1].get("until") == "porthaven stopped" and iv["start"] <= prev[-1]["end"] + 5:
                prev[-1].update({**{k: v for k, v in iv.items() if v is not None}, "start": prev[-1]["start"], "end": iv["end"],
                                 "until": iv.get("until")})
                continue
            merged.setdefault(key, []).append(dict(iv))
        out = [iv for ivs in merged.values() for iv in ivs]
        now = time.time()
        if at is not None:
            out = [iv for iv in out if iv["start"] <= at <= (iv["end"] or now)]
        if since is not None:
            out = [iv for iv in out if (iv["end"] or now) >= since]
        if until is not None:
            out = [iv for iv in out if iv["start"] <= until]
        return sorted(out, key=lambda iv: iv["start"], reverse=True)


# ---------------------------------------------------------------- reading "yesterday 3pm", "2h ago", "14:30"

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
AGO = re.compile(r"^(\d+(?:\.\d+)?)\s*(s|sec|secs|m|min|mins|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)\s+ago$")
CLOCK = re.compile(r"^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)?$")


def parse_when(text, now=None):
    """A moment typed by a person -> a timestamp. Raises ValueError with an example when it cannot tell."""
    now = now or time.time()
    s = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not s or s == "now":
        return now
    m = AGO.match(s)
    if m:
        n, unit = float(m.group(1)), m.group(2)[0]
        return now - n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    try:
        return dt.datetime.fromisoformat(s.replace(" at ", " ")).timestamp()
    except ValueError:
        pass
    today = dt.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    day, explicit_day = today, False
    words = s.replace(" at ", " ").split(" ")
    if words[0] in ("today", "yesterday") or words[0] in WEEKDAYS or words[0][:3] in [w[:3] for w in WEEKDAYS]:
        w = words.pop(0)
        explicit_day = True
        if w == "yesterday":
            day = today - dt.timedelta(days=1)
        elif w != "today":
            idx = [x[:3] for x in WEEKDAYS].index(w[:3])
            back = (today.weekday() - idx) % 7 or 7
            day = today - dt.timedelta(days=back)
    rest = " ".join(words).strip()
    if not rest:
        if explicit_day:
            return day.timestamp() + (12 * 3600 if day != today else 0)
        raise ValueError(f"Could not read “{text}”. Try 15:00, “yesterday 3pm”, “2h ago” or 2026-10-20 15:00.")
    m = CLOCK.match(rest.replace(" ", "") if re.match(r"^\d", rest) else rest)
    if not m:
        raise ValueError(f"Could not read “{text}”. Try 15:00, “yesterday 3pm”, “2h ago” or 2026-10-20 15:00.")
    hour, minute, sec = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)
    if m.group(4) == "pm" and hour < 12:
        hour += 12
    if m.group(4) == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        raise ValueError(f"{rest} is not a time of day.")
    ts = day.replace(hour=hour, minute=minute, second=sec).timestamp()
    if not explicit_day and ts > now:
        ts -= 86400   # "15:00" said in the morning means yesterday afternoon
    return ts
