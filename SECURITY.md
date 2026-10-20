# Security policy

Porthaven can stop processes on your machine, so its safety matters.

## How Porthaven protects you

- **Loopback only.** The server listens on `127.0.0.1` and `::1`, never on your network.
- **DNS rebinding blocked.** Requests must carry Porthaven's own `localhost` Host header.
- **Session token.** Every change needs a per-session token that only Porthaven's own page can read, so other
  websites cannot send it commands.
- **Guard rails.** Porthaven never uses sudo. It can't stop itself, other users' processes, or processes it doesn't
  show. Desktop apps and system services need you to type the port number to confirm.
- **Nothing leaves your machine.** No accounts, no telemetry. State lives in `~/.porthaven`.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through
[GitHub's private vulnerability reporting](https://github.com/KirtiJha/porthaven/security/advisories/new).

Include what an attacker could do, how to reproduce it, and the OS and version. You will get a reply within a week.
A fix and an advisory crediting you (if you wish) follow as soon as possible.

## Supported versions

Only the latest release on `main` receives security fixes.
