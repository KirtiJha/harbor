<div align="center">

<img src="web/public/porthaven.svg" width="72" alt="Porthaven logo" />

# Porthaven

**A safe haven for every port on your machine.**

See every app listening on a port: what it is, which project it belongs to, whether it answers, and who talks to whom.
Start whole stacks in dependency order, give each git branch its own port, and let your coding agent do the same,
without leaving servers behind.

[![CI](https://github.com/KirtiJha/porthaven/actions/workflows/ci.yml/badge.svg)](https://github.com/KirtiJha/porthaven/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-2dd4bf.svg)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-60a5fa.svg)
![macOS · Linux · Windows](https://img.shields.io/badge/runs%20on-macOS%20·%20Linux%20·%20Windows-a78bfa.svg)
![Zero dependencies](https://img.shields.io/badge/backend%20dependencies-0-34d399.svg)

<img src="docs/images/hero.jpg" alt="Porthaven landing page with a live preview of the dashboard" width="900" />

</div>

## Why

Every project brings a dev server, an API, a database and a watcher. They pile up on ports you never chose:

- `EADDRINUSE` on :5173, and then `lsof`, a pid and `ps` just to find out what holds it.
- Vite and Next quietly move to the next free port, so your bookmark now opens a different project.
- `kill <pid>` hits a child process, and `make dev` starts it again.
- A server bound to `0.0.0.0` is reachable from the café Wi-Fi. Last week's prototype is still holding 400 MB.
- Two branches, or two coding agents, both want :3000. The frontend has the API's port hard-coded.
- The API moved to :8001 this morning, but the frontend's `.env` still says :8000.
- Your coding agent's session ended an hour ago. The three dev servers it started are still running.

Porthaven turns that into one live, searchable dashboard, with a command line for when you are already in a terminal
and an MCP server for when your coding agent is the one starting servers.

## Quick start

You need Python 3.9 or newer. Node 20+ is needed only once, to build the UI.

**macOS / Linux**

```bash
git clone https://github.com/KirtiJha/porthaven.git && cd porthaven
make run          # builds the UI the first time, starts Porthaven, opens http://localhost:7475
make install      # optional: a `porthaven` command on your PATH (~/.local/bin)
```

**Windows (PowerShell)**

```powershell
git clone https://github.com/KirtiJha/porthaven.git; cd porthaven
cd web; npm install; npm run build; cd ..
bin\porthaven.cmd    # starts Porthaven and opens http://localhost:7475
```

The tour of every feature is at http://localhost:7475/welcome.

## Features

<img src="docs/images/features.jpg" alt="Porthaven features" width="900" />

### See
- **Live port map.** Every listening TCP port, refreshed every two seconds and grouped by project. Each row shows:
  - the framework (Vite, Next, Uvicorn, Django, Postgres…) and the page title;
  - HTTP status and response time, uptime, connections, and CPU and memory sparklines.
- **Network warnings** for anything reachable from other devices, with the Wi-Fi URL for phone testing.
- **Forgotten servers.** Dev servers with no connections and no CPU for hours are flagged, with the memory
  they hold.
- **Port map.** Every port on one line: neighbours together, saved apps that are not running, ports taken from a
  saved app, and the next free ports one click away.
- **Sort and scan.** Sort by port, name, response time, uptime, CPU or memory; a memory bar shows what holds the most.
- **Search, filters and pins.** Search on port, project, command and notes; `:51` finds ports starting with 51.
- **Docker-aware.** Published container ports show the container and image.

### Act
- **Stop the whole app, not just the pid.** Porthaven walks up from the port's process through launchers
  (`make`, `npm`, shells, reloaders) and stops the whole tree. It stops at your terminal, editor or agent.
- **Graceful first.** SIGTERM (or `taskkill`) first; force only after a grace period you choose.
- **Bulk stop** of several ports or apps, and a one-click clean-up of idle servers.
- **Changed your mind?** A server that stops stays in the list for a few seconds with a Restart button.
- **Guard rails.** No sudo, ever. Porthaven won't stop itself, other users' processes, or anything it doesn't show.
  System services and desktop apps need you to type the port number to confirm.

### Run
- **Saved apps.** Save a command, folder and port once, then start, stop and restart with one click.
  - Output is live and coloured, with clickable URLs and a jump to error lines.
  - Groups start and stop together, and crashed apps can restart automatically.
- **Port conflicts handled before they happen.** See who holds the port, then take the next free one
  (Porthaven sets `PORT` and fills `{port}` in the command) or take the port over.
- **Stable names.** `http://shop.localhost:7475` reaches the app on whatever port it is on today, websockets and
  hot reload included.
- **Outlives restarts.** Apps keep running when Porthaven stops or restarts, and Porthaven picks them up again.
- **Find projects.** Porthaven scans a folder for npm, pnpm and yarn scripts, Makefile targets, Django, FastAPI,
  Flask and Streamlit apps, and Compose files.
- **Sleep when quiet.** An app with no traffic for the time you choose is stopped to free its memory, and the next
  request to its stable name starts it again.
- **Workspaces.** Save what is running ("Shop, full stack"), then restore it later in one click, or switch to it and
  stop everything else.

### Stacks

<img src="docs/images/stacks.jpg" alt="A stack starting in dependency order" width="900" />

- **Dependencies.** "Storefront starts after Shop API": Porthaven starts the API first and waits for its health
  check (`/health`, or just the port) before starting what needs it. Cycles and missing apps are reported up front.
- **Apps find each other.** Write `{url:api}` or `{port:api}` in a command or environment variable, and Porthaven
  fills in the port the API is on today. Every app also gets `PORTHAVEN_<APP>_PORT` and `PORTHAVEN_<APP>_URL`.
- **`porthaven.toml`.** Commit the stack to the repo; whoever clones it runs `porthaven up`. Two apps from different
  folders that expect the same port are flagged before they collide.

```toml
group = "Shop"

[apps.api]
command = ".venv/bin/uvicorn main:app --reload --port {port}"
cwd = "backend"
port = 8000
health = "/health"

[apps.web]
name = "Storefront"
command = "npm run dev -- --port {port} --strictPort"
cwd = "frontend"
port = 5173
depends_on = ["api"]
env = { VITE_API_URL = "{url:api}" }
sleep_after = 60
```

- **Docker Compose services in a stack.** `compose = "postgres"` makes one service of the folder's compose file a
  member of the stack: Porthaven runs it with `docker compose up`, keeps its output, waits for its container's
  health check before starting what depends on it, and stops it with `docker compose stop`. Project discovery lists
  each compose service.

```toml
[apps.db]
compose = "postgres"          # a service of docker-compose.yml in this folder (or compose_file = "...")

[apps.api]
command = "uvicorn main:app --port {port}"
depends_on = ["db"]
env = { DATABASE_URL = "postgres://dev@localhost:{port:db}/shop" }
```

- **Git worktrees.** Run any saved app from another worktree of its repo. It gets its own port and its own address
  (`http://feature-x.api.localhost:7475`), so parallel branches, and parallel coding agents, stop fighting over one
  port. Cards show the branch each app runs from.

### For coding agents

<img src="docs/images/agents.jpg" alt="A coding agent using Porthaven's MCP tools" width="900" />

Porthaven includes an [MCP](https://modelcontextprotocol.io) server, so Claude Code, Cursor, Windsurf and other agents
can see ports, start stacks, read logs and free ports with the same guard rails you have.

```bash
claude mcp add porthaven -- porthaven mcp
```

For Cursor, Windsurf and other clients, add this to their MCP settings (Settings → Connect a coding agent shows the
full path for your machine):

```json
{ "mcpServers": { "porthaven": { "command": "porthaven", "args": ["mcp"] } } }
```

Tools: `list_ports`, `port_info`, `list_apps`, `start_app`, `stop_app`, `restart_app`, `app_logs`, `stop_port`,
`find_free_ports`, `stack_up`, `stack_down`, `run_in_worktree`, `recent_requests`, `recent_activity`,
`service_map`, `port_drift`, `port_history`, `search_logs`, `my_servers`, `stop_my_servers`. The agent starts
Porthaven if it isn't running, and its actions show in Activity as "by agent".

- **No servers left behind.** Porthaven notes which coding-agent session (Claude Code, Codex, Gemini CLI, Copilot
  CLI, Cursor Agent, Aider, opencode, Goose, Amp…) started each dev server, whether through MCP or the agent's own
  shell. When the session ends, its servers show under "Left by coding agents" with the memory they hold, and one
  click stops them. Settings can stop them on their own once nobody is connected. Agents can clean up after
  themselves with `my_servers` and `stop_my_servers`.

### Connect the dots

<img src="docs/images/map.jpg" alt="The service map: a storefront calling its API, the API holding a database connection" width="900" />

- **Service map.** Who talks to whom, drawn from the live TCP connections between your processes: browser →
  storefront → API → Postgres. Links carrying traffic animate; a link whose server went away turns red and stays on
  the map for half an hour, and a dependency you declared but that isn't running is marked as broken.
- **Port drift.** Porthaven reads the files where projects write down each other's addresses (`.env` files,
  vite/next/nuxt configs, proxy configs, compose files) and checks every `localhost:PORT` against what is running:
  "Storefront expects Shop API on :8000, but Shop API is on :8001". One click changes the line (only that line,
  keeping its line endings), or ignore it.
- **Port history.** Who held each port, and when, for 30 days: "what was on :3000 yesterday at 3 pm?" from the port's
  details, `porthaven history 3000 --at "yesterday 3pm"` or the `port_history` tool.
- **Trusted HTTPS for stable names.** `https://shop.localhost:7443/` with a lock in the browser, for OAuth callbacks,
  secure cookies and service workers. Porthaven makes a certificate authority on your machine (or uses mkcert's)
  and a certificate for each name on first use. `porthaven https setup`, then `porthaven https trust` once.
- **Share a port.** A link and QR code to open a dev server on your phone over Wi-Fi, or a public link through
  cloudflared or ngrok when one is installed. The app stays on 127.0.0.1: the link goes through a relay that only
  lets in visitors who have its secret, ends on its own after the time you choose, and refuses debuggers, notebooks
  and databases. A banner shows what is shared until it ends.

### Understand
- **Search every app's output.** One search box (text or regex) over the output of every saved app, newest first,
  with "errors only" and a list of the errors written in the last ten minutes, by app.
- **Activity timeline.** One lane per port, with markers for launches, crashes and conflicts, plus a
  weekday-by-hour heatmap and an event log.
- **Insights.** A week of history:
  - memory by project, and ports over time;
  - health (checks OK, average and p95 response time);
  - top-five lists, and suggestions with one-click fixes.
- **Request inspector.** Every request through an app's stable name is recorded: method, path, status, time and
  size, with its headers and the start of each body. Replay a request as it was, or edit the method, path, headers
  and body first; copy it as `curl`; export everything as a HAR file for the browser's dev tools.
- **Memory that keeps growing.** A dev server whose memory grew by 500 MB (you choose) and is still growing is
  flagged ("Storefront +640 MB in 2 h"), with a Restart button.
- **Exposure guard.** A Werkzeug debug console or Django debug pages reachable from the network are flagged as
  critical or high, with a notification and the fix.
- **Watch and notify.** A banner, a toast and a desktop notification when a watched port goes down.
- **Install as an app.** Porthaven installs as its own window with a dock badge (Settings → Install as an app).
- **In your editor and launcher.** [Extras](extras) include a VS Code / Cursor / Windsurf extension (ports in the
  status bar; open, stop, start apps), Raycast script commands, an Alfred script filter (`porthaven ls --alfred`) and
  a menu-bar plugin for SwiftBar, xbar and Argos.

### Keyboard

| Keys | Action | Keys | Action |
|---|---|---|---|
| `⌘K` / `Ctrl K` | Command palette (type a port number) | `o` | Open in browser |
| `/` | Search | `c` | Copy URL |
| `1`–`6` | Ports · Apps · Map · Logs · Activity · Insights | `p` / `w` | Pin / watch |
| `j` `k` | Move between rows | `x` / `⇧X` | Stop process / whole app |
| `Space` | Select for bulk stop | `?` | All shortcuts |

## Command line

```bash
porthaven                  # the dashboard (same as `porthaven serve`)
porthaven ls [--all]       # listening ports; --json for scripts
porthaven who 5173         # what is on a port: command, folder, app, HTTP answer
porthaven kill 5173 --app  # stop the whole app on a port (asks first; -y to skip)
porthaven free 3000 -n 5   # the next free ports
porthaven open 5173        # open in the browser
porthaven up               # start the apps in ./porthaven.toml, dependencies first
porthaven down             # stop them
porthaven init             # write a porthaven.toml from the saved apps in this folder
porthaven start shop       # start a saved app and its dependencies; `porthaven stop shop`
porthaven mcp              # MCP server (stdio) for coding agents
porthaven map              # which local services talk to which
porthaven drift [--fix]    # config files that point at a port the service has moved away from
porthaven history 3000 --at "yesterday 3pm"   # who held a port, and when
porthaven logs timeout --errors              # search every saved app's output
porthaven share 5173       # a link for your phone (--public through cloudflared or ngrok; --stop)
porthaven agents [--stop]  # servers coding agents started and left running
porthaven https setup      # trusted HTTPS for stable names; `trust`, `status`, `off`
porthaven service install  # start at login (launchd, systemd or Task Scheduler); uninstall / status
```

The commands that change things talk to the running dashboard and start it if needed.

## How it works

<img src="docs/images/architecture.jpg" alt="Porthaven architecture" width="900" />

```mermaid
flowchart LR
  OS["Sockets and processes<br/>lsof · ps (macOS, Linux)<br/>netstat · PowerShell (Windows)"] --> Scanner
  Scanner --> Classifier["Classifier<br/>project · framework · launcher"]
  Servers["Your servers"] -->|HTTP checks| Prober
  Classifier --> Engine
  Prober --> Engine["Engine<br/>events · idle · conflicts · guard rails"]
  Engine --> API["Local server<br/>JSON API · live stream"] --> UI["Dashboard & CLI"]
  Engine --> Proxy["Stable names<br/>app.localhost → port"]
  Engine <--> Supervisor["Supervisor<br/>saved apps · logs"]
  Engine <--> Store[("~/.porthaven<br/>apps · notes · history")]
```

A small local server reads the machine every two seconds (about 0.2 s of work on macOS). It works out what each
listening process is and which app launched it, asks each web server for its status and title, and streams the
picture to your browser. Everything is the Python standard library, plus the tools your OS already has.

## Security

- **Loopback only.** Porthaven listens on `127.0.0.1` and `::1`, never on your network.
- **DNS rebinding blocked.** It answers only requests addressed to its own `localhost` port.
- **Session token.** Every change needs a per-session token that only Porthaven's own page can read.
- **Same rules for agents.** The MCP server uses the same guard rails: it won't stop Porthaven itself, other users'
  processes, desktop apps or system services.
- **Shares are opt-in and short.** A shared link goes through a relay that needs the link's secret, ends on its own
  (8 hours at most) and never shares debuggers, notebooks, databases or debug pages. The app itself stays on
  127.0.0.1.
- **Your CA stays yours.** The HTTPS certificate authority's key is kept in `~/.porthaven/tls` (readable by you only)
  and is trusted only when you run `porthaven https trust`; certificates are issued only for `*.localhost` names.
- **No sudo, no telemetry.** State lives in `~/.porthaven` (move it with `PORTHAVEN_HOME`).

See [SECURITY.md](SECURITY.md) for how to report a vulnerability.

## Platform notes

| | macOS | Linux | Windows |
|---|---|---|---|
| Reads ports and processes with | `lsof`, `ps` | `/proc`, `ps` | `netstat`, PowerShell |
| Stops processes with | signals | signals | `taskkill` |
| Knows each process's folder | ✓ | ✓ | from its command line |
| Start at login | launchd | systemd user service | Task Scheduler |
| Trusting the HTTPS CA | login keychain | system store (sudo) and NSS | user certificate store |

## Contributing

Issues and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers setup, tests and the project layout.
`make test` runs the backend tests (a real server and a real app included) and the UI type check. CI runs them on
macOS, Linux and Windows.

## License

[MIT](LICENSE) © Kirti Nath Jha
