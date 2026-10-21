"""Searching the output of every saved app at once, and spotting error lines as they are written."""
from __future__ import annotations

import re
import time

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
ERROR = re.compile(r"\b(error|exception|traceback|fatal|panic|unhandled(?:\s*(?:promise)?\s*rejection)?|segmentation fault)\b"
                   r"|\b[A-Z]\w*(?:Error|Exception)\b|npm ERR!|ERR_[A-Z_]+|\bfailed to\b|HTTP/\d(?:\.\d)?\"?\s+5\d\d\b"
                   r"|\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+\S+\s+5\d\d\s", re.I)
NOT_ERROR = re.compile(r"\b(0|no) errors?\b|errors?:\s*0\b|without errors|error_?page|\.error\(|errorHandler|onerror", re.I)
RUN_HEADER = re.compile(r"^── (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})  \$ ")
TAIL_BYTES = 2 * 1024 * 1024


def is_error(text):
    plain = ANSI.sub("", text or "")
    return bool(ERROR.search(plain)) and not NOT_ERROR.search(plain)


def matcher(query, regex=False, case=False):
    """A function telling whether a line matches; raises ValueError for a bad regular expression."""
    if not query:
        return lambda s: True
    if regex:
        try:
            rx = re.compile(query, 0 if case else re.I)
        except re.error as err:
            raise ValueError(f"Not a valid regular expression: {err}.") from err
        return lambda s: bool(rx.search(s))
    q = query if case else query.lower()
    return (lambda s: q in s) if case else (lambda s: q in s.lower())


def file_lines(path):
    """The last part of a log file as [{seq, t, text}], with each line dated by the run it belongs to."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > TAIL_BYTES:
                f.seek(size - TAIL_BYTES)
                f.readline()   # skip the partial first line
            raw = f.read()
    except OSError:
        return []
    out, run_t = [], None
    for i, line in enumerate(raw.decode("utf-8", "replace").splitlines()):
        m = RUN_HEADER.match(line)
        if m:
            try:
                run_t = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                run_t = None
        out.append({"seq": i + 1, "t": run_t, "text": line.rstrip("\r"), "run": True})
    return out


def search(sources, query="", regex=False, case=False, errors_only=False, since=None, limit=500):
    """sources: [(app, lines)] -> {"matches": [...], "counts": {app id: n}, "truncated": bool}, newest first."""
    match = matcher(query, regex, case)
    hits, counts = [], {}
    for app, lines in sources:
        n = 0
        for ln in lines:
            text = ANSI.sub("", ln["text"])
            if since and (ln.get("t") or 0) < since:
                continue
            if errors_only and not is_error(text):
                continue
            if not match(text):
                continue
            n += 1
            hits.append({"appId": app["id"], "app": app["name"], "seq": ln["seq"], "t": ln.get("t"), "text": text[:2000],
                         "approx": bool(ln.get("run")), "error": is_error(text)})
        counts[app["id"]] = n
    hits.sort(key=lambda h: (h["t"] or 0, h["seq"]), reverse=True)
    return {"matches": hits[:limit], "counts": counts, "truncated": len(hits) > limit, "total": len(hits)}
