# Contributing to Harbor

Thanks for helping! Harbor is small on purpose: a standard-library Python backend and a React UI. Changes that keep it
that way are the easiest to accept.

## Set up

```bash
git clone https://github.com/KirtiJha/harbor.git && cd harbor
make build              # installs the UI's packages and builds it (Node 20+)
bin/harbor --no-open    # backend on http://localhost:7475
make dev                # UI with hot reload on http://localhost:7476 (proxies /api to :7475)
```

On Windows, use `bin\harbor.cmd` and run `npm install && npm run build` inside `web\`.

## Before you open a pull request

- `make test`: backend tests (`python -m unittest`) and the UI type check. CI runs the backend tests on macOS,
  Linux and Windows with Python 3.9 and 3.13.
- Keep the backend dependency-free (Python 3.9+, standard library only). If a feature needs a package, open an
  issue first.
- Anything that reads the machine or stops processes goes through `harbor/system.py`, which has one code path per
  operating system. Add a parser test with sample command output for any new platform code.
- Write user-facing text plainly: say what happened, why, and what to do next.
- Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:` …) and keep one concern
  per pull request.

## Project layout

| Path | What it is |
|---|---|
| `harbor/system.py` | Reads ports and processes and stops them: lsof/ps on macOS, /proc/ps on Linux, netstat/PowerShell/taskkill on Windows |
| `harbor/classify.py` | Works out each port's framework, project, kind, and the app that launched it |
| `harbor/core.py` | Scan loop, live snapshot, actions and guard rails |
| `harbor/control.py` | Stopping processes; running saved apps that outlive Harbor |
| `harbor/metrics.py` | The week of minute-by-minute history behind Activity and Insights |
| `harbor/server.py` | Local HTTP server: JSON API, live event stream, stable-name proxy, static UI |
| `web/` | React + Tailwind dashboard, and the landing page in `web/public/welcome.*` |
| `tests/` | Unit tests on recorded command output, plus a real server and real app runs |

## Reporting bugs and security problems

Open an issue with the bug template. Report security problems privately, as described in [SECURITY.md](SECURITY.md).

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE) and that you will
follow the [Code of Conduct](CODE_OF_CONDUCT.md).
