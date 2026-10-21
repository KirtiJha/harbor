"""Which coding-agent session started a server, so servers an agent leaves running can be found and stopped.

An agent (Claude Code, Codex, Gemini CLI, …) runs dev servers as its own child processes. Porthaven notes the agent
session while it is still an ancestor of the server; when that session ends, the server is reparented and would
otherwise look like any other forgotten process.
"""
from __future__ import annotations

import re

from . import classify

# (id, label, pattern on the program or, for node/python/bun, the script it runs)
AGENTS = [
    ("claude", "Claude Code", re.compile(r"(^|[\\/])claude(?i:\.exe)?$|@anthropic-ai[\\/]claude-code[\\/]")),
    ("codex", "Codex", re.compile(r"(^|[\\/])codex(?i:\.exe)?$|@openai[\\/]codex[\\/]")),
    ("cursor", "Cursor Agent", re.compile(r"(^|[\\/])cursor-agent(?i:\.exe)?$")),
    ("gemini", "Gemini CLI", re.compile(r"(^|[\\/])gemini(?i:\.exe)?$|@google[\\/]gemini-cli[\\/]")),
    ("copilot", "Copilot CLI", re.compile(r"(^|[\\/])copilot(?i:\.exe)?$|@github[\\/]copilot[\\/]")),
    ("aider", "Aider", re.compile(r"(^|[\\/])aider(?i:\.exe)?$")),
    ("opencode", "opencode", re.compile(r"(^|[\\/])opencode(?i:\.exe)?$|opencode-ai[\\/]")),
    ("goose", "Goose", re.compile(r"(^|[\\/])goose(?i:\.exe)?$")),
    ("amp", "Amp", re.compile(r"@sourcegraph[\\/]amp[\\/]")),
    ("qwen", "Qwen Code", re.compile(r"@qwen-code[\\/]")),
    ("crush", "Crush", re.compile(r"(^|[\\/])crush(?i:\.exe)?$")),
]
INTERPRETERS = re.compile(r"(^|[\\/])(node|bun|deno|python\d*(\.\d+)?|uv|pipx)(?i:\.exe)?$", re.I)


def _tokens(args):
    s = (args or "").strip()
    first = classify.first_token(s)
    rest = s[len(first) + (2 if s.startswith('"') else 0):].strip()
    second = classify.first_token(rest) if rest else ""
    return first, second


def agent_of(args):
    """(id, label) when a command line is a coding agent's own process, else None."""
    first, second = _tokens(args)
    for aid, label, rx in AGENTS:
        if rx.search(first) or (INTERPRETERS.search(first) and second and rx.search(second)):
            return aid, label
    return None


def find_session(pid, procs, now, limit=40, stop_pids=()):
    """The nearest coding-agent ancestor of `pid`: {agent, label, pid, startedAt}, or None. The walk stops at
    `stop_pids` (Porthaven itself: an app Porthaven launched is Porthaven's, even when an agent started Porthaven)."""
    cur, seen = procs.get(pid), set()
    while cur and limit:
        limit -= 1
        seen.add(cur["pid"])
        parent = procs.get(cur["ppid"])
        if not parent or parent["pid"] in seen or parent["pid"] <= 1 or parent["pid"] in stop_pids:
            return None
        hit = agent_of(parent["args"])
        if hit:
            return {"agent": hit[0], "label": hit[1], "pid": parent["pid"], "startedAt": started(parent, now)}
        cur = parent
    return None


def started(proc, now):
    return round(now - proc["elapsed"]) if proc and proc.get("elapsed") is not None else None


def alive(session, procs, now):
    """The session's process is still running (and is the same process, not a reused pid)."""
    p = procs.get(session["pid"])
    if not p:
        return False
    if session.get("startedAt") is None or p.get("elapsed") is None:
        return True
    return abs(started(p, now) - session["startedAt"]) <= 5


def from_header(value, procs, now):
    """The session an MCP client says it belongs to ("<pid>"), checked against the process table."""
    try:
        pid = int(str(value).split(":")[0])
    except (TypeError, ValueError):
        return None
    p = procs.get(pid)
    hit = agent_of(p["args"]) if p else None
    if not hit:
        return None
    return {"agent": hit[0], "label": hit[1], "pid": pid, "startedAt": started(p, now)}
