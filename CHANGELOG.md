# Changelog

All notable changes to Harbor are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
- Apps started by Harbor keep running when Harbor stops or restarts, and Harbor picks them up again.
- Harbor answers on IPv6 loopback too, so `localhost` opens in every browser.

## [1.0.0] - 2026-10-20

### Added
- Live dashboard of every listening port, with project, framework, HTTP status, CPU, memory and connections.
- Stop a process or the whole app tree, with guard rails.
- Saved apps with captured logs, port-conflict handling, groups and auto-restart.
- Stable names (`<app>.localhost:7475`), forgotten-server detection, bulk stop, watch and notifications.
- Project discovery, export and import, command palette, CLI (`ls`, `who`, `kill`, `free`, `open`, `service`).
- Landing page at `/welcome`.
