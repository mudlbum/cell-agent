"""Loopback-only control plane. Workers run in Windows Job Objects, outside this server."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cell_agent import BASE, Store, FileBody, dump, ident
from growth import Growth
from process_guard import ProcessGuard
from conversation import Conversations
from mesh import Mesh
from semi_inbox import SemiInbox
from autonomy import Autonomy


def prepare(store):
    with store.lock, store.db:
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs(
                id TEXT PRIMARY KEY, created REAL, ended REAL, status TEXT,
                goal TEXT, criteria TEXT, config TEXT, result TEXT DEFAULT '', reason TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS approvals(
                id TEXT PRIMARY KEY, run TEXT, at REAL, argv TEXT, cwd TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS control(key TEXT PRIMARY KEY, value TEXT);
        """)


class Controller:
    def __init__(self, state, roots, lease_seconds=45, enable_autonomy=False):
        import msvcrt
        state = Path(state).resolve()
        state.mkdir(parents=True, exist_ok=True)
        self.instance_lock = open(state / "supervisor.lock", "a+b")
        self.instance_lock.seek(0)
        try:
            msvcrt.locking(self.instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.instance_lock.close()
            raise RuntimeError("이 상태 폴더를 사용하는 제어 서버가 이미 실행 중입니다.") from None
        self.store = Store(state)
        prepare(self.store)
        self.growth = Growth(self.store)
        self.roots = [str(Path(p).resolve()) for p in roots]
        self.body = FileBody(self.roots, self.store)
        self.conversations = Conversations(self)
        self.mesh = Mesh(self)
        self.semi = SemiInbox(self)
        self.api_key = ""
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.active = None
        self.closed = threading.Event()
        self.last_seen = time.monotonic()
        self.lease_seconds = lease_seconds
        with self.store.lock, self.store.db:
            stale = self.store.db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('running','paused','starting')").fetchone()[0]
            self.store.db.execute("UPDATE runs SET status='interrupted',ended=?,reason='Controller restarted; review previous effects' WHERE status IN ('running','paused','starting')", (time.time(),))
            self.store.db.execute("UPDATE approvals SET status='denied' WHERE status='pending'")
            row = self.store.db.execute("SELECT value FROM control WHERE key='halted'").fetchone()
            self.halted = bool(stale or (row and row[0] == "1"))
            self._persist_latch()
        self.watch = threading.Thread(target=self._watch, daemon=True)
        self.watch.start()
        self.autonomy = Autonomy(self,start=enable_autonomy)

    def _persist_latch(self):
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT OR REPLACE INTO control VALUES('halted',?)", ("1" if self.halted else "0",))

    @staticmethod
    def _number(data, name, default, low, high):
        value = data.get(name, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{name}: expected integer {low}..{high}")
        return value

    def start(self, data, context=None, background=False):
        mode = data.get("mode", "demo")
        if mode == "live":
            raise ValueError("현재 설정에서는 유료 외부 LLM 호출을 사용하지 않습니다. 로컬 대화 또는 데모를 선택하세요.")
        if mode not in {"demo", "local", "search", "kill_test", "growth", "peer_sync", "research"}:
            raise ValueError("Unknown execution mode")
        goal, criteria = data.get("goal", ""), data.get("criteria", "")
        if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 12000:
            raise ValueError("목표를 입력하세요 (최대 12,000자).")
        if not isinstance(criteria, str) or not 1 <= len(criteria.strip()) <= 4000:
            raise ValueError("완료 기준을 입력하세요 (최대 4,000자).")
        shell = data.get("shell", "ask")
        if shell not in {"deny", "ask", "trusted"}:
            raise ValueError("Invalid command mode")
        key = data.get("api_key", "") or self.api_key or os.environ.get("OPENAI_API_KEY", "")
        if not isinstance(key, str) or len(key) > 1000:
            raise ValueError("Invalid API key")
        if mode == "live" and not key:
            raise ValueError("실제 실행에는 OpenAI API 키가 필요합니다. 데모는 키 없이 실행됩니다.")
        config = {"mode": mode, "shell": shell, "web": data.get("web") is True,
                  "max_calls": self._number(data, "max_calls", 20, 1, 100),
                  "max_cells": self._number(data, "max_cells", 8, 1, 16),
                  "seconds": self._number(data, "seconds", 900, 10, 3600),
                  "tokens": self._number(data, "tokens", 80000, 1000, 300000),
                  "memory_mb": self._number(data, "memory_mb", 1024, 128, 8192),
                  "cpu_percent": self._number(data, "cpu_percent", 50, 10, 100),
                  "state_mb": self._number(data, "state_mb", 256, 16, 4096)}
        if mode in {"growth","peer_sync","research"}:
            if not background:raise ValueError("이 작업은 자율 감독 루프에서만 시작합니다.")
            config["auto_source"]=str(data.get("auto_source",""))[:128]
        with self.lock:
            if self.closed.is_set():
                raise ValueError("Controller is closing")
            if self.halted:
                raise ValueError("비상 정지 잠금을 먼저 해제하세요.")
            if self.active:
                raise ValueError("이미 실행 중인 작업이 있습니다.")
            run = ident()
            # Demo workspaces are distinct from live user workspaces.
            roots = self.roots if mode in {"live", "local"} else [str(Path(self.roots[0]) / "examples" / run)]
            for root in roots:
                Path(root).mkdir(parents=True, exist_ok=True)
            config["roots"] = roots
            with self.store.lock, self.store.db:
                self.store.db.execute("INSERT INTO runs(id,created,status,goal,criteria,config) VALUES(?,?,?,?,?,?)",
                                      (run, time.time(), "starting", goal, criteria, dump(config)))
            guard = process = None
            try:
                guard = ProcessGuard(config["memory_mb"], config["cpu_percent"])
                env = {k: v for k, v in os.environ.items()
                       if not any(s in k.upper() for s in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))}
                process = subprocess.Popen([sys.executable, "-X", "utf8", str(BASE / "dashboard_worker.py")],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    cwd=BASE, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
                # Worker waits on stdin. No task or key is delivered before successful attachment.
                guard.attach(process)
                self.active = {"run": run, "process": process, "guard": guard, "background":background,
                               "deadline": time.monotonic() + config["seconds"]}
                self.last_seen = time.monotonic()
                with self.store.lock, self.store.db:
                    self.store.db.execute("UPDATE runs SET status='running' WHERE id=?", (run,))
                payload = dict(run=run, state=str(self.store.directory), config=config,
                               goal=goal, criteria=criteria, context=context or [], api_key=key if mode == "live" else "")
                process.stdin.write((dump(payload) + "\n").encode())
                process.stdin.close()
                self.store.event(run, "supervisor", "started", {"mode": mode, "pid": process.pid,
                    "containment": "Windows Job Object", "memory_mb": config["memory_mb"], "cpu_percent": config["cpu_percent"]})
                return {"run": run}
            except BaseException as error:
                if guard:
                    guard.close()
                if process:
                    with contextlib.suppress(Exception):
                        process.kill()
                        process.wait(timeout=3)
                    if process.stdin and not process.stdin.closed:
                        process.stdin.close()
                self.active = None
                with self.store.lock, self.store.db:
                    self.store.db.execute("UPDATE runs SET status='failed',ended=?,reason=? WHERE id=?",
                                          (time.time(), "Startup failed: " + str(error), run))
                raise

    def pause(self, paused):
        with self.lock:
            if not self.active:
                raise ValueError("실행 중인 작업이 없습니다.")
            with self.store.lock, self.store.db:
                self.store.db.execute("UPDATE runs SET status=? WHERE id=?",
                                      ("paused" if paused else "running", self.active["run"]))
            self.store.event(self.active["run"], "supervisor", "pause" if paused else "resume", {})
        return {"paused": paused, "note": "Boundary pause; in-flight API calls and commands may complete"}

    def kill(self, reason="Operator emergency stop"):
        with self.lock:
            self.halted = True
            # Terminate before waiting on SQLite; a crashed 'running' record locks on restart.
            active = self.active
            if active:
                peak = active["guard"].peak_bytes()
                active["guard"].kill()
                active["guard"].close()
                try:
                    active["process"].wait(timeout=3)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("Termination requested but worker exit not confirmed; latch remains locked")
                self.active = None
                with self.store.lock, self.store.db:
                    self.store.db.execute("UPDATE runs SET status='killed',ended=?,reason=? WHERE id=?",
                                          (time.time(), reason, active["run"]))
                    self.store.db.execute("UPDATE approvals SET status='denied' WHERE run=? AND status='pending'", (active["run"],))
                self.store.event(active["run"], "supervisor", "killed", {"reason": reason})
                self.store.event(active["run"], "supervisor", "resource_peak", {"peak_bytes": peak})
            self._persist_latch()
            return {"halted": True, "worker_exit_confirmed": True,
                    "note": "Already-sent remote requests and completed side effects are not undone"}

    def reset(self, confirmation):
        if confirmation != "RESUME":
            raise ValueError("잠금 해제를 위해 RESUME을 입력하세요.")
        with self.lock:
            if self.active:
                raise ValueError("Cannot unlock during execution")
            self.halted = False
            self._persist_latch()
        return {"halted": False}

    def approve(self, aid, allow):
        if type(allow) is not bool:
            raise ValueError("allow must be a boolean")
        with self.lock, self.store.lock, self.store.db:
            if self.halted or not self.active:
                raise ValueError("No active authorized run")
            changed = self.store.db.execute("UPDATE approvals SET status=? WHERE id=? AND run=? AND status='pending'",
                ("approved" if allow else "denied", aid, self.active["run"])).rowcount
            if not changed:
                raise ValueError("Approval expired or already handled")
        return {"recorded": True}

    def _watch(self):
        while not self.closed.wait(0.25):
            try:
                with self.lock:
                    a = self.active
                    if not a:
                        continue
                    if a["process"].poll() is not None:
                        # Closing the job also reaps descendants left behind by a finished worker.
                        peak = a["guard"].peak_bytes()
                        a["guard"].close()
                        self.store.event(a["run"], "supervisor", "resource_peak", {"peak_bytes": peak})
                        with self.store.lock, self.store.db:
                            row = self.store.db.execute("SELECT data FROM events WHERE run=? AND kind='worker_outcome' ORDER BY seq DESC LIMIT 1", (a["run"],)).fetchone()
                            outcome = json.loads(row[0]) if row else {}
                            status = "report_ready" if a["process"].returncode == 0 and outcome.get("ok") else "failed"
                            self.store.db.execute("UPDATE runs SET status=?,ended=?,result=?,reason=? WHERE id=?",
                                (status, time.time(), outcome.get("result", ""), outcome.get("error", "") or ("" if status == "report_ready" else "Worker exited without a complete report"), a["run"]))
                            self.store.db.execute("UPDATE approvals SET status='denied' WHERE run=? AND status='pending'", (a["run"],))
                        self.active = None
                    elif time.monotonic() >= a["deadline"]:
                        self.kill("Wall-clock deadline reached")
                    elif not a.get("background") and self.lease_seconds and time.monotonic() - self.last_seen > self.lease_seconds:
                        self.kill("Dashboard connection heartbeat lost")
            except Exception as error:
                # A watcher failure must not silently leave work running.
                with self.lock:
                    self.halted = True
                    if self.active:
                        with contextlib.suppress(Exception):
                            self.active["guard"].close()
                    with contextlib.suppress(Exception):
                        self._persist_latch()
                        self.store.event("", "supervisor", "watchdog_error", {"error": str(error)})

    def snapshot(self, run=None, chat=None):
        self.last_seen = time.monotonic()
        with self.lock:
            active_id = self.active["run"] if self.active else None
            peak = self.active["guard"].peak_bytes() if self.active else 0
            halted = self.halted
        with self.store.lock:
            self.store.db.row_factory = sqlite3.Row
            try:
                runs = [dict(r) for r in self.store.db.execute("SELECT * FROM runs ORDER BY created DESC LIMIT 25")]
                selected = run or active_id or (runs[0]["id"] if runs else None)
                details = next((r for r in runs if r["id"] == selected), None)
                raw = [dict(r) for r in self.store.db.execute("SELECT * FROM events WHERE run=? ORDER BY seq ASC LIMIT 5000", (selected,))]
                approvals = [dict(r) for r in self.store.db.execute("SELECT * FROM approvals WHERE status='pending' ORDER BY at")]
                changes = [dict(r) for r in self.store.db.execute("SELECT id,at,path,status FROM changes ORDER BY at DESC LIMIT 12")]
                evaluations = [dict(r) for r in self.store.db.execute("SELECT * FROM evaluations ORDER BY at DESC LIMIT 30")]
            finally:
                self.store.db.row_factory = None
        cells, metrics, events = {}, {"calls": 0, "cells": 0, "tokens": 0}, []
        for item in raw:
            data = json.loads(item["data"])
            cid, kind = item["cell"], item["kind"]
            if kind == "cell_created":
                cells[cid] = dict(id=cid, role=data["role"], parent=data.get("parent"), status="created", tool="")
            elif kind == "start":
                cells.setdefault(cid, dict(id=cid, role=data["role"], parent=None, tool=""))["status"] = "running"
            elif kind == "budget":
                metrics = {key: max(metrics[key], data.get(key, 0)) for key in metrics}
            elif kind == "resource_peak" and selected != active_id:
                peak = data.get("peak_bytes", 0)
            elif kind == "tool_requested" and cid in cells:
                cells[cid]["tool"] = data.get("name", "")
            elif kind in {"final", "stopped"} and cid in cells:
                cells[cid]["status"] = "report_ready" if kind == "final" else "stopped"
            # Do not transfer whole model response histories into the browser every second.
            if kind != "response":
                events.append(dict(seq=item["seq"], at=item["at"], cell=cid, kind=kind, detail=dump(data)[:6000]))
        if details and details["status"] in {"killed", "interrupted", "failed"}:
            for cell in cells.values():
                if cell["status"] in {"running", "created"}:
                    cell["status"] = "stopped"
        for record in runs:
            record["config"] = json.loads(record["config"])
        return dict(halted=halted, active=active_id, roots=self.roots, selected=selected,
                    runs=runs, cells=list(cells.values()), metrics=metrics, peak_bytes=peak,
                    approvals=approvals, events=events[-80:], storage=self.store.stats(),
                    routes=self.growth.find(), skills=self.store.skills(), memories=self.store.recall(""),
                    changes=changes, evaluations=evaluations, lease_seconds=self.lease_seconds,
                    conversation=self.conversations.snapshot(chat), key_configured=bool(self.api_key or os.environ.get("OPENAI_API_KEY")),
                    autonomy=self.autonomy.snapshot() if hasattr(self,"autonomy") else {},
                    semi_inbox=self.semi.snapshot(),
                    mesh=self.mesh.snapshot() if hasattr(self,"mesh") else {"available":False})

    def idle_action(self, action, data):
        with self.lock:
            if self.active:
                raise ValueError("이 작업은 실행 종료 후 수행하세요.")
            if action == "route-review":
                return self.growth.review(data["name"], data["digest"], data["verdict"], data["evidence"], data.get("run", ""))
            if action == "skill-activate":
                self.store.activate(data["name"], data["digest"])
                self.store.event("", "operator", "skill_activated", {"name": data["name"], "digest": data["digest"], "evidence": str(data.get("evidence", ""))[:8000]})
                return {"activated": True}
            if action == "restore":
                return self.body.restore(data["change_id"])
            if action == "compact":
                return self.store.compact()
            if action == "evaluate":
                with self.store.lock:
                    row = self.store.db.execute("SELECT status FROM runs WHERE id=?", (data["run"],)).fetchone()
                if not row or row[0] not in {"report_ready", "failed", "killed", "interrupted"}:
                    raise ValueError("Finished run required")
                self.growth.evaluate(data["run"], data["verdict"], data["evidence"])
                return {"recorded": True}
            raise ValueError("Unknown operation")

    def close(self):
        if hasattr(self,"autonomy"):self.autonomy.close()
        with self.lock:
            if self.active:
                self.kill("Controller shutting down")
            self.closed.set()
        self.watch.join(timeout=2)
        self.store.close()
        self.instance_lock.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "CellControl/0.3"

    def log_message(self, *_):
        pass  # Never log Authorization headers, request bodies, or API keys.

    def respond(self, status, data, content_type="application/json; charset=utf-8"):
        payload = data if isinstance(data, bytes) else dump(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(payload)

    def authorized(self):
        expected_host = f"127.0.0.1:{self.server.server_address[1]}"
        if self.headers.get("Host") != expected_host:
            self.respond(403, {"error": "Invalid host"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + expected_host:
            self.respond(403, {"error": "Cross-origin request denied"})
            return False
        supplied = self.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied, "Bearer " + self.server.controller.token):
            self.respond(401, {"error": "Local session token required; open the startup URL"})
            return False
        return True

    def do_GET(self):
        path = urllib.parse.urlparse(self.path)
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                  "/chat.js": ("chat.js", "application/javascript; charset=utf-8"),
                  "/chat.css": ("chat.css", "text/css; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8")}
        if path.path in static:
            name, kind = static[path.path]
            self.respond(200, (BASE / "ui" / name).read_bytes(), kind)
        elif path.path == "/api/snapshot":
            if self.authorized():
                try:
                    query = urllib.parse.parse_qs(path.query)
                    self.respond(200, self.server.controller.snapshot(query.get("run", [None])[0],query.get("chat",[None])[0]))
                except Exception as error:
                    self.respond(500, {"error": str(error)})
        else:
            self.respond(404, {"error": "Not found"})

    def do_POST(self):
        if not self.authorized():
            return
        try:
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("JSON required")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("Body size limit is 64 KB")
            self.connection.settimeout(5)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Object required")
            c = self.server.controller
            action = self.path.removeprefix("/api/")
            if action == "start":
                result = c.start(data)
            elif action == "chat-new":
                result = c.conversations.create()
            elif action == "chat-send":
                result = c.conversations.send(data)
            elif action == "upload":
                result = c.conversations.attach(data)
            elif action == "configure-key":
                key = data.get("api_key", "")
                if not isinstance(key,str) or len(key)>1000:
                    raise ValueError("Invalid API key")
                c.api_key = key.strip()
                result = {"configured":bool(c.api_key)}
            elif action == "autonomy-configure":
                result = c.autonomy.configure(data.get("enabled"))
            elif action == "research-topic":
                result = c.autonomy.topic(data.get("topic"),data.get("enabled",True))
            elif action.startswith("semi-"):
                result = c.semi.action(action[5:],data)
            elif action.startswith("mesh-"):
                result = c.mesh.action(action[5:],data)
            elif action == "kill":
                result = c.kill()
            elif action == "reset":
                result = c.reset(data.get("confirmation"))
            elif action == "pause":
                result = c.pause(True)
            elif action == "resume":
                result = c.pause(False)
            elif action == "approve":
                result = c.approve(data["id"], data["allow"])
            else:
                result = c.idle_action(action, data)
            self.respond(200, result)
        except (ValueError, KeyError, TypeError, PermissionError) as error:
            self.respond(400, {"error": str(error)})
        except Exception as error:
            self.respond(500, {"error": str(error)})


def make_server(controller, port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.controller = controller
    return server


def main():
    parser = argparse.ArgumentParser(description="Cell Agent local control interface")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state", default=str(BASE / "state-ui"))
    parser.add_argument("--root", action="append")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    controller = Controller(args.state, args.root or [BASE / "workspace-ui"], enable_autonomy=True)
    server = make_server(controller, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/#token={controller.token}"
    print("Cell Agent Workspace 0.5\n" + url, flush=True)
    print("Closing this controller stops its active worker. Ctrl+C to exit.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        controller.close()


if __name__ == "__main__":
    main()
