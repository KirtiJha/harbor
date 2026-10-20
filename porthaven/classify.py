"""What a listening process is: framework, kind, project, display name, and the app it belongs to."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

# (id, label, kind, pattern on the full command line, speaks HTTP)
FRAMEWORKS = [
    ("porthaven", "Porthaven", "tool", r"-m porthaven\b|porthaven/__main__", True),
    ("vite", "Vite", "dev", r"\bvite(\.js)?\b", True),
    ("next", "Next.js", "dev", r"\bnext(-server)?\b|next/dist", True),
    ("nuxt", "Nuxt", "dev", r"\bnuxi?\b", True),
    ("astro", "Astro", "dev", r"\bastro\b", True),
    ("remix", "Remix", "dev", r"\bremix\b", True),
    ("storybook", "Storybook", "dev", r"storybook", True),
    ("angular", "Angular", "dev", r"\bng(\.js)? serve\b|@angular/cli", True),
    ("cra", "Create React App", "dev", r"react-scripts", True),
    ("webpack", "Webpack", "dev", r"webpack(-dev-server)?", True),
    ("metro", "Expo / Metro", "dev", r"\bexpo\b|\bmetro\b", True),
    ("n8n", "n8n", "service", r"\bn8n\b", True),
    ("uvicorn", "Uvicorn", "dev", r"\buvicorn\b", True),
    ("gunicorn", "Gunicorn", "dev", r"\bgunicorn\b", True),
    ("hypercorn", "Hypercorn", "dev", r"\bhypercorn\b", True),
    ("fastapi", "FastAPI", "dev", r"\bfastapi (dev|run)\b", True),
    ("django", "Django", "dev", r"manage\.py\s+runserver|\bdaphne\b", True),
    ("flask", "Flask", "dev", r"\bflask\b", True),
    ("streamlit", "Streamlit", "dev", r"\bstreamlit\b", True),
    ("gradio", "Gradio", "dev", r"\bgradio\b", True),
    ("jupyter", "Jupyter", "dev", r"jupyter|ipykernel_launcher|jupyter-lab", True),
    ("mkdocs", "MkDocs", "dev", r"\bmkdocs\b", True),
    ("pyhttp", "Python http.server", "dev", r"-m\s+http\.server", True),
    ("rails", "Rails", "dev", r"\brails\b|\bpuma\b", True),
    ("hugo", "Hugo", "dev", r"\bhugo\b", True),
    ("jekyll", "Jekyll", "dev", r"\bjekyll\b", True),
    ("php", "PHP", "dev", r"\bphp\b.*\s-S\s", True),
    ("spring", "Spring Boot", "dev", r"spring|bootRun", True),
    ("ollama", "Ollama", "service", r"\bollama\b", True),
    ("postgres", "PostgreSQL", "database", r"\bpostgres\b|\bpostmaster\b", False),
    ("mysql", "MySQL", "database", r"\bmysqld\b|\bmariadbd?\b", False),
    ("redis", "Redis", "database", r"\bredis-server\b|\bvalkey-server\b", False),
    ("mongo", "MongoDB", "database", r"\bmongod\b", False),
    ("elastic", "Elasticsearch", "database", r"elasticsearch|opensearch", True),
    ("docker", "Docker", "service", r"com\.docker|vpnkit|docker-proxy|\bdockerd\b|OrbStack", True),
    ("inspector", "Node inspector", "dev", r"--inspect", True),
    ("deno", "Deno", "dev", r"(^|[\\/])deno\b", True),
    ("bun", "Bun", "dev", r"(^|[\\/])bun\b", True),
    ("node", "Node.js", "dev", r"(^|[\\/])node\b", True),
    ("python", "Python", "dev", r"(^|[\\/])[Pp]ython(3(\.\d+)?)?\b", True),
    ("ruby", "Ruby", "dev", r"(^|[\\/])ruby\b", True),
    ("java", "Java", "dev", r"(^|[\\/])java\b", True),
    ("go", "Go", "dev", r"go-build|/exe/", True),
]
_COMPILED = [(i, l, k, re.compile(p), h) for i, l, k, p, h in FRAMEWORKS]

# Commands that are part of the operating system or a desktop app, not something a developer started.
SYSTEM_COMMANDS = {"rapportd", "ControlCenter", "ControlCe", "sharingd", "identityservicesd", "launchd", "mDNSResponder",
                   "AirPlayXPCHelper", "WiFiAgent", "remoted", "cupsd", "netbiosd", "stable",
                   # Windows
                   "System", "svchost.exe", "lsass.exe", "services.exe", "wininit.exe", "spoolsv.exe", "System Idle Process",
                   "Registry", "smss.exe", "csrss.exe", "winlogon.exe", "MsMpEng.exe", "SearchIndexer.exe"}
WIN_APPS = re.compile(r"\\(?:Program Files(?: \(x86\))?|AppData\\Local\\Programs)\\([^\\]+)\\", re.I)
RUNTIMES = re.compile(r"(?:^|[\\/])(node|python\d*|pythonw|java|ruby|deno|bun|php|dotnet|go|docker\w*|postgres|mysqld|redis-server|mongod)(\.exe)?$", re.I)
APP_BUNDLE = re.compile(r"/([^/]+)\.app/")

PORT_HINTS = {
    3000: "React / Next / Express", 3001: "Dev server", 4173: "Vite preview", 4200: "Angular", 5000: "Flask / AirPlay",
    5173: "Vite", 5174: "Vite (2nd)", 5432: "PostgreSQL", 5678: "n8n", 6006: "Storybook", 6379: "Redis",
    7000: "AirPlay", 8000: "Django / Uvicorn", 8080: "HTTP alt", 8081: "Metro", 8501: "Streamlit", 8787: "Wrangler / API",
    8888: "Jupyter", 9000: "PHP-FPM / MinIO", 9229: "Node inspector", 9200: "Elasticsearch", 11434: "Ollama", 27017: "MongoDB",
    3306: "MySQL", 1313: "Hugo", 4000: "Jekyll / Phoenix", 7860: "Gradio", 24678: "Vite HMR",
}


def framework(args):
    for fid, label, kind, rx, http in _COMPILED:
        if rx.search(args or ""):
            return {"id": fid, "label": label, "kind": kind, "http": http}
    return None


def app_bundle(args):
    m = APP_BUNDLE.search(args or "") or (WIN_APPS.search(first_token(args)) if not RUNTIMES.search(first_token(args)) else None)
    if not m:
        return None
    name = m.group(1)
    return {"Code Helper": "VS Code", "Code": "VS Code", "Microsoft VS Code": "VS Code", "Electron": "Electron app"}.get(name, name)


INTERPRETER_BUNDLES = {"Python", "Python3"}


def bundled_executable(args):
    """True when the program itself lives inside a desktop app (a macOS .app bundle, or Program Files /
    AppData\\Local\\Programs on Windows), not a language runtime installed there."""
    if RUNTIMES.search(first_token(args)):
        return False
    program = (args or "").split(" .", 1)[0].split(" -", 1)[0]   # unquoted paths may contain spaces
    m = APP_BUNDLE.search(program)
    return bool((m and m.group(1) not in INTERPRETER_BUNDLES) or WIN_APPS.search(program))


def kind_of(command, args, uid, my_uid, fw):
    if fw and fw["id"] == "porthaven":
        return "tool"
    if command in SYSTEM_COMMANDS or (args or "").startswith(("/System/", "/usr/libexec/", "/usr/sbin/")) or uid == 0:
        return "system"
    if fw and fw["kind"] in ("database", "service"):
        return fw["kind"]
    if bundled_executable(args):
        return "app"
    if uid is not None and uid != my_uid:
        return "system"
    return "dev" if fw else "other"


# ---------------------------------------------------------------- projects

MARKERS = ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Gemfile", "composer.json", "manage.py", "deno.json")
_project_cache = {}


def _manifest_name(d):
    pj = d / "package.json"
    if pj.is_file():
        try:
            name = json.loads(pj.read_text(errors="replace")).get("name")
            if isinstance(name, str) and name:
                return name
        except (OSError, ValueError):
            pass
    pp = d / "pyproject.toml"
    if pp.is_file():
        try:
            m = re.search(r'^\s*name\s*=\s*"([^"]+)"', pp.read_text(errors="replace"), re.M)
            if m:
                return m.group(1)
        except OSError:
            pass
    return None


def project(cwd):
    """{name, root, repo, path} for a working directory, or None for '/', the home folder and system paths."""
    if not cwd or cwd in _project_cache:
        return _project_cache.get(cwd)
    home = Path.home()
    p = Path(cwd)
    result = None
    if p != Path("/") and p != home and not str(p).startswith(("/System", "/usr", "/private/var", "/Library")):
        manifest_dir, git_dir = None, None
        cur = p
        while True:
            if manifest_dir is None and any((cur / m).exists() for m in MARKERS):
                manifest_dir = cur
            if (cur / ".git").exists():
                git_dir = cur
                break
            if cur == home or cur.parent == cur:
                break
            cur = cur.parent
        root = manifest_dir or git_dir or p
        name = _manifest_name(root) if manifest_dir else None
        repo = git_dir.name if git_dir else None
        result = {"name": name or root.name, "root": str(root), "repo": repo, "path": str(p),
                  "sub": str(root.relative_to(git_dir)) if git_dir and root != git_dir and git_dir in root.parents else None}
    _project_cache[cwd] = result
    return result


# ---------------------------------------------------------------- the app a process belongs to

SHELLS = {"sh", "bash", "zsh", "fish", "dash", "ksh", "tcsh", "cmd", "powershell", "pwsh"}
RUNNERS = re.compile(r"(^|[\\/])(make|gmake|npm|npx|pnpm|yarn|bun|turbo|concurrently|nodemon|honcho|foreman|overmind|"
                     r"docker-compose|cargo|poetry|uv|pipenv|just|task|watchfiles|tsx|ts-node|air|reflex)\b|"
                     r"\b(npm-cli\.js|npx-cli\.js|pnpm\.c?js|yarn\.c?js|concurrently|nodemon|turbo|vite|next|"
                     r"uvicorn|watchfiles|flask|manage\.py|honcho|multiprocessing\.spawn|run-p|run-s|npm-run-all)\b")


def first_token(args):
    """The program part of a command line, keeping "C:\\Program Files\\..." quoted paths whole."""
    s = (args or "").strip()
    if s.startswith('"'):
        end = s.find('"', 1)
        return s[1:end] if end > 0 else s[1:]
    return s.split(" ", 1)[0]


def base(args):
    name = re.split(r"[\\/]", first_token(args))[-1].lstrip("-")
    return name[:-4] if name.lower().endswith(".exe") else name


RUNS_COMMAND = re.compile(r"(?:^|\s)(?:-c|/c|/k|-Command|-File)(?:\s|$)", re.I)


def is_shell_command(args):
    return base(args).lower() in SHELLS and bool(RUNS_COMMAND.search(f" {args} "))


def is_interactive_shell(args):
    return base(args).lower() in SHELLS and not RUNS_COMMAND.search(f" {args} ")


def app_root(pid, procs, my_uid, stop_pids=()):
    """Walk up from a listening process through launchers (make, npm, shells running a command, reloaders) and
    stop below anything that hosts more than one app: an interactive shell, a terminal, an editor, launchd."""
    cur = procs.get(pid)
    if not cur:
        return pid
    root = cur
    seen = {pid}
    while True:
        parent = procs.get(root["ppid"])
        if not parent or parent["pid"] <= 1 or parent["pid"] in seen or parent["pid"] in stop_pids:
            break
        if parent["uid"] != my_uid or is_interactive_shell(parent["args"]):
            break
        if is_shell_command(parent["args"]):
            # A `sh -c` belongs to the app only when a launcher started it (npm, make); a `zsh -c` straight
            # from a terminal, an editor or an agent is that host's wrapper, not part of the app.
            grand = procs.get(parent["ppid"])
            if not grand or not (RUNNERS.search(grand["args"]) or is_shell_command(grand["args"])):
                break
        elif not RUNNERS.search(parent["args"]):
            break
        seen.add(parent["pid"])
        root = parent
    return root["pid"]


def descendants(pid, procs):
    children = {}
    for p in procs.values():
        children.setdefault(p["ppid"], []).append(p["pid"])
    out, stack = [], [pid]
    while stack:
        cur = stack.pop()
        for c in children.get(cur, []):
            if c not in out and c != pid:
                out.append(c)
                stack.append(c)
    return out


def ancestors(pid, procs):
    out, cur = [], procs.get(pid)
    while cur and cur["ppid"] in procs and cur["ppid"] not in [a["pid"] for a in out] and cur["ppid"] != 0:
        cur = procs[cur["ppid"]]
        out.append(cur)
    return out


def display_command(args, limit=None):
    """A short, readable command: node_modules/.bin paths and interpreter paths trimmed."""
    s = args or ""
    s = re.sub(r'^"([^"]+)"', lambda m: m.group(1).replace(" ", "\ue000"), s)   # keep a quoted program path whole
    s = re.sub(r"\S*[\\/]node_modules[\\/]\.bin[\\/](\.\.[\\/])?", "", s)
    s = re.sub(r"\S*[\\/]node_modules[\\/](\S+?)[\\/]bin[\\/]", r"\1 ", s)
    s = re.sub(r"^\S*[\\/](Python|python3?(\.\d+)?|pythonw?|node|ruby|java)(\.exe)?\b", r"\1", s, flags=re.I)
    s = s.replace("\ue000", " ")
    s = re.sub(r"^(Python|python3?(\.\d+)?) (\S*/)?\.?venv/bin/", "", s)
    return s if not limit or len(s) <= limit else s[:limit - 1] + "…"


PATH_TOKEN = re.compile(r'"([A-Za-z]:\\[^"]+|/[^"]+)"|([A-Za-z]:\\\S+|/\S+)')


def dir_from_args(args):
    """A project folder guessed from paths in a command line, for when the working folder can't be read
    (Windows): the folder above node_modules, or the folder of a script."""
    for m in PATH_TOKEN.finditer(args or ""):
        path = m.group(1) or m.group(2)
        sep = "\\" if "\\" in path else "/"
        marker = f"{sep}node_modules{sep}"
        if marker in path:
            return path.split(marker, 1)[0]
        if re.search(r"\.(py|js|mjs|cjs|ts)$", path, re.I) and not re.search(r"[\\/](lib|Lib|site-packages|Program Files)[\\/]", path):
            return os.path.dirname(path)
    return None
