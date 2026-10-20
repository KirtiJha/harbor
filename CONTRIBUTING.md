# Contributing to Porthaven

Thanks for helping! Porthaven is small on purpose: a standard-library Python backend and a React UI. Changes that keep it
that way are the easiest to accept.

## Set up

```bash
git clone https://github.com/KirtiJha/porthaven.git && cd porthaven
make build              # installs the UI's packages and builds it (Node 20+)
bin/porthaven --no-open    # backend on http://localhost:7475
make dev                # UI with hot reload on http://localhost:7476 (proxies /api to :7475)
```

On Windows, use `bin\porthaven.cmd` and run `npm install && npm run build` inside `web\`.

## Before you open a pull request

- `make test`: backend tests (`python -m unittest`) and the UI type check. CI runs the backend tests on macOS,
  Linux and Windows with Python 3.9 and 3.13.
- Keep the backend dependency-free (Python 3.9+, standard library only). If a feature needs a package, open an
  issue first.
- Anything that reads the machine or stops processes goes through `porthaven/system.py`, which has one code path per
  operating system. Add a parser test with sample command output for any new platform code.
- Write user-facing text plainly: say what happened, why, and what to do next.
- Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:` …) and keep one concern
  per pull request.

## Project layout

| Path | What it is |
|---|---|
| `porthaven/system.py` | Reads ports and processes and stops them: lsof/ps on macOS, /proc/ps on Linux, netstat/PowerShell/taskkill on Windows |
| `porthaven/classify.py` | Works out each port's framework, project, kind, and the app that launched it |
| `porthaven/core.py` | Scan loop, live snapshot, actions and guard rails |
| `porthaven/control.py` | Stopping processes; running saved apps that outlive Porthaven |
| `porthaven/metrics.py` | The week of minute-by-minute history behind Activity and Insights |
| `porthaven/server.py` | Local HTTP server: JSON API, live event stream, stable-name proxy, static UI |
| `web/` | React + Tailwind dashboard, and the landing page in `web/public/welcome.*` |
| `tests/` | Unit tests on recorded command output, plus a real server and real app runs |

## Reporting bugs and security problems

Open an issue with the bug template. Report security problems privately, as described in [SECURITY.md](SECURITY.md).

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE) and that you will
follow the [Code of Conduct](CODE_OF_CONDUCT.md).
