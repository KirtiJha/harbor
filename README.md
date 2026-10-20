# Harbor

Every app listening on a port on your Mac, in one live dashboard: what it is, which project it belongs
to, whether it answers, and one click to open, stop, restart or start it.

```bash
cd harbor
make run            # builds the UI the first time, starts Harbor, opens http://localhost:7475
make install        # optional: a `harbor` command on your PATH (~/.local/bin)
```

It needs only `python3` (3.9+, standard library only) plus `lsof` and `ps`, which macOS has. Node is used only to
build the UI once. The overview page is at http://localhost:7475/welcome.

## What it does

**Ports**
- Live list of every listening TCP port, refreshed every 2 s while the page is open.
- Each row shows the project (from `package.json`, `pyproject.toml` or git), the framework (Vite, Next, Uvicorn,
  Django, Postgres…), the page title, HTTP status and response time, uptime, CPU and memory sparklines,
  and open connections.
- Grouped by project or by type, with filters: Mine, Web, Dev servers, Databases, On network, Pinned,
  System & apps.
- Search works on port, title, project, folder, command and your notes; `:51` finds ports starting with 51.
- **Network warning** on anything bound to all interfaces, so you can see it is reachable from your network.
- Workers sharing a socket (uvicorn `--reload`, gunicorn) collapse into one row.
- Docker containers are named on the ports they publish.
- **Forgotten servers**: dev servers with no connections and no CPU for 4 h (you can change this) are marked
  idle, listed with the memory they hold, and stopped in one click.
- **Multi-select** (space or the row checkbox) to stop several ports or apps at once.
- **Response-time history** and an "ok" count per port, plus each port's own history in the detail panel.
- **Phone testing**: network-exposed servers show their Wi-Fi URL.

**Stopping and restarting**
- **Stop process** stops just that pid.
- **Stop whole app** finds what launched the server (`make dev`, `npm run dev`, a reloader) and stops it and
  every child, so nothing respawns it. It never climbs into your terminal, editor or agent shell.
- Stopping is polite: SIGTERM first, then SIGKILL only after a grace period, which you can set.
- **Restart** re-runs the app's own command in its folder under Harbor, so you then get its logs.
- **Guard rails:**
  - Harbor itself and other users' processes can't be stopped.
  - Desktop apps and macOS services need you to type the port number to confirm.
  - Harbor never uses sudo.

**Apps (saved launchers)**
- Save a command, folder and port once, then start or stop it with one click.
  - Use **Save as app** on any running row.
  - Use **Find projects** to scan a folder for npm/pnpm/yarn scripts, Makefile targets, Django, FastAPI,
    Flask and Streamlit apps, and Compose files.
- Live output with colours, clickable URLs, filtering, and a jump to error lines. Output is also kept in
  `~/.harbor/logs/`.
- **Port conflicts are handled before starting:**
  - Harbor shows who holds the port.
  - It offers the next free port: it sets `PORT` and fills `{port}` in the command.
  - Or it can stop the holder and take the port.
- Flags an app that is running off its saved port, and one already running outside Harbor (Harbor can
  restart it under Harbor to capture logs).
- Optional auto-restart on crash, up to 3 times in 2 minutes.
- **Groups**: put backend and frontend in a group and start or stop them together.
- **Stable names**: `http://<short-name>.localhost:7475` always reaches the app, whatever port it is on today.
  - Websockets and hot reload work through it.
  - Every saved app gets one. A project with a single web port is reachable by its project name too
    (e.g. `docs-web.localhost:7475`).
- **Export and import** apps as JSON to share a setup.

**Everything else**
- **Pin and watch:**
  - Pinned ports stay on top.
  - A watched port that goes down raises a banner, a toast and, when the tab is hidden, a desktop
    notification.
- **Notes and names per port.** These survive restarts.
- **Activity timeline** of ports opening and closing, and apps starting, stopping and crashing.
- **Port tools:** "is this port free?" (who holds it, and free ports nearby) and "find free ports from 3000/5173/8000…".
- **Folders:** open a project's folder in Finder, your editor (`code`/`cursor`) or Terminal.
- **Keyboard:**

  | Keys | Action |
  |---|---|
  | `⌘K` | Command palette (type a port number to jump to it) |
  | `/` | Search |
  | `1` `2` `3` | Ports, Apps, Activity tabs |
  | `j` `k` | Move between rows |
  | `o` | Open |
  | `c` | Copy URL |
  | `p` | Pin |
  | `w` | Watch |
  | `x` / `⇧X` | Stop the process / the whole app |
  | `n` | New app |
  | `t` | Theme |
  | `?` | Help |

- Light and dark themes.

## Command line

```bash
harbor                 # dashboard (same as `harbor serve`)
harbor ls [--all]      # listening ports; --json for scripts
harbor who 5173        # what is on a port: command, folder, app, HTTP answer
harbor kill 5173 --app # stop the whole app on a port (asks first; -y to skip)
harbor free 3000 -n 5  # next free ports
harbor open 5173
harbor service install # start Harbor at login (launchd); uninstall / status
```

## Safety

- Harbor listens on 127.0.0.1 only.
- It answers only requests addressed to `localhost`/`127.0.0.1` on its own port, which blocks DNS
  rebinding from web pages.
- Every change needs a per-session token that only Harbor's own page can read.
- It opens folders only for apps it is showing.
- It stores apps, notes and settings in `~/.harbor/state.json` (move it with `HARBOR_HOME`). Don't put
  secrets in an app's environment there; let the app read its own `.env`.

Apps that Harbor started stop when Harbor stops (Ctrl-C), because Harbor owns their output.

## Development

```bash
make test             # backend tests (unittest, includes a real server and a real app run) + UI type check
bin/harbor --no-open  # backend on :7475
make dev              # UI with hot reload on :7476, proxying /api to :7475
```

- **`harbor/`**: the Python backend.
  - `system.py` reads lsof and ps.
  - `classify.py` decides framework, kind, project and the owning app.
  - `core.py` runs the scan loop and the actions.
  - `server.py` serves the API, the event stream and the UI.
- **`web/`**: the React + Tailwind UI.
