# Changelog

All notable changes to Porthaven are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/KirtiJha/porthaven/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/KirtiJha/porthaven/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/KirtiJha/porthaven/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/KirtiJha/porthaven/releases/tag/v1.0.0
