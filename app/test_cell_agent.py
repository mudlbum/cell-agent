import concurrent.futures
import gzip
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cell_agent import Budget, DemoProvider, FileBody, LimitReached, OpenAIProvider, Runtime, Store


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "workspace"
        self.store = Store(self.base / "state")
        self.files = FileBody([self.root], self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def runtime(self, **kwargs):
        return Runtime(kwargs.pop("provider", DemoProvider()), self.store, [self.root], **kwargs)


class FilesTests(Fixture):
    def test_create_overwrite_delete_and_undo(self):
        self.files.change("a.txt", "first\r\n한글")
        original = (self.root / "a.txt").read_bytes()
        changed = self.files.change("a.txt", "second")
        self.files.restore(changed["change_id"])
        self.assertEqual((self.root / "a.txt").read_bytes(), original)
        deleted = self.files.change("a.txt", delete=True)
        self.assertFalse((self.root / "a.txt").exists())
        self.files.restore(deleted["change_id"])
        self.assertEqual((self.root / "a.txt").read_bytes(), original)

    def test_undo_new_file_removes_it(self):
        change = self.files.change("new.txt", "content")
        self.files.restore(change["change_id"])
        self.assertFalse((self.root / "new.txt").exists())

    def test_undo_detects_newer_changes(self):
        change = self.files.change("a.txt", "one")
        self.files.change("a.txt", "two")
        with self.assertRaisesRegex(ValueError, "newer work"):
            self.files.restore(change["change_id"])
        self.assertEqual(self.files.read("a.txt"), "two")

    def test_scope_and_runtime_state_protection(self):
        with self.assertRaises(PermissionError):
            self.files.change("../outside.txt", "bad")
        with self.assertRaises(PermissionError):
            self.files.read(str(self.base / "outside.txt"))
        broad = FileBody([self.base], self.store)
        with self.assertRaises(PermissionError):
            broad.read(str(self.store.directory / "cells.sqlite3"))

    def test_binary_file_not_destroyed_by_text_write(self):
        target = self.root / "binary"
        target.write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(UnicodeDecodeError):
            self.files.change("binary", "text")
        self.assertEqual(target.read_bytes(), b"\xff\xfe\x00")


class StoreTests(Fixture):
    def test_memory_dedup_and_persistence(self):
        first = self.store.remember("topic", "fact", "source", "observed")
        second = self.store.remember("topic", "fact", "source", "observed")
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate"])
        self.store.close()
        self.store = Store(self.base / "state")
        self.assertEqual(len(self.store.recall("fact")), 1)

    def test_skill_update_invalidates_activation(self):
        first = self.store.propose_skill("helper", "v1", "evidence")
        self.store.activate("helper", first["digest"])
        self.assertEqual(len(self.store.skills(True)), 1)
        self.store.propose_skill("helper", "v2", "new evidence")
        self.assertEqual(self.store.skills(True), [])
        with self.assertRaises(ValueError):
            self.store.activate("helper", first["digest"])

    def test_archive_preserves_memories_and_backup(self):
        self.store.remember("topic", "fact", "source", "observed")
        self.files.change("a.txt", "a")
        changed = self.files.change("a.txt", "b")
        self.store.event("run", "cell", "old", {"proof": 42})
        with self.store.db:
            self.store.db.execute("UPDATE events SET at=?", (time.time() - 10 * 86400,))
        self.store.event("newrun", "cell", "new", {})
        result = self.store.compact()
        self.assertEqual(result["archived_events"], 1)
        with gzip.open(result["archive"], "rt", encoding="utf-8") as stream:
            self.assertIn("42", stream.read())
        self.assertEqual(self.store.stats()["events"], 1)
        self.assertEqual(len(self.store.recall("fact")), 1)
        self.files.restore(changed["change_id"])
        self.assertEqual(self.files.read("a.txt"), "a")

    def test_mail_is_isolated_by_run_and_delivered_once(self):
        self.store.mail("r1", "a", "b", "hello")
        self.assertEqual(self.store.inbox("r2", "b"), [])
        self.assertEqual(self.store.inbox("r1", "b")[0]["content"], "hello")
        self.assertEqual(self.store.inbox("r1", "b"), [])


class RuntimeTests(Fixture):
    def test_storage_threshold_stops_before_model_call(self):
        class Provider:
            def response(self, *args, **kwargs):
                raise AssertionError("Must not be called")
        run = self.runtime(provider=Provider(), max_state_mb=0)
        with self.assertRaisesRegex(LimitReached, "storage threshold"):
            run.run_cell("task")
        self.assertEqual(run.budget.calls, 0)

    def test_cancelled_run_cannot_start_command(self):
        run = self.runtime(shell="trusted")
        run.cancel.set()
        with patch("subprocess.Popen") as proc:
            with self.assertRaises(LimitReached):
                run.command([sys.executable, "-c", "print(1)"], ".")
            proc.assert_not_called()

    def test_api_key_not_in_child_environment(self):
        run = self.runtime(shell="trusted")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "not-a-real-key"}):
            result = run.command([sys.executable, "-c",
                "import os; print('present' if 'OPENAI_API_KEY' in os.environ else 'absent')"], ".")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["output"].strip(), "absent")

    def test_command_denied_without_execution(self):
        run = self.runtime(shell="deny")
        with patch("subprocess.Popen") as proc:
            with self.assertRaises(PermissionError):
                run.command([sys.executable, "-c", "print(1)"], ".")
            proc.assert_not_called()

    def test_declined_command_does_not_execute(self):
        run = self.runtime(shell="ask", confirm=lambda argv, cwd: False)
        with patch("subprocess.Popen") as proc:
            with self.assertRaises(PermissionError):
                run.command([sys.executable, "-c", "print(1)"], ".")
            proc.assert_not_called()

    def test_trusted_command_reports_actual_exit_and_output(self):
        run = self.runtime(shell="trusted")
        result = run.command([sys.executable, "-c", "print('verified'); raise SystemExit(7)"], ".")
        self.assertEqual(result["exit_code"], 7)
        self.assertIn("verified", result["output"])

    def test_read_only_cell_cannot_mutate_or_delegate(self):
        run = self.runtime()
        with self.assertRaises(PermissionError):
            run.tool("x", 0, "write_file", {"path": "x", "content": "x"}, True)
        with self.assertRaises(PermissionError):
            run.tool("x", 0, "delegate", {"tasks": []}, True)

    def test_shared_call_budget_under_concurrency(self):
        budget = Budget(calls=5)
        def reserve(_):
            try:
                budget.reserve_call()
                return True
            except LimitReached:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(30)))
        self.assertEqual(sum(results), 5)

    def test_delegate_really_overlaps_and_limits_depth(self):
        barrier = threading.Barrier(2)
        class Provider:
            def response(self, *args, **kwargs):
                barrier.wait(timeout=5)
                return {"id": "fake", "output": [{"type": "message", "content": [{"text": "done"}]}]}
        run = self.runtime(provider=Provider())
        tasks = [{"role": str(i), "task": "inspect", "read_only": True} for i in range(2)]
        results = run.tool("root", 0, "delegate", {"tasks": tasks})
        self.assertTrue(all(r.get("result") == "done" for r in results))
        self.assertEqual(run.budget.cells, 2)
        with self.assertRaises(LimitReached):
            run.tool("root", 2, "delegate", {"tasks": tasks})

    def test_demo_checks_real_generated_code_and_memory_reuse(self):
        run = self.runtime(shell="trusted")
        run.run_cell("demo")
        self.assertEqual(run.budget.cells, 2)
        results = [json.loads(row[0]) for row in self.store.db.execute(
            "SELECT data FROM events WHERE kind='tool_result'")]
        command = next(r["result"] for r in results if r["name"] == "run_command")
        self.assertEqual(command["exit_code"], 0)
        self.assertIn("3 checks passed", command["output"])
        self.assertEqual(len(self.store.recall("demo-sum")), 1)
        self.assertEqual(self.store.skills()[0]["status"], "candidate")
        self.assertTrue(all(c["status"] == "finished_unverified" for c in run.cells.values()))

    def test_incomplete_response_is_not_success(self):
        class Provider:
            def response(self, *args, **kwargs):
                return {"id": "x", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
        run = self.runtime(provider=Provider())
        with self.assertRaises(RuntimeError):
            run.run_cell("task")
        self.assertEqual(next(iter(run.cells.values()))["status"], "stopped")

    def test_tool_output_keeps_matching_call_id(self):
        class Provider:
            def __init__(self):
                self.calls = []
            def response(self, instructions, inputs, previous, tools, timeout):
                self.calls.append((inputs, previous))
                if previous is None:
                    return {"id": "resp-first", "output": [{"type": "function_call", "name": "system_info",
                        "call_id": "call-original", "arguments": "{}"}]}
                return {"id": "resp-second", "output": [{"type": "message", "content": [{"text": "done"}]}]}
        provider = Provider()
        self.runtime(provider=provider).run_cell("task")
        self.assertEqual(provider.calls[1][1], "resp-first")
        self.assertEqual(provider.calls[1][0][0]["call_id"], "call-original")


class AdapterTests(unittest.TestCase):
    def test_paid_adapter_does_not_send_configured_key(self):
        with patch("urllib.request.urlopen") as transport:
            with self.assertRaisesRegex(RuntimeError, "유료"):
                OpenAIProvider("test-key", web=True).response("policy", [], "previous", [])
            transport.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
