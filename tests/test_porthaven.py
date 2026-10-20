"""Porthaven tests: parsers and rules on recorded command output, plus the real server and a real app run
on this machine (a throwaway `python3 -m http.server` on a free port)."""
import faulthandler
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from porthaven import classify, probe, system
from porthaven.core import Porthaven, slugify
from porthaven.discover import discover
from porthaven.store import Store

LSOF_LISTEN = """p6072
cnode
u501
Ldev
f22
n127.0.0.1:5173
f23
n[::1]:5173
p923
crapportd
u501
Ldev
f10
n*:61038
"""

PS = """    1     0     1     0   0.0  12000 6-17:00:00 /sbin/launchd
  100     1   100   501   0.0   4000 01:00:00 /bin/zsh -l
  200   100   200   501   0.0   3000    10:00 make dev
  201   200   200   501   0.0   2000    10:00 /bin/sh -c npm run dev
  202   201   200   501   0.0  50000    10:00 npm run dev
  203   202   200   501   1.5 120000    09:59 node /p/node_modules/.bin/vite
  300     1   300   501   0.1  60000 01-02:03:04 uvicorn app:app --reload --port 8000
  301   300   300   501   0.2  40000    05:00 /usr/bin/python3 -c from multiprocessing.spawn import spawn_main
  400   999   400   501   0.0   1000    01:00 /bin/zsh -c eval 'make dev'
  401   400   400   501   0.0   1000    01:00 make dev
  402   401   400   501   0.0   1000    01:00 node vite
  999     1   999   501   0.0   1000    01:00 claude
"""


class Parsing(unittest.TestCase):
    def test_listeners_merge_ipv4_and_ipv6_of_one_process(self):
        rows = system.parse_listeners(LSOF_LISTEN)
        self.assertEqual(rows[(6072, 5173)]["addresses"], ["127.0.0.1", "::1"])
        self.assertEqual(rows[(923, 61038)]["addresses"], ["*"])

    def test_elapsed_time_formats(self):
        self.assertEqual(system.parse_etime("05:00"), 300)
        self.assertEqual(system.parse_etime("01:00:00"), 3600)
        self.assertEqual(system.parse_etime("01-02:03:04"), 93784)

    def test_ps_lines(self):
        procs = system.parse_ps(PS)
        self.assertEqual(procs[203]["args"], "node /p/node_modules/.bin/vite")
        self.assertEqual(procs[300]["elapsed"], 93784)

    def test_established_counts_only_the_server_side(self):
        text = "p1\nf3\nn127.0.0.1:5173->127.0.0.1:50000\np2\nf4\nn127.0.0.1:50000->127.0.0.1:5173\n"
        self.assertEqual(system.parse_established(text, {5173}), {5173: 1})


NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1012
  TCP    127.0.0.1:5173         0.0.0.0:0              LISTENING       6072
  TCP    127.0.0.1:5173         127.0.0.1:51000        ESTABLISHED     6072
  TCP    127.0.0.1:51000        127.0.0.1:5173         ESTABLISHED     9000
  TCP    [::1]:5173             [::]:0                 LISTENING       6072
  TCP    [::]:445               [::]:0                 ABHÖREN         4
  UDP    0.0.0.0:5353           *:*                                    2200
"""

CIM = json.dumps([
    {"ProcessId": 6072, "ParentProcessId": 5000, "SessionId": 1, "Name": "node.exe",
     "CommandLine": '"C:\\Program Files\\nodejs\\node.exe" C:\\dev\\shop\\node_modules\\vite\\bin\\vite.js',
     "WorkingSetSize": 104857600, "KernelModeTime": 10_000_000, "UserModeTime": 10_000_000, "Created": 1_000},
    {"ProcessId": 1012, "ParentProcessId": 4, "SessionId": 0, "Name": "svchost.exe", "CommandLine": None,
     "WorkingSetSize": 2048, "KernelModeTime": 0, "UserModeTime": 0, "Created": 0},
])


PROC_TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1001        0 41234 1 0000000000000000 100 0 0 10 0
   1: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1111 1 0000000000000000 100 0 0 10 0
   2: 0100007F:1F90 0100007F:C350 01 00000000:00000000 00:00000000 00000000  1001        0 41299 1 0000000000000000 20 4 30 10 -1
"""
PROC_TCP6 = """  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000000000000000000001000000:1F90 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000  1001        0 41235 1 0000000000000000 100 0 0 10 0
"""


class Linux(unittest.TestCase):
    def test_proc_net_tcp(self):
        rows = system.parse_proc_net(PROC_TCP) + system.parse_proc_net(PROC_TCP6)
        listen = [(r["host"], r["port"], r["uid"]) for r in rows if r["state"] == "0A"]
        self.assertEqual(listen, [("127.0.0.1", 8080, 1001), ("0.0.0.0", 22, 0), ("::1", 8080, 1001)])
        self.assertEqual([(r["port"], r["inode"]) for r in rows if r["state"] == "01"], [(8080, 41299)])


class Windows(unittest.TestCase):
    """The Windows backend's parsers, on sample output, so they are tested on every OS."""

    def test_netstat_listeners_and_connections(self):
        out = system.parse_netstat(NETSTAT)
        self.assertEqual(out["listen"][(6072, 5173)]["addresses"], ["127.0.0.1", "::1"])
        self.assertEqual(out["listen"][(1012, 135)]["addresses"], ["*"])
        self.assertIn((4, 445), out["listen"], "a localised state name must still count as listening")
        self.assertEqual(out["established"], {5173: 1, 51000: 1})
        self.assertNotIn(5353, [p for (_, p) in out["listen"]], "UDP is not a listener")

    def test_process_table_and_cpu(self):
        state = {}
        first = system.parse_cim(CIM, state, now=1_100)
        node = first[6072]
        self.assertEqual((node["ppid"], node["uid"], node["rss_kb"], node["elapsed"]), (5000, 1, 102400, 100))
        later = json.loads(CIM)
        later[0]["UserModeTime"] += 5_000_000          # half a second of CPU in one second
        self.assertEqual(system.parse_cim(json.dumps(later), state, now=1_101)[6072]["cpu"], 50.0)
        self.assertEqual(system.parse_cim("not json"), {})

    def test_command_lines(self):
        args = '"C:\\Program Files\\nodejs\\node.exe" C:\\dev\\shop\\node_modules\\vite\\bin\\vite.js --port 5173'
        self.assertEqual(classify.base(args), "node")
        self.assertEqual(classify.framework(args)["id"], "vite")
        self.assertEqual(classify.dir_from_args(args), "C:\\dev\\shop")
        self.assertEqual(classify.kind_of("node.exe", args, 1, 1, classify.framework(args)), "dev")
        self.assertTrue(classify.is_shell_command("C:\\Windows\\system32\\cmd.exe /d /s /c npm run dev"))
        self.assertTrue(classify.is_interactive_shell("C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"))
        code = '"C:\\Users\\k\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe" --type=utility'
        self.assertEqual(classify.kind_of("Code.exe", code, 1, 1, classify.framework(code)), "app")
        self.assertEqual(classify.kind_of("svchost.exe", "svchost.exe -k netsvcs", 0, 1, None), "system")


class Rules(unittest.TestCase):
    procs = system.parse_ps(PS)

    def test_app_root_climbs_launchers_but_stops_at_the_interactive_shell(self):
        self.assertEqual(classify.app_root(203, self.procs, 501), 200)   # make dev, not zsh -l

    def test_app_root_ignores_an_agent_or_editor_wrapper_shell(self):
        self.assertEqual(classify.app_root(402, self.procs, 501), 401)   # make dev, not claude's `zsh -c`

    def test_descendants(self):
        self.assertEqual(sorted(classify.descendants(200, self.procs)), [201, 202, 203])

    def test_frameworks_and_kinds(self):
        self.assertEqual(classify.framework("node /x/node_modules/.bin/vite")["id"], "vite")
        self.assertEqual(classify.framework("uvicorn app:app --reload")["id"], "uvicorn")
        self.assertEqual(classify.framework("/opt/homebrew/bin/postgres -D x")["kind"], "database")
        vscode = "/Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper (Plugin).app/Contents/MacOS/Code Helper (Plugin) --inspect"
        self.assertEqual(classify.kind_of("Code\\x20H", vscode, 501, 501, classify.framework(vscode)), "app")
        python_app = "/opt/homebrew/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python .venv/bin/uvicorn a:b"
        self.assertEqual(classify.kind_of("Python", python_app, 501, 501, classify.framework(python_app)), "dev")
        self.assertEqual(classify.kind_of("rapportd", "/usr/libexec/rapportd", 501, 501, None), "system")

    def test_readable_command(self):
        self.assertEqual(classify.display_command("node /a/b/node_modules/.bin/vite --port 1"), "node vite --port 1")

    def test_workers_sharing_a_socket_become_one_row(self):
        rows = [{"port": 8000, "pid": 300, "cpu": 0.1, "memMb": 58.6, "connections": 0, "display": "uvicorn"},
                {"port": 8000, "pid": 301, "cpu": 0.2, "memMb": 39.1, "connections": 2, "display": "python"}]
        out = Porthaven._merge_workers(rows, self.procs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["pid"], 300)
        self.assertEqual(out[0]["workers"][0]["pid"], 301)
        self.assertEqual(out[0]["connections"], 2)


class NewRules(unittest.TestCase):
    def test_slugs_are_url_safe_and_unique(self):
        self.assertEqual(slugify("Shop web!"), "shop-web")
        with tempfile.TemporaryDirectory() as d:
            h = Porthaven(Store(d))
            a = h.store.upsert_app({"name": "Web", "cwd": d, "command": "x"})
            b = h.store.upsert_app({"name": "web", "cwd": d, "command": "y"})
            c = h.store.upsert_app({"name": "API", "cwd": d, "command": "z", "slug": "api"})
            self.assertEqual(h.app_slugs(), {a["id"]: "web", b["id"]: "web-2", c["id"]: "api"})

    def test_idle_needs_hours_without_connections_or_cpu(self):
        with tempfile.TemporaryDirectory() as d:
            h = Porthaven(Store(d))
            now, four_hours = time.time(), 4 * 3600
            old = {"cpu": 0.0, "elapsed": 2 * 86400}
            self.assertGreater(h._idle_for(5173, "dev", old, 0, now, four_hours), four_hours)
            self.assertIsNone(h._idle_for(5173, "dev", old, 1, now, four_hours), "an open connection means in use")
            self.assertIsNone(h._idle_for(5173, "dev", {"cpu": 5.0, "elapsed": 2 * 86400}, 0, now, four_hours))
            self.assertIsNone(h._idle_for(5432, "database", old, 0, now, four_hours), "databases are never idle")
            h.last_active[5173] = now - 60
            self.assertIsNone(h._idle_for(5173, "dev", old, 0, now, four_hours), "used a minute ago")


class SurvivesRestart(unittest.TestCase):
    def test_an_app_keeps_running_and_is_picked_up_by_the_next_porthaven(self):
        # Not TemporaryDirectory(): on Windows the stopped app's log may still be open for a moment, and a failed
        # cleanup would fail a test whose checks all passed.
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        if True:
            port = free_port()
            first = Porthaven(Store(d))
            app = first.store.upsert_app({"name": "demo", "cwd": d, "command": f"{sys.executable} -u -m http.server {port} --bind 127.0.0.1"})
            first.refresh(initial=True)
            first._publish()
            first.start_app(app["id"])
            for _ in range(50):
                if not probe.port_free(port):
                    break
                time.sleep(0.1)
            pid = first.managed[app["id"]].pid
            first.stop()                                 # Porthaven stops; the app must not
            self.assertTrue(system.is_alive(pid))
            self.assertFalse(probe.port_free(port), "the app stopped when Porthaven stopped")
            second = Porthaven(Store(d))
            second.managed.update(__import__("porthaven.control", fromlist=["Managed"]).Managed.adopt_all(second.store, second._on_exit))
            self.assertIn(app["id"], second.managed, "the next Porthaven did not pick the app up")
            m = second.managed[app["id"]]
            self.assertEqual((m.pid, m.status), (pid, "running"))
            m.stop(grace=2)
            for _ in range(40):
                if m.status == "stopped":
                    break
                time.sleep(0.1)
            self.assertEqual(m.status, "stopped")
            self.assertFalse((Path(d) / "run" / f"{app['id']}.json").exists())


class Discovery(unittest.TestCase):
    def test_finds_npm_scripts_make_targets_and_python_apps(self):
        with tempfile.TemporaryDirectory() as d:
            web = Path(d, "web")
            web.mkdir()
            (web / "package.json").write_text(json.dumps({"name": "web", "scripts": {"dev": "vite --port 5180"}}))
            (web / "pnpm-lock.yaml").write_text("")
            api = Path(d, "api")
            api.mkdir()
            (api / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
            Path(d, "Makefile").write_text("dev:\n\tuvicorn api.main:app --port 8001\n")
            items = {(i["rel"], i["command"]): i for i in discover(d, 2)["items"]}
            self.assertEqual(items[("web", "pnpm run dev")]["port"], 5180)
            self.assertEqual(items[(".", "make dev")]["port"], 8001)
            self.assertIn(("api", "uvicorn main:app --reload --port {port}"), items)


class Ports(unittest.TestCase):
    def test_free_port_finder_skips_a_listening_port(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        try:
            self.assertFalse(probe.port_free(port))
            self.assertNotIn(port, probe.free_ports(port, 2))
        finally:
            s.close()


# Talk to the test server directly: urllib otherwise applies the OS proxy settings, even to 127.0.0.1 on macOS.
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port():
    return probe.free_ports(47000, 1)[0]


class _Live(unittest.TestCase):
    """Porthaven's real HTTP server on a free port, with its state in a temporary folder."""

    @classmethod
    def setUpClass(cls):
        from porthaven.server import serve
        cls.home = tempfile.TemporaryDirectory()
        cls.port = free_port()
        cls.h = Porthaven(Store(cls.home.name), cls.port)
        cls.crash = []

        def run():
            try:
                serve(cls.h, cls.port)
            except Exception as err:   # surface a server that died, instead of a client timeout
                cls.crash.append(repr(err))
        threading.Thread(target=run, daemon=True).start()
        for _ in range(50):
            if not probe.port_free(cls.port):
                break
            time.sleep(0.1)
        probe_sock = socket.socket()
        probe_sock.settimeout(3)
        reach = probe_sock.connect_ex(("127.0.0.1", cls.port))
        probe_sock.close()
        if reach != 0:
            if sys.platform == "darwin" and os.environ.get("CI") and not cls.crash:
                # GitHub's macOS runners block loopback TCP for Python: a plain `python -m http.server` is unreachable
                # there too (see the CI diagnostics step). These tests run on Linux and Windows CI and on real Macs.
                cls.tearDownClass()
                raise unittest.SkipTest(f"loopback TCP is blocked on this macOS CI runner (connect_ex={reach})")
            raise AssertionError(f"test server on 127.0.0.1:{cls.port} unreachable (connect_ex={reach}); server error: {cls.crash}")
        cls.token = cls.get("/api/session")["token"]
        for _ in range(100):   # the first scan runs in the background
            if cls.h.snapshot:
                break
            time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.h.shutdown_apps()
        cls.h.stop()
        cls.home.cleanup()

    @classmethod
    def call(cls, method, path, body=None, host=None, token=True):
        req = urllib.request.Request(f"http://127.0.0.1:{cls.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Host", host or f"127.0.0.1:{cls.port}")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if token and method != "GET":
            req.add_header("X-Porthaven-Token", cls.token)
        try:
            with NO_PROXY.open(req, timeout=15) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read() or b"{}")

    @classmethod
    def get(cls, path):
        return cls.call("GET", path)[1]


class LiveServer(_Live):
    def test_sees_itself_and_will_not_stop_itself(self):
        snap = self.get("/api/state")
        self.h.refresh()
        snap = self.get("/api/state")
        me = [r for r in snap["listeners"] if r["port"] == self.port]
        self.assertTrue(me, f"Porthaven's own port {self.port} is missing. Scan error: {snap['error']}; "
                            f"ports seen: {sorted({r['port'] for r in snap['listeners']})}")
        self.assertEqual(me[0]["risk"], "self")
        status, body = self.call("POST", "/api/kill", {"pid": os.getpid(), "mode": "process"})
        self.assertEqual(status, 403, body)

    def test_import_skips_duplicates_and_incomplete_apps(self):
        apps = [{"name": "one", "cwd": self.home.name, "command": "echo 1"}, {"name": "no command", "cwd": self.home.name}]
        status, r = self.call("POST", "/api/apps/import", {"apps": apps})
        self.assertEqual((status, r["added"]), (200, ["one"]))
        status, r = self.call("POST", "/api/apps/import", {"apps": apps[:1]})
        self.assertEqual((r["added"], r["skipped"][0]["why"]), ([], "already saved"))
        exported = self.get("/api/apps/export")["apps"]
        self.assertIn("one", [a["name"] for a in exported])

    def test_rejects_requests_for_another_host_name(self):
        status, _ = self.call("GET", "/api/state", host="evil.example:80")
        self.assertEqual(status, 403)

    def test_changes_need_the_session_token(self):
        status, _ = self.call("PUT", "/api/ports/5999", {"note": "x"}, token=False)
        self.assertEqual(status, 403)
        status, meta = self.call("PUT", "/api/ports/5999", {"note": "x"})
        self.assertEqual((status, meta), (200, {"note": "x"}))

    def test_a_saved_app_starts_logs_moves_off_a_taken_port_and_stops(self):
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        taken = blocker.getsockname()[1]
        try:
            status, app = self.call("POST", "/api/apps", {"name": "demo", "cwd": self.home.name, "port": taken,
                                                          "command": f"{sys.executable} -u -m http.server {{port}} --bind 127.0.0.1"})
            self.assertEqual(status, 200, app)
            status, err = self.call("POST", f"/api/apps/{app['id']}/start", {})
            self.assertEqual(status, 409, err)
            alt = err["conflict"]["suggest"]
            self.assertTrue(alt and alt != taken)
            status, run = self.call("POST", f"/api/apps/{app['id']}/start", {"port": alt, "force": True})
            self.assertEqual(status, 200, run)
            for _ in range(60):
                self.h.refresh()
                st = next(a for a in self.get("/api/state")["apps"] if a["id"] == app["id"])
                if st["state"] == "running":
                    break
                time.sleep(0.2)
            self.assertEqual(st["state"], "running", f"{st}; scan error: {self.h.error}; ports seen: {sorted(p for (_, p) in self.h.listeners)}")
            self.assertEqual(st["ports"], [alt])
            self.assertTrue(st["drift"], "running off its saved port should be flagged")
            # the stable name reaches the app on whichever port it is on
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/")
            req.add_header("Host", f"demo.localhost:{self.port}")
            with NO_PROXY.open(req, timeout=10) as r:
                self.assertIn(b"Directory listing", r.read(), "demo.localhost did not reach the app")
            for _ in range(30):   # Porthaven follows the log file a few times a second
                logs = self.get(f"/api/apps/{app['id']}/logs")
                if any("Serving HTTP" in ln["text"] for ln in logs["lines"]):
                    break
                time.sleep(0.2)
            self.assertTrue(any("Serving HTTP" in ln["text"] for ln in logs["lines"]), logs)
            status, _ = self.call("POST", f"/api/apps/{app['id']}/stop", {})
            self.assertEqual(status, 200)
            for _ in range(30):
                if probe.port_free(alt):
                    break
                time.sleep(0.1)
            self.assertTrue(probe.port_free(alt), "the app's port is still taken after stopping it")
            time.sleep(0.3)
            st = next(a for a in self.get("/api/state")["apps"] if a["id"] == app["id"])
            self.assertEqual(st["run"]["status"], "stopped", "a stop from Porthaven must not be reported as a crash")
        finally:
            blocker.close()


if __name__ == "__main__":
    unittest.main()


class ProbeIPv6(unittest.TestCase):
    def test_a_server_listening_only_on_ipv6_loopback_is_checked_over_ipv6(self):
        import http.server
        if not socket.has_ipv6:
            self.skipTest("no IPv6")

        class V6(http.server.ThreadingHTTPServer):
            address_family = socket.AF_INET6

        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<title>Only on ::1</title>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        try:
            srv = V6(("::1", 0), Page)
        except OSError:
            self.skipTest("cannot bind ::1")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            r = probe.probe(srv.server_address[1], timeout=3)
            if not r.get("ok") and sys.platform == "darwin" and os.environ.get("CI"):
                self.skipTest("loopback TCP is blocked on this macOS CI runner")
            self.assertEqual((r.get("status"), r.get("title")), (200, "Only on ::1"), r)
        finally:
            srv.shutdown()
            srv.server_close()


# ---------------------------------------------------------------- Porthaven 1.2 features

from porthaven import gitinfo, mcp, stacks, teamfile  # noqa: E402


class Stacks(unittest.TestCase):
    apps = [{"id": "a", "name": "API", "dependsOn": ["db"]}, {"id": "w", "name": "Web", "dependsOn": ["api"]},
            {"id": "d", "name": "DB"}]
    slugs = {"a": "api", "w": "web", "d": "db"}

    def test_dependencies_start_first(self):
        self.assertEqual([a["id"] for a in stacks.start_order(self.apps, self.slugs, ["w"])], ["d", "a", "w"])

    def test_cycles_and_unknown_names_are_explained(self):
        loop = [{"id": "x", "name": "X", "dependsOn": ["y"]}, {"id": "y", "name": "Y", "dependsOn": ["x"]}]
        with self.assertRaisesRegex(stacks.StackError, "circle"):
            stacks.start_order(loop, {"x": "x", "y": "y"}, ["x"])
        with self.assertRaisesRegex(stacks.StackError, "no saved app"):
            stacks.start_order([{"id": "x", "name": "X", "dependsOn": ["ghost"]}], {"x": "x"}, ["x"])

    def test_placeholders_and_sibling_variables(self):
        wired = stacks.wiring(self.apps, self.slugs, {"a": 8001, "d": 5432})
        self.assertEqual(stacks.expand("--port {port} --api {url:api} --db {port:db} {url:nope}", 3000, wired),
                         "--port 3000 --api http://localhost:8001 --db 5432 {url:nope}")
        self.assertEqual(stacks.env_for(wired)["PORTHAVEN_API_URL"], "http://localhost:8001")


TOML = """
# the shop
group = "Shop"

[apps.api]
command = "uvicorn main:app --port {port}"   # comment after a value
cwd = "."
port = 8_001
health = "/health"

[apps.web]
name = 'Storefront'
command = "npm run dev -- --port {port}"
port = 5173
depends_on = ["api"]
env = { API_URL = "{url:api}", DEBUG = "1" }
sleep_after = 30
"""


class Teamfile(unittest.TestCase):
    def test_reads_porthaven_toml_without_tomllib(self):
        doc = teamfile._mini_toml(TOML)
        self.assertEqual(doc["group"], "Shop")
        self.assertEqual(doc["apps"]["api"]["port"], 8001)
        self.assertEqual(doc["apps"]["web"]["env"], {"API_URL": "{url:api}", "DEBUG": "1"})
        self.assertEqual(doc["apps"]["web"]["depends_on"], ["api"])

    def test_load_dump_and_claims(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "porthaven.toml").write_text(TOML)
            apps = teamfile.load(teamfile.find(d))
            web = next(a for a in apps if a["slug"] == "web")
            self.assertEqual((web["name"], web["sleepAfter"], web["group"], web["dependsOn"]), ("Storefront", 30, "Shop", ["api"]))
            again = teamfile._mini_toml(teamfile.dump(apps, d))
            self.assertEqual(again["apps"]["web"]["depends_on"], ["api"])
            other = {"name": "Other", "cwd": tempfile.gettempdir(), "port": 5173}
            self.assertEqual(teamfile.port_claims(apps + [other]), {5173: ["Storefront", "Other"]})

    def test_mistakes_are_reported(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "porthaven.toml").write_text("[apps.x]\ncommand = \"a\"\nwhat = 1\n")
            with self.assertRaisesRegex(teamfile.TeamfileError, "unknown setting"):
                teamfile.load(Path(d, "porthaven.toml"))


@unittest.skipUnless(__import__("shutil").which("git"), "git is not installed")
class Worktrees(unittest.TestCase):
    def test_branch_and_worktree_are_detected(self):
        import subprocess as sp
        with tempfile.TemporaryDirectory() as d:
            repo, tree = Path(d, "repo"), Path(d, "repo-feature")
            repo.mkdir()
            git = lambda *a, cwd=repo: sp.run(["git", *a], cwd=cwd, check=True, capture_output=True)
            git("init", "-q", "-b", "main")
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x")
            git("worktree", "add", "-q", "-b", "feature/checkout", str(tree))
            self.assertEqual(gitinfo.info(str(repo))["branch"], "main")
            wt = gitinfo.info(str(tree))
            self.assertEqual((wt["branch"], wt["worktree"], wt["repo"]), ("feature/checkout", True, "repo"))
            self.assertEqual({t["branch"] for t in gitinfo.worktrees(repo)}, {"main", "feature/checkout"})


class Exposure(unittest.TestCase):
    def test_dangerous_things_on_the_network_are_flagged(self):
        net = {"exposure": "network", "port": 9229}
        self.assertEqual(Porthaven.exposure_risk(net, "node --inspect=0.0.0.0:9229 app.js", None, "dev", None)["level"], "critical")
        pg = classify.framework("/opt/homebrew/bin/postgres -D x")
        self.assertEqual(Porthaven.exposure_risk({"exposure": "network", "port": 5432}, "postgres", pg, "database", None)["level"], "high")
        self.assertEqual(Porthaven.exposure_risk({"exposure": "network", "port": 5000}, "flask run", None, "dev",
                                                 {"flags": ["werkzeug-debugger"]})["level"], "critical")
        self.assertIsNone(Porthaven.exposure_risk({"exposure": "local", "port": 9229}, "node --inspect app.js", None, "dev", None))


class Mcp(unittest.TestCase):
    def test_protocol(self):
        class Fake:
            def call(self, name, args):
                if name == "find_free_ports":
                    return "3001 3002"
                raise mcp.ClientError("Porthaven is not running")
        init = mcp.handle(Fake(), {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual((init["result"]["protocolVersion"], init["result"]["serverInfo"]["name"]), ("2025-06-18", "porthaven"))
        self.assertIsNone(mcp.handle(Fake(), {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        names = {t["name"] for t in mcp.handle(Fake(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertTrue({"list_ports", "start_app", "app_logs", "stop_port", "run_in_worktree"} <= names)
        ok = mcp.handle(Fake(), {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "find_free_ports", "arguments": {}}})
        self.assertEqual(ok["result"]["content"][0]["text"], "3001 3002")
        err = mcp.handle(Fake(), {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "list_ports", "arguments": {}}})
        self.assertTrue(err["result"]["isError"])
        self.assertEqual(mcp.handle(Fake(), {"jsonrpc": "2.0", "id": 5, "method": "nope"})["error"]["code"], -32601)


SERVE = """import http.server, os, sys
port = int(sys.argv[1])
body = ("ok " + os.environ.get("UPSTREAM", "-")).encode()
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
print("serving", port, os.environ.get("UPSTREAM", "-"), flush=True)
http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
"""


class StackLive(_Live):
    """Stacks, the request inspector, sleep and wake, porthaven.toml and workspaces on a real server."""

    def setUp(self):
        # A hang here should print every thread's stack and end the run, not stall CI for hours.
        faulthandler.dump_traceback_later(240, exit=True)

    def tearDown(self):
        faulthandler.cancel_dump_traceback_later()

    def _wait(self, cond, seconds=20):
        for _ in range(int(seconds * 10)):
            self.h.refresh()
            if cond():
                return True
            time.sleep(0.1)
        return False

    def _app(self, app_id):
        return next(a for a in self.get("/api/state")["apps"] if a["id"] == app_id)

    def _up_or_skip(self, cond, msg):
        if self._wait(cond):
            return
        if sys.platform == "darwin" and os.environ.get("CI"):
            # Health checks reach the apps over loopback TCP, which GitHub's macOS runners block for Python.
            self.skipTest("loopback TCP is blocked on this macOS CI runner")
        self.fail(msg)

    def test_stack_wiring_inspector_sleep_and_wake(self):
        Path(self.home.name, "serve.py").write_text(SERVE)
        py = f'"{sys.executable}" -u serve.py'
        db_port, web_port = free_port(), probe.free_ports(48500, 1)[0]
        _, db = self.call("POST", "/api/apps", {"name": "Store DB", "slug": "storedb", "cwd": self.home.name, "port": db_port,
                                                "command": py + " {port}", "health": "/"})
        _, web = self.call("POST", "/api/apps", {"name": "Store Web", "slug": "storeweb", "cwd": self.home.name, "port": web_port,
                                                 "command": py + " {port}", "dependsOn": ["storedb"], "env": {"UPSTREAM": "{url:storedb}"}})
        status, res = self.call("POST", f"/api/apps/{web['id']}/start", {})
        self.assertEqual((status, res.get("stack")), (200, ["Store DB", "Store Web"]))
        self._up_or_skip(lambda: self._app(web["id"])["state"] == "running" and self._app(web["id"])["ports"], "the stack did not come up")
        self.assertEqual(self._app(db["id"])["state"], "running", "the dependency was not started first")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/")
        req.add_header("Host", f"storeweb.localhost:{self.port}")
        with NO_PROXY.open(req, timeout=10) as r:
            self.assertEqual(r.read().decode(), f"ok http://localhost:{db_port}", "the app did not get its dependency's URL")
        # the proxy records a request once the exchange is over, which can be just after the client has its answer
        self.assertTrue(self._wait(lambda: self.get(f"/api/apps/{web['id']}/requests")["requests"], 5), "the request was not recorded")
        reqs = self.get(f"/api/apps/{web['id']}/requests")["requests"]
        self.assertEqual((reqs[-1]["method"], reqs[-1]["path"], reqs[-1]["status"]), ("GET", "/", 200))
        # sleep after a quiet minute, then wake on the next request
        self.call("PUT", f"/api/apps/{web['id']}", {"sleepAfter": 1, "wake": True})
        m = self.h.managed[web["id"]]
        m.started_at -= 120
        self.h.last_traffic[web["id"]] = time.time() - 120
        self.h._sleep_idle_apps()
        self.assertTrue(self._wait(lambda: self._app(web["id"])["state"] == "sleeping"), self._app(web["id"]))
        try:
            with NO_PROXY.open(req, timeout=40) as r:
                self.assertEqual(r.status, 200, "the request did not wake the app")
        except urllib.error.HTTPError as err:
            logs = self.get(f"/api/apps/{web['id']}/logs")
            self.fail(f"the request did not wake the app: HTTP {err.code} {err.read()[:300]!r}; app {self._app(web['id'])}; "
                      f"output {str(logs)[-1500:]}")
        self.assertTrue(self._wait(lambda: self._app(web["id"])["state"] == "running"))
        # workspaces remember what was running
        _, ws = self.call("POST", "/api/workspaces", {"name": "shop"})
        self.assertEqual(set(ws["apps"]) >= {db["id"], web["id"]}, True)
        for a in (web, db):
            self.call("POST", f"/api/apps/{a['id']}/stop", {})
        self.assertTrue(self._wait(lambda: self._app(db["id"])["state"] in ("stopped", "exited")))
        status, res = self.call("POST", f"/api/workspaces/{ws['id']}/restore", {})
        self.assertEqual(res["starting"], ["Store DB", "Store Web"])
        self.assertTrue(self._wait(lambda: self._app(web["id"])["state"] == "running"), "the workspace did not come back")
        for a in (web, db):
            self.call("POST", f"/api/apps/{a['id']}/stop", {})

    def test_porthaven_toml_up_and_down(self):
        Path(self.home.name, "serve.py").write_text(SERVE)
        p1, p2 = probe.free_ports(48700, 2)
        Path(self.home.name, "porthaven.toml").write_text(f"""
[apps.backend]
command = '"{sys.executable}" -u serve.py {{port}}'
port = {p1}
health = "/"

[apps.frontend]
command = '"{sys.executable}" -u serve.py {{port}}'
port = {p2}
depends_on = ["backend"]
env = {{ UPSTREAM = "{{url:backend}}" }}
""")
        status, res = self.call("POST", "/api/teamfile/up", {"path": self.home.name})
        self.assertEqual((status, res["order"]), (200, ["Backend", "Frontend"]), res)
        ids = res["ids"]
        self._up_or_skip(lambda: all(self._app(i)["state"] == "running" and self._app(i)["ports"] for i in ids), "the stack did not come up")
        status, again = self.call("POST", "/api/teamfile/import", {"path": self.home.name})
        self.assertEqual((again["added"], len(again["updated"])), ([], 2), "re-importing must update, not duplicate")
        status, down = self.call("POST", "/api/teamfile/down", {"path": self.home.name})
        self.assertEqual(sorted(down["stopped"]), ["Backend", "Frontend"])
