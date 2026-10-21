"""Tests for the service map, port drift, port history, coding-agent sessions, memory trends, log search,
Docker Compose services, the request inspector's replay and export, shared links and HTTPS for stable names."""
import gzip
import http.client
import json
import os
import shutil
import socket
import ssl
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from porthaven import agents, compose, drift, history, leaks, logsearch, netmap, relay, share, system, teamfile, tls
from porthaven.core import Porthaven

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_porthaven as base  # noqa: E402
from test_porthaven import NO_PROXY, PS, SERVE, free_port  # noqa: E402

LSOF_EST = """p100
cnode
f20
n127.0.0.1:51000->127.0.0.1:8000
p200
cpython3
f7
n127.0.0.1:8000->127.0.0.1:51000
f8
n127.0.0.1:52000->127.0.0.1:5432
p300
cpostgres
f9
n127.0.0.1:5432->127.0.0.1:52000
"""


def row(pid, port, title, app=None, project=None, kind="dev", mem=100.0):
    return {"pid": pid, "port": port, "title": title, "kind": kind, "appId": app, "memMb": mem, "framework": None, "root": None,
            "project": {"name": project, "root": f"/code/{project}"} if project else None}


class Connections(unittest.TestCase):
    def test_both_ends_of_local_connections_are_read(self):
        links = system.parse_connections(LSOF_EST)
        self.assertEqual(len(links), 4)
        self.assertEqual(system.server_counts(links, [8000, 5432]), {8000: 1, 5432: 1})

    def test_windows_and_linux_connections(self):
        from test_porthaven import NETSTAT, PROC_TCP
        links = system.parse_netstat(NETSTAT)["links"]
        self.assertIn({"pid": 9000, "local": ("127.0.0.1", 51000), "remote": ("127.0.0.1", 5173)}, links)
        est = [r for r in system.parse_proc_net(PROC_TCP) if r["state"] == "01"]
        self.assertEqual(est[0]["remote"], ("127.0.0.1", 50000))


class ServiceMapTests(unittest.TestCase):
    procs = {100: {"pid": 100, "ppid": 1, "args": "node web.js"}, 200: {"pid": 200, "ppid": 1, "args": "python3 api.py"},
             300: {"pid": 300, "ppid": 1, "args": "postgres"},
             400: {"pid": 400, "ppid": 1, "args": "/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Helper"}}

    def test_who_talks_to_whom_and_broken_links(self):
        rows = [row(100, 3000, "Storefront", app="w"), row(200, 8000, "API", app="a"), row(300, 5432, "Postgres", kind="database")]
        links = system.parse_connections(LSOF_EST) + [{"pid": 400, "local": ("127.0.0.1", 53000), "remote": ("::1", 3000)}]
        apps = [{"id": "w", "name": "Storefront", "dependsOn": ["api"]}, {"id": "a", "name": "API", "slug": "api"}]
        m = netmap.ServiceMap()
        out = m.build(rows, self.procs, links, apps, set(), now=1000)
        pairs = {(e["from"], e["to"], e["state"]) for e in out["edges"]}
        self.assertIn(("app:w", "app:a", "active"), pairs)
        self.assertIn(("app:a", "cmd:Postgres", "active"), pairs)
        self.assertIn(("client:Google Chrome", "app:w", "active"), pairs)
        self.assertTrue(next(e for e in out["edges"] if e["from"] == "app:w")["declared"], "the dependency matches the traffic")
        # the API stops: its link from the storefront stays on the map, broken
        later = m.build([rows[0], rows[2]], self.procs, [], apps, set(), now=1060)
        broken = next(e for e in later["edges"] if e["from"] == "app:w" and e["to"] == "app:a")
        self.assertEqual(broken["state"], "broken")
        self.assertIn("BROKEN", netmap.ServiceMap.describe(later))
        # a dependency that is not running at all is broken from the start
        apps2 = apps + [{"id": "s", "name": "Search", "slug": "search"}]
        apps2[0] = {**apps2[0], "dependsOn": ["api", "search"]}
        fresh = netmap.ServiceMap().build(rows, self.procs, [], apps2, set(), now=1000)
        search = next(e for e in fresh["edges"] if e["to"] == "app:s")
        self.assertEqual((search["state"], search["declared"]), ("broken", True))
        # half an hour later it is forgotten
        gone = m.build([rows[0], rows[2]], self.procs, [], [], set(), now=1060 + netmap.KEEP + 1)
        self.assertFalse([e for e in gone["edges"] if e["to"] == "app:a"])


class History(unittest.TestCase):
    def test_intervals_survive_a_restart_and_answer_at(self):
        with tempfile.TemporaryDirectory() as d:
            h = history.PortHistory(Path(d))
            h.start(10, 3000, {"title": "old app"}, started=1000)
            h.end(10, 3000, ended=2000)
            h.start(11, 3000, {"title": "shop"}, started=3000)
            h.flush()                                   # Porthaven stops while shop still runs
            h2 = history.PortHistory(Path(d))
            h2.start(11, 3000, {"title": "shop"}, started=3000)   # and sees it again after it restarts
            rows = h2.query(3000)
            self.assertEqual([(r["title"], r["end"]) for r in rows], [("shop", None), ("old app", 2000)])
            self.assertEqual([r["title"] for r in h2.query(3000, at=1500)], ["old app"])
            self.assertEqual(h2.query(3001), [])

    def test_reading_moments(self):
        import datetime as dt
        now = dt.datetime(2026, 10, 21, 10, 0).timestamp()
        at = lambda s: dt.datetime.fromtimestamp(history.parse_when(s, now))
        self.assertEqual(at("2h ago"), dt.datetime(2026, 10, 21, 8, 0))
        self.assertEqual(at("yesterday 3pm"), dt.datetime(2026, 10, 20, 15, 0))
        self.assertEqual(at("15:00"), dt.datetime(2026, 10, 20, 15, 0), "a time later than now means yesterday")
        self.assertEqual(at("9:30"), dt.datetime(2026, 10, 21, 9, 30))
        self.assertEqual(at("2026-10-19 12:00"), dt.datetime(2026, 10, 19, 12, 0))
        self.assertEqual(at("monday 9am"), dt.datetime(2026, 10, 19, 9, 0))
        with self.assertRaisesRegex(ValueError, "yesterday 3pm"):
            history.parse_when("whenever", now)


class AgentSessions(unittest.TestCase):
    def test_agents_are_recognised(self):
        self.assertEqual(agents.agent_of("claude"), ("claude", "Claude Code"))
        self.assertEqual(agents.agent_of("node /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js"), ("claude", "Claude Code"))
        self.assertEqual(agents.agent_of("/opt/homebrew/bin/codex exec"), ("codex", "Codex"))
        self.assertEqual(agents.agent_of('"C:\\Program Files\\nodejs\\node.exe" C:\\npm\\node_modules\\@google\\gemini-cli\\dist\\index.js')[0], "gemini")
        self.assertIsNone(agents.agent_of("node /p/node_modules/.bin/vite"))
        self.assertIsNone(agents.agent_of("/Applications/Claude.app/Contents/MacOS/Claude"), "the desktop app is not a coding session")

    def test_a_server_started_by_an_agent_knows_its_session(self):
        procs = system.parse_ps(PS)
        sess = agents.find_session(402, procs, now=10_000)
        self.assertEqual((sess["agent"], sess["pid"]), ("claude", 999))
        self.assertIsNone(agents.find_session(203, procs, now=10_000), "a server started from a terminal has no agent")
        self.assertIsNone(agents.find_session(402, procs, now=10_000, stop_pids={400}),
                          "an app Porthaven launched is not the agent's, even when the agent started Porthaven")
        self.assertTrue(agents.alive(sess, procs, 10_000))
        del procs[999]
        self.assertFalse(agents.alive(sess, procs, 10_000))


class LaunchPorts(unittest.TestCase):
    def test_an_app_just_started_counts_on_its_launch_port(self):
        with tempfile.TemporaryDirectory() as d:
            from porthaven.store import Store
            h = Porthaven(Store(d), 1)

            class Run:
                port, alive = 8101, True
            h.managed["api"] = Run()
            h.snapshot = {"apps": [{"id": "db", "ports": [5434]}, {"id": "api", "ports": []}]}
            self.assertEqual(h.app_ports(), {"db": 5434, "api": 8101}, "the scan has not seen the API yet; {url:api} must not fall back to its saved port")


class SharedPort(unittest.TestCase):
    def test_two_servers_on_one_port_are_flagged_and_the_older_named(self):
        rows = [{"pid": 1, "port": 5173, "title": "web", "addresses": ["127.0.0.1"], "uptime": 180000, "id": "1:5173"},
                {"pid": 2, "port": 5173, "title": "web", "addresses": ["::1"], "uptime": 90000, "id": "2:5173"},
                {"pid": 3, "port": 8000, "title": "api", "addresses": ["127.0.0.1"], "uptime": 10, "id": "3:8000"}]
        Porthaven._mark_twins(rows)
        self.assertEqual((rows[0]["twins"]["older"], rows[1]["twins"]["older"]), (True, False))
        self.assertEqual(rows[0]["twins"]["others"][0]["addresses"], ["::1"])
        self.assertNotIn("twins", rows[2])


class MemoryTrend(unittest.TestCase):
    def series(self, f, minutes=120):
        return [(i * 60.0, f(i)) for i in range(minutes)]

    def test_steady_growth_is_flagged_and_a_plateau_is_not(self):
        found = leaks.trend(self.series(lambda i: 300 + i * 6), min_mb=500)
        self.assertTrue(found and found["growthMb"] >= 600 and found["perHour"] > 300, found)
        self.assertIsNone(leaks.trend(self.series(lambda i: 300 + min(i, 60) * 12), min_mb=500), "grew while warming up, then settled")
        self.assertIsNone(leaks.trend(self.series(lambda i: 300 + (i % 2) * 700), min_mb=500), "up and down is not a leak")
        self.assertIsNone(leaks.trend(self.series(lambda i: 300 + i * 6, minutes=20), min_mb=500), "too short to tell")
        self.assertIsNone(leaks.trend(self.series(lambda i: 300 + i * 6), min_mb=0), "0 turns the check off")


class LogSearch(unittest.TestCase):
    def test_errors_are_recognised(self):
        for line in ("TypeError: x is undefined", "Traceback (most recent call last):", "npm ERR! code ELIFECYCLE",
                     '127.0.0.1 - "GET /api HTTP/1.1" 500 12', "  GET /checkout 502 3.1 ms - 12"):
            self.assertTrue(logsearch.is_error(line), line)
        for line in ("compiled with 0 errors", "  GET / 200 3 ms", "ready in 312 ms", "registered errorHandler"):
            self.assertFalse(logsearch.is_error(line), line)

    def test_search_across_apps_newest_first(self):
        a, b = {"id": "a", "name": "API"}, {"id": "b", "name": "Web"}
        res = logsearch.search([(a, [{"seq": 1, "t": 10, "text": "GET /cart 200"}, {"seq": 2, "t": 30, "text": "\x1b[31mError: cart\x1b[0m"}]),
                                (b, [{"seq": 1, "t": 20, "text": "fetching /cart"}])], "cart")
        self.assertEqual([(m["app"], m["t"]) for m in res["matches"]], [("API", 30), ("Web", 20), ("API", 10)])
        self.assertEqual(res["matches"][0]["text"], "Error: cart", "colour codes are removed")
        self.assertEqual(logsearch.search([(a, [{"seq": 1, "t": 1, "text": "Error: x"}, {"seq": 2, "t": 2, "text": "ok"}])], "",
                                          errors_only=True)["total"], 1)
        with self.assertRaisesRegex(ValueError, "regular expression"):
            logsearch.search([], "(", regex=True)

    def test_log_files_are_dated_by_their_run(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "a.log")
            p.write_text("── 2026-10-21 09:00:00  $ npm run dev\nready\nError: boom\n", encoding="utf-8")
            lines = logsearch.file_lines(p)
            self.assertEqual(lines[2]["text"], "Error: boom")
            self.assertEqual(time.strftime("%H:%M", time.localtime(lines[2]["t"])), "09:00")


class Drift(unittest.TestCase):
    def test_a_config_file_pointing_at_a_moved_service(self):
        with tempfile.TemporaryDirectory() as d:
            web, api = Path(d, "web"), Path(d, "api")
            web.mkdir()
            api.mkdir()
            Path(web, ".env").write_bytes(b"# where the API is\r\nAPI_URL=http://localhost:8000/v1\r\nOTHER=1\r\n")
            Path(web, ".env.example").write_text("API_URL=http://localhost:9999\n")
            (web / "node_modules").mkdir()
            Path(web, "node_modules", "vite.config.js").write_text("proxy: 'http://localhost:7777'")
            Path(web, "vite.config.ts").write_text("export default { server: { proxy: { '/x': 'http://127.0.0.1:6543' } } }\n")
            apps = [{"id": "api", "name": "API", "cwd": str(api), "port": 8000}, {"id": "web", "name": "Storefront", "cwd": str(web), "port": 5173}]
            rows = [{"pid": 1, "port": 8001, "title": "API", "appId": "api", "project": None},
                    {"pid": 2, "port": 5173, "title": "Storefront", "appId": "web", "project": None}]
            projects = [{"root": str(web), "name": "Storefront", "appId": "web", "ports": [5173], "running": True}]
            found = drift.check(projects, apps, rows, [])
            warn = [f for f in found if f["level"] == "warn"]
            self.assertEqual(len(warn), 1, found)
            self.assertEqual((warn[0]["title"], warn[0]["fix"]), ("Storefront expects API on :8000, but API is on :8001", {"port": 8001}))
            self.assertTrue(any(f["port"] == 6543 and f["level"] == "info" for f in found), "nothing listens on :6543")
            self.assertFalse(any(f["port"] in (9999, 7777) for f in found), "examples and dependencies are not read")
            drift.apply_fix(warn[0]["file"], warn[0]["line"], warn[0]["match"], "localhost:8001")
            self.assertEqual(Path(web, ".env").read_bytes(), b"# where the API is\r\nAPI_URL=http://localhost:8001/v1\r\nOTHER=1\r\n")
            with self.assertRaisesRegex(ValueError, "no longer contains"):
                drift.apply_fix(warn[0]["file"], warn[0]["line"], warn[0]["match"], "localhost:8002")

    def test_a_project_that_moved_ports_is_found_from_history(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".env.local").write_text("SEARCH=http://localhost:7700\n")
            rows = [{"pid": 3, "port": 7701, "title": "meili", "appId": None, "project": {"name": "search", "root": "/elsewhere"}}]
            activity = [{"type": "opened", "port": 7700, "ts": time.time() - 3600, "project": "search", "title": "meili"}]
            found = drift.check([{"root": d, "name": "Shop", "ports": [], "running": True}], [], rows, activity)
            self.assertEqual(found[0]["fix"], {"port": 7701})


COMPOSE = """
services:
  db:
    image: postgres:16
    ports:
      - "127.0.0.1:5433:5432"
    healthcheck:
      test: ["CMD", "pg_isready"]
  cache:
    image: redis:7
    ports: ["6380:6379"]
  web:
    build: .
    ports:
      - target: 80
        published: "8088"
  worker:
    image: busybox
"""


class Compose(unittest.TestCase):
    def test_services_and_ports_without_docker(self):
        svcs = compose.parse(COMPOSE)
        self.assertEqual({k: v["ports"] for k, v in svcs.items()}, {"db": [5433], "cache": [6380], "web": [8088], "worker": []})
        self.assertTrue(svcs["db"]["healthcheck"])
        self.assertIsNone(compose.host_port("5432"))
        self.assertEqual(compose.host_port("8000-8001:8000-8001/tcp"), 8000)

    def test_containers_and_health(self):
        line = json.dumps({"ID": "abc", "Names": "shop-db-1", "Image": "postgres:16", "Status": "Up 4 seconds (health: starting)",
                           "Ports": "127.0.0.1:5433->5432/tcp", "Labels": "com.docker.compose.service=db,com.docker.compose.project.working_dir=/code/shop"})
        c = compose.parse_ps(line)[0]
        self.assertEqual((c["service"], c["workdir"], c["ports"][0]["host"]), ("db", "/code/shop", 5433))
        self.assertEqual(compose.health(c["status"]), "starting")
        self.assertEqual(compose.health("Up 2 minutes (healthy)"), "healthy")
        self.assertIsNone(compose.health("Up 2 minutes"))

    def test_a_compose_service_in_porthaven_toml(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "docker-compose.yml").write_text(COMPOSE)
            Path(d, "porthaven.toml").write_text('[apps.db]\ncompose = "db"\n\n[apps.api]\ncommand = "x"\ndepends_on = ["db"]\n')
            old = os.environ.get("PATH", "")
            os.environ["PATH"] = ""   # read the file itself, as on a machine without Docker
            try:
                apps = teamfile.load(Path(d, "porthaven.toml"))
            finally:
                os.environ["PATH"] = old
            db = apps[0]
            self.assertEqual((db["compose"], db["port"]), ({"service": "db", "file": "docker-compose.yml"}, 5433))
            self.assertEqual(db["command"], "docker compose -f docker-compose.yml up db")
            self.assertIn('compose = "db"', teamfile.dump(apps, d))


class Inspector(unittest.TestCase):
    def test_answers_are_read_back(self):
        body = gzip.compress(b'{"ok": true}')
        raw = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Encoding: gzip\r\nTransfer-Encoding: chunked\r\n\r\n"
               + hex(len(body))[2:].encode() + b"\r\n" + body + b"\r\n0\r\n\r\n")
        e = {"id": 1, "t": 1_700_000_000.5, "method": "POST", "path": "/api/cart?x=1", "status": 200, "ms": 12, "ttfb": 10, "bytes": len(raw),
             "ws": False, "port": 8000, "_reqHeaders": [["Host", "shop.localhost:7475"], ["Content-Type", "application/json"]],
             "_reqBody": b'{"id": 3}', "_resp": raw}
        d = relay.detail(e)
        self.assertEqual((d["responseBody"]["text"], d["requestBody"]["text"]), ('{"ok": true}', '{"id": 3}'))
        self.assertNotIn("_resp", relay.public(e))
        har = relay.har([e], "test")["log"]["entries"][0]
        self.assertEqual((har["request"]["url"], har["request"]["queryString"], har["response"]["content"]["text"]),
                         ("http://shop.localhost:7475/api/cart?x=1", [{"name": "x", "value": "1"}], '{"ok": true}'))
        self.assertEqual(har["request"]["postData"]["text"], '{"id": 3}')


class _Upstream:
    """A real app for relay tests: python's http.server on a free loopback port."""

    def __enter__(self):
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = f"hello {self.headers.get('Host')} {self.headers.get('Cookie') or '-'}".encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        s = socket.socket()
        s.settimeout(3)
        reach = s.connect_ex(("127.0.0.1", self.port))
        s.close()
        if reach and sys.platform == "darwin" and os.environ.get("CI"):
            self.srv.shutdown()
            raise unittest.SkipTest("loopback TCP is blocked on this macOS CI runner")
        return self

    def __exit__(self, *a):
        self.srv.shutdown()
        self.srv.server_close()


class Sharing(unittest.TestCase):
    def test_a_shared_link_needs_its_secret(self):
        with _Upstream() as up:
            s = share.Share(up.port, "Shop", "lan", 5, "127.0.0.1")
            try:
                get = lambda path, cookie=None: self._get(s.relay_port, path, cookie)
                self.assertEqual(get("/")[0], 403, "no secret, no entry")
                self.assertEqual(get("/?ph=wrong")[0], 403)
                status, headers, _ = get(f"/cart?ph={s.token}&x=1")
                self.assertEqual((status, headers.get("Location")), (302, "/cart?x=1"))
                cookie = headers.get("Set-Cookie").split(";")[0]
                status, _, body = get("/cart?x=1", cookie + "; theme=dark")
                self.assertEqual(status, 200)
                self.assertEqual(body, f"hello 127.0.0.1:{s.relay_port} theme=dark", "the share's cookie is not passed on")
                self.assertEqual(s.requests, 1)
            finally:
                s.close()
            time.sleep(0.6)
            self.assertTrue(s.ended)

    @staticmethod
    def _get(port, path, cookie=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", path, headers={"Cookie": cookie} if cookie else {})
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, dict(r.getheaders()), body


@unittest.skipUnless(tls.openssl(), "openssl is not installed")
class Https(unittest.TestCase):
    def test_a_certificate_per_name_from_the_local_ca(self):
        with tempfile.TemporaryDirectory() as d:
            auth = tls.Authority(Path(d), use_mkcert=False)
            ca = auth.ensure_ca()
            ctx = auth.server_context()
            with self.assertRaises(tls.TlsError):
                auth.leaf("evil.example.com")
            srv = socket.socket()
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            import threading

            def serve():
                conn, _ = srv.accept()
                try:
                    t = ctx.wrap_socket(conn, server_side=True)
                    t.sendall(b"ok")
                    t.close()
                except (ssl.SSLError, OSError):
                    pass
            threading.Thread(target=serve, daemon=True).start()
            client = ssl.create_default_context(cafile=str(ca))
            raw = socket.create_connection(("127.0.0.1", port), timeout=10)
            with client.wrap_socket(raw, server_hostname="shop.localhost") as c:
                names = [v for k, v in c.getpeercert()["subjectAltName"] if k == "DNS"]
                self.assertEqual(names, ["shop.localhost"])
                self.assertEqual(c.recv(2), b"ok")
            srv.close()
            self.assertTrue(Path(d, "tls", "hosts", "shop.localhost.pem").exists())


class FeaturesLive(base._Live):
    """Replay, HAR and HTTPS through Porthaven's real server, with a real app behind a stable name."""

    setUp = base.StackLive.setUp
    tearDown = base.StackLive.tearDown
    _wait = base.StackLive._wait
    _app = base.StackLive._app
    _up_or_skip = base.StackLive._up_or_skip

    def test_replay_export_and_https(self):
        Path(self.home.name, "serve.py").write_text(SERVE)
        port = free_port()
        _, app = self.call("POST", "/api/apps", {"name": "Echo", "slug": "echo", "cwd": self.home.name, "port": port,
                                                 "command": f'"{sys.executable}" -u serve.py {{port}}'})
        self.call("POST", f"/api/apps/{app['id']}/start", {})
        self._up_or_skip(lambda: self._app(app["id"])["ports"] == [port], "the app did not start")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/hello?x=1")
        req.add_header("Host", f"echo.localhost:{self.port}")
        with NO_PROXY.open(req, timeout=10) as r:
            self.assertEqual(r.status, 200)
        self.assertTrue(self._wait(lambda: self.get(f"/api/apps/{app['id']}/requests")["requests"], 5))
        rid = self.get(f"/api/apps/{app['id']}/requests")["requests"][-1]["id"]
        d = self.get(f"/api/apps/{app['id']}/requests/{rid}")
        self.assertIn(["Host", f"echo.localhost:{self.port}"], d["requestHeaders"])
        self.assertEqual(d["responseBody"]["text"], "ok -")
        status, rep = self.call("POST", f"/api/apps/{app['id']}/requests/{rid}/replay", {"path": "/again"})
        self.assertEqual((status, rep["status"], rep["path"], rep["replay"]), (200, 200, "/again", True), rep)
        har = self.get(f"/api/apps/{app['id']}/har")
        self.assertEqual([e["request"]["url"].split(str(self.port))[1] for e in har["log"]["entries"]], ["/hello?x=1", "/again"])
        # the same app over HTTPS, with a certificate for its name
        if not tls.openssl():
            self.call("POST", f"/api/apps/{app['id']}/stop", {})
            return
        self.h.tls = tls.Authority(self.home.name, use_mkcert=False)
        hport = free_port()
        status, res = self.call("POST", "/api/https/enable", {"port": hport})
        self.assertEqual((status, res["enabled"]), (200, True), res)
        ctx = ssl.create_default_context(cafile=res["status"]["ca"])
        c = http.client.HTTPSConnection("127.0.0.1", hport, context=ctx, timeout=15)
        c.sock = ctx.wrap_socket(socket.create_connection(("127.0.0.1", hport), timeout=15), server_hostname="echo.localhost")
        c.request("GET", "/secure", headers={"Host": f"echo.localhost:{hport}"})
        r = c.getresponse()
        self.assertEqual((r.status, r.read()), (200, b"ok -"))
        c.close()
        from porthaven import probe
        self.assertTrue(probe.probe(hport).get("tls"), "an HTTPS port must not be reported as down by the plain-HTTP health check")
        self.call("POST", "/api/https/disable", {})
        self.call("POST", f"/api/apps/{app['id']}/stop", {})


if __name__ == "__main__":
    unittest.main()
