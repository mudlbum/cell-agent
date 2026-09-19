"""Task worker. Must block on stdin until the supervisor assigns its Windows Job."""
import json
from pathlib import Path
import subprocess
import sys
import time

from cell_agent import Budget, DemoProvider, LimitReached, OpenAIProvider, Runtime, Store, dump, ident
from dashboard import prepare
from growth import Growth


def main():
    payload = json.loads(sys.stdin.buffer.readline(524289))
    run, config = payload["run"], payload["config"]
    store = Store(payload["state"])
    prepare(store)
    growth = Growth(store)

    def checkpoint():
        while True:
            with store.lock:
                row = store.db.execute("SELECT status FROM runs WHERE id=?", (run,)).fetchone()
            if not row or row[0] not in {"running", "paused"}:
                raise LimitReached("Supervisor stopped this run")
            if row[0] != "paused":
                return
            time.sleep(0.15)

    def confirm(argv, cwd):
        approval = ident()
        with store.lock, store.db:
            store.db.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?)",
                             (approval, run, time.time(), dump(argv), str(cwd), "pending"))
        store.event(run, "worker", "approval_required", {"id": approval, "argv": argv, "cwd": str(cwd)})
        while True:
            checkpoint()
            with store.lock:
                row = store.db.execute("SELECT status FROM approvals WHERE id=?", (approval,)).fetchone()
            if not row or row[0] == "denied":
                return False
            if row[0] == "approved":
                return True
            time.sleep(0.15)

    class ObservableDemo(DemoProvider):
        def response(self, *args, **kwargs):
            for _ in range(12):
                checkpoint()
                time.sleep(0.1)
            return super().response(*args, **kwargs)

    try:
        if config["mode"] == "kill_test":
            target = str(Path(config["roots"][0]) / "heartbeat.txt")
            script = "import time,pathlib\np=pathlib.Path(" + repr(target) + ")\nfor n in range(1200):\n p.write_text(str(n))\n time.sleep(0.1)\n"
            child = subprocess.Popen([sys.executable, "-c", script], creationflags=subprocess.CREATE_NO_WINDOW)
            store.event(run, "probe", "kill_probe", {"pid": child.pid, "heartbeat_file": target,
                "note": "This child writes a counter every 100 ms. Emergency stop must stop the counter."})
            while child.poll() is None:
                checkpoint()
                time.sleep(0.1)
            result = "중단 실험 프로세스가 종료되었습니다."
        else:
            provider = ObservableDemo() if config["mode"] == "demo" else OpenAIProvider(
                payload["api_key"], web=config["web"])
            payload["api_key"] = ""
            runtime = Runtime(provider, store, config["roots"],
                shell=config["shell"],
                budget=Budget(config["max_calls"], config["max_cells"], config["seconds"], config["tokens"]),
                confirm=confirm, checkpoint=checkpoint, run_id=run, growth=growth,
                max_state_mb=config["state_mb"])
            result = runtime.run_cell(dump({"goal": payload["goal"], "acceptance_criteria": payload["criteria"],
                "conversation_history": payload.get("context", []),
                "instruction": "Completion needs evidence. Recall related routes; verify missing knowledge through primary sources and tests. Propose reusable acquisition routes with fallback and limitations. Never treat your own report as an independent evaluation."}))
            if config["mode"] == "demo":
                growth.propose("python-checks", "Python 코드의 동작을 어떻게 검증하는가",
                    "로컬 Python 실행기와 테스트 파일", "최소 재현 사례와 정상·경계·실패 입력을 구성하고 실제로 실행한다.",
                    "종료 코드와 검증 항목을 확인하고 원래 요구사항과 비교한다.",
                    "환경 오류이면 Python 경로를 확인하고, 별도 환경에서 재현한다.", [])
                result = "오프라인 고정 시나리오 완료. 하위 세포 2개와 파일·명령·기억 도구를 실행했습니다. 실제 LLM 학습이나 지능 향상 실험은 아닙니다.\n\n" + result
        store.event(run, "worker", "worker_outcome", {"ok": True, "result": result})
    except BaseException as error:
        store.event(run, "worker", "worker_outcome", {"ok": False, "error": str(error)})
        raise
    finally:
        store.close()


if __name__ == "__main__":
    main()
