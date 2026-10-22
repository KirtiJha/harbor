# Changelog

All notable changes to Porthaven are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Port map:** every port on one line above the table, with neighbours close together and big jumps broken. Saved
  apps that are not running hold a dashed place, a port another process took from a saved app is marked, and the
  next free ports near 3000, 5173 and 8000 are one click from the clipboard. Hovering a port highlights its row.
- **Sortable columns** in Ports: port, name, HTTP response time, uptime, CPU and memory.
- An **HTTP column** with each server's status and response time, and a memory bar that shows at a glance which
  server holds the most.
- A port that stops listening stays in the table for a few seconds as **stopped, with Restart**.
- Project headers show the folder, the memory the project holds, and buttons to open it in your editor or a
  terminal, or stop everything in it.
- The Ports table can be used from the keyboard with a screen reader (grid semantics, a focused row that follows
  `j`/`k`, `Home`/`End`), and adapts to narrow windows instead of scrolling sideways.

### Changed
- The process command, pid and launcher moved under each server's name; badges are ordered by importance and the
  rest fold into `+n`, so long names are no longer cut off.

### Fixed
- **Restart after stopping** a server (from the toast) ran nothing: Porthaven looked for the process it had just
  stopped. It now remembers stopped servers, including ones that stopped by themselves.
- Restarting or saving a server started with `npx` ran `npm exec vite --port 5174`, which hands `--port` to npm;
  it now runs `npm exec -- vite --port 5174`.
- **Linux:** for a moment after Porthaven launched an app, its own port (:7475) was reported as that app's, giving
  toasts like "Storefront is ready on :7475". A socket held by several processes (a just-forked child, or workers)
  now belongs to the topmost one, as on macOS.

## [2.0.0] - 2026-10-20

Harbor is now **Porthaven**, with a new logo.

### Changed
- **Renamed** to Porthaven: the command is `porthaven`, state lives in `~/.porthaven`, and the environment variables
  are `PORTHAVEN_HOME` and `PORTHAVEN_PORT`. State in `~/.harbor` moves over automatically on first start, and
  `HARBOR_HOME` still works.

### Added
- **Stacks:** apps can start after other apps and wait for their health check. `{url:api}` and `{port:api}` in a
  command or environment variable fill in another app's current port, and every app gets `PORTHAVEN_<APP>_PORT` and
  `PORTHAVEN_<APP>_URL`.
- **`porthaven.toml`:** a stack committed to the repo. `porthaven up`, `down`, `init`, `start` and `stop` on the
  command line; import and export in the dashboard; a warning when two apps expect the same port.
- **MCP server** (`porthaven mcp`) with 14 tools, so coding agents can list ports, start stacks, read logs, run a
  worktree and free ports, under the same guard rails. Their actions show as "by agent" in Activity.
- **Git worktrees:** run a saved app from another worktree on its own port and stable name; branch chips on apps
  and ports.
- **Sleep when quiet:** apps stop after a quiet period you choose and wake on the next request to their stable name.
- **Request inspector:** requests through stable names are recorded and shown per app.
- **Exposure guard:** Werkzeug debug consoles and Django debug pages reachable from the network are flagged, with a
  notification.
- **Workspaces:** save what is running and restore or switch to it later.
- **Install as an app** (PWA with a dock badge) and a menu-bar plugin for SwiftBar, xbar and Argos.
- Settings show how to connect Claude Code, Cursor, Windsurf and other MCP clients.

### Fixed
- Menus inside cards are no longer cut off.

## [1.1.1] - 2026-10-20

### Fixed
- **Linux:** ports are read from `/proc/net/tcp` and `/proc/<pid>` instead of `lsof`, which listed no sockets on
  some distributions.
- **Windows:** app output written with `\r\n` line endings no longer shows as empty lines.
- The server answers immediately and runs its first scan in the background, so a slow first scan can't time out
  the browser.

## [1.1.0] - 2026-10-20

### Added
- **Windows support** through netstat, PowerShell and taskkill, alongside macOS and Linux. CI covers all three.
- **Activity view:** a timeline with one lane per port, markers for launches, crashes and conflicts, events over
  time, a weekday-by-hour heatmap, and an event log grouped by day.
- **Insights view:** a week of history, with memory by project, ports over time, health (checks OK, average and p95
  response time), top-five lists, and suggestions with one-click fixes.
- **Start at login** on every platform: launchd (macOS), a systemd user service (Linux), Task Scheduler (Windows).
- Port conflicts are recorded as events.
- New landing page design.

### Fixed
- Apps started by Porthaven keep running when Porthaven stops or restarts, and Porthaven picks them up again.
- Porthaven answers on IPv6 loopback too, so `localhost` opens in every browser.

## [1.0.0] - 2026-10-20

### Added
- Live dashboard of every listening port, with project, framework, HTTP status, CPU, memory and connections.
- Stop a process or the whole app tree, with guard rails.
- Saved apps with captured logs, port-conflict handling, groups and auto-restart.
- Stable names (`<app>.localhost:7475`), forgotten-server detection, bulk stop, watch and notifications.
- Project discovery, export and import, command palette, CLI (`ls`, `who`, `kill`, `free`, `open`, `service`).
- Landing page at `/welcome`.

[Unreleased]: https://github.com/KirtiJha/porthaven/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/KirtiJha/porthaven/compare/v1.1.1...v2.0.0
[1.1.1]: https://github.com/KirtiJha/porthaven/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/KirtiJha/porthaven/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/KirtiJha/porthaven/releases/tag/v1.0.0
