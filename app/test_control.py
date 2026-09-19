import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from cell_agent import FileBody, Store
from dashboard import Controller, make_server
from growth import Growth
from process_guard import ProcessGuard


def until(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError("Condition timed out")


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "state")
        self.g = Growth(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def proposal(self, strategy="Search official docs"):
        return self.g.propose("route-a", "Python errors", "official documentation", strategy,
                              "execute reproducer", "search version-specific release notes", [])

    def test_route_version_changes_invalidate_review(self):
        r = self.proposal()
        self.g.review(r["name"], r["digest"], "pass", "Observed reproduction passed")
        self.assertEqual(self.g.find("Python")[0]["status"], "active")
        self.proposal("Use updated documentation")
        item = self.g.find("Python")[0]
        self.assertEqual(item["status"], "candidate")
        self.assertEqual(item["successes"], 0)
        with self.assertRaises(ValueError):
            self.g.review(r["name"], r["digest"], "pass", "stale review should fail")

    def test_failure_demotes_route(self):
        r = self.proposal()
        self.g.review(r["name"], r["digest"], "fail", "Counterexample did not pass")
        result = self.g.find()[0]
        self.assertEqual(result["failures"], 1)
        self.assertEqual(result["status"], "needs_review")

    def test_unchanged_route_keeps_reviews(self):
        r = self.proposal()
        self.g.review(r["name"], r["digest"], "pass", "checked example returned expected output")
        self.assertTrue(self.proposal()["unchanged"])
        self.assertEqual(self.g.find()[0]["successes"], 1)

    def test_no_agent_review_tool(self):
        self.assertEqual({t["name"] for t in self.g.tools()}, {"find_routes", "propose_route"})

    def test_write_ahead_intent_survives_failed_replace(self):
        root = Path(self.tmp.name) / "root"
        body = FileBody([root], self.store)
        body.change("a.txt", "old")
        with patch("os.replace", side_effect=OSError("simulated interrupted mutation")):
            with self.assertRaises(OSError):
                body.change("a.txt", "new")
        row = self.store.db.execute("SELECT id,status FROM changes ORDER BY at DESC LIMIT 1").fetchone()
        self.assertEqual(row[1], "pending")
        self.assertTrue(body.restore(row[0])["no_change"])
        self.assertEqual(body.read("a.txt"), "old")


@unittest.skipUnless(os.name == "nt", "Windows Job Objects required")
class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.c = Controller(self.base / "state", [self.base / "workspace"], lease_seconds=0)

    def tearDown(self):
        if self.c:
            self.c.close()
        self.tmp.cleanup()

    def start_probe(self):
        rid = self.c.start({"mode": "kill_test", "goal": "kill probe", "criteria": "counter must stop", "seconds": 30})["run"]
        def get_event():
            s = self.c.snapshot()
            return next((json.loads(e["detail"]) for e in s["events"] if e["kind"] == "kill_probe"), None)
        data = until(get_event)
        path = Path(data["heartbeat_file"])
        until(path.exists)
        return rid, path

    def test_kill_stops_child_writes_and_latches(self):
        rid, path = self.start_probe()
        start = time.monotonic()
        result = self.c.kill()
        elapsed = time.monotonic() - start
        value = path.read_bytes()
        time.sleep(.35)
        self.assertEqual(path.read_bytes(), value)
        self.assertTrue(result["worker_exit_confirmed"])
        self.assertLess(elapsed, 3)
        self.assertEqual(self.c.snapshot()["runs"][0]["status"], "killed")
        with self.assertRaises(ValueError):
            self.c.start({"mode": "demo", "goal": "blocked", "criteria": "none"})
        self.c.reset("RESUME")
        self.assertFalse(self.c.halted)

    def test_latch_survives_restart(self):
        self.c.kill()
        self.c.close()
        self.c = Controller(self.base / "state", [self.base / "workspace"], lease_seconds=0)
        self.assertTrue(self.c.halted)
        with self.assertRaises(ValueError):
            self.c.reset("yes")

    def test_missing_heartbeat_stops_worker(self):
        _, path = self.start_probe()
        self.c.lease_seconds = .2
        self.c.last_seen = time.monotonic() - 1
        until(lambda: self.c.active is None)
        self.assertTrue(self.c.halted)
        value = path.read_bytes()
        time.sleep(.25)
        self.assertEqual(path.read_bytes(), value)

    def test_pause_records_boundary_pause_without_claiming_process_freeze(self):
        self.start_probe()
        self.c.pause(True)
        self.assertEqual(self.c.snapshot()["runs"][0]["status"], "paused")
        self.c.pause(False)
        self.assertEqual(self.c.snapshot()["runs"][0]["status"], "running")
        self.c.kill()

    def test_duplicate_controller_refused(self):
        with self.assertRaises(RuntimeError):
            Controller(self.base / "state", [self.base / "workspace"])

    def test_demo_real_worker_completes_without_api(self):
        self.c.start({"mode": "demo", "goal": "demo", "criteria": "three code checks", "shell": "trusted"})
        until(lambda: self.c.active is None, 15)
        data = self.c.snapshot()
        self.assertEqual(data["runs"][0]["status"], "report_ready")
        self.assertEqual(len(data["cells"]), 3)
        self.assertTrue(data["routes"])
        results = [json.loads(e["detail"]) for e in data["events"] if e["kind"] == "tool_result"]
        command = next(r["result"] for r in results if r["name"] == "run_command")
        self.assertIn("3 checks passed", command["output"])

    def test_demo_approval_is_bound_to_run_and_one_use(self):
        self.c.start({"mode": "demo", "goal": "approval demo", "criteria": "approved command only", "shell": "ask"})
        approvals = until(lambda: self.c.snapshot()["approvals"], 10)
        aid = approvals[0]["id"]
        self.c.approve(aid, True)
        with self.assertRaises(ValueError):
            self.c.approve(aid, True)
        until(lambda: self.c.active is None, 12)
        self.assertEqual(self.c.snapshot()["runs"][0]["status"], "report_ready")

    def test_pending_approval_revoked_on_kill(self):
        rid, _ = self.start_probe()
        with self.c.store.lock, self.c.store.db:
            self.c.store.db.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?)",
                                    ("a", rid, time.time(), "[]", ".", "pending"))
        self.c.kill()
        with self.assertRaises(ValueError):
            self.c.approve("a", True)
        self.assertEqual(self.c.snapshot()["approvals"], [])

    def test_job_owner_crash_stops_descendant(self):
        marker = self.base / "owner-crash-counter.txt"
        child_code = "import sys,time,pathlib\nsys.stdin.readline()\np=pathlib.Path(" + repr(str(marker)) + ")\nfor n in range(600):\n p.write_text(str(n))\n time.sleep(.1)\n"
        owner_code = ("from process_guard import ProcessGuard\nimport subprocess,sys\n"
                      "g=ProcessGuard()\np=subprocess.Popen([sys.executable,'-c'," + repr(child_code) +
                      "],stdin=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)\n"
                      "g.attach(p)\np.stdin.write(b'go\\n')\np.stdin.close()\nsys.stdin.readline()\n")
        owner = subprocess.Popen([sys.executable, "-c", owner_code], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            until(marker.exists)
            owner.kill()
            owner.wait(timeout=3)
            time.sleep(.15)
            value = marker.read_bytes()
            time.sleep(.3)
            self.assertEqual(marker.read_bytes(), value)
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=3)
            owner.stdin.close()


@unittest.skipUnless(os.name == "nt", "Windows Job Objects required")
class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = Path(self.tmp.name)
        self.c = Controller(p / "state", [p / "workspace"], lease_seconds=0)
        self.server = make_server(self.c)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.c.close()
        self.tmp.cleanup()

    def request(self, path, body=None, auth=True, extra=None):
        headers = {"Authorization": "Bearer " + self.c.token} if auth else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        headers.update(extra or {})
        req = urllib.request.Request(self.url + path, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        return urllib.request.urlopen(req, timeout=5)

    def test_api_requires_token(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/snapshot", auth=False)
        self.assertEqual(caught.exception.code, 401)

    def test_cross_origin_mutation_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/kill", {}, extra={"Origin": "https://evil.invalid"})
        self.assertEqual(caught.exception.code, 403)
        self.assertFalse(self.c.halted)

    def test_host_rebinding_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/snapshot", extra={"Host": "evil.invalid"})
        self.assertEqual(caught.exception.code, 403)

    def test_kill_endpoint_and_unlock(self):
        with self.request("/api/kill", {}) as response:
            self.assertTrue(json.load(response)["halted"])
        with self.request("/api/reset", {"confirmation": "RESUME"}) as response:
            self.assertFalse(json.load(response)["halted"])

    def test_static_has_csp_and_no_embedded_secret(self):
        with self.request("/", auth=False) as response:
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            self.assertNotIn(self.c.token, response.read().decode())

    def test_live_start_requires_key_and_does_not_log_it(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request("/api/start", {"mode": "live", "goal": "x", "criteria": "y"})
            self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.c.snapshot()["runs"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
