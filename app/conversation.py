"""Persistent conversations; model credentials remain in supervisor memory only."""
import json
import time
from pathlib import Path

from cell_agent import dump, ident


class Conversations:
    def __init__(self, controller):
        self.c = controller
        self.store = controller.store
        with self.store.lock, self.store.db:
            self.store.db.executescript("""
                CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,created REAL,updated REAL,title TEXT);
                CREATE TABLE IF NOT EXISTS chat_messages(id TEXT PRIMARY KEY,at REAL,chat TEXT,role TEXT,content TEXT,run TEXT);
                CREATE INDEX IF NOT EXISTS chat_order ON chat_messages(chat,at);
            """)

    def create(self):
        cid = ident()
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT INTO conversations VALUES(?,?,?,?)", (cid,time.time(),time.time(),"새 대화"))
        return {"chat": cid}

    def send(self, data):
        content = data.get("message", "")
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= 12000:
            raise ValueError("메시지는 1~12,000자로 입력하세요.")
        with self.c.lock:
            cid = data.get("chat")
            with self.store.lock:
                if not self.store.db.execute("SELECT 1 FROM conversations WHERE id=?", (cid,)).fetchone():
                    raise ValueError("대화를 먼저 선택하세요.")
            history = self.snapshot(cid)["messages"][-12:]
            history = [{"role": m["role"], "content": m["content"][-4000:]} for m in history]
            request = {k: v for k,v in data.items() if k not in {"chat", "message", "context"}}
            request.update(goal=content, criteria="사용자 요청에 답하고, 수행한 변경·확인 근거·남은 한계를 구분해 설명한다.")
            result = self.c.start(request, context=history)
            now = time.time()
            with self.store.lock, self.store.db:
                self.store.db.execute("INSERT INTO chat_messages VALUES(?,?,?,?,?,?)", (ident(),now,cid,"user",content,result["run"]))
                self.store.db.execute("INSERT INTO chat_messages VALUES(?,?,?,?,?,?)", (ident(),now+.0001,cid,"assistant","",result["run"]))
                self.store.db.execute("UPDATE conversations SET updated=?, title=CASE WHEN title='새 대화' THEN ? ELSE title END WHERE id=?", (now,content[:50],cid))
            return dict(chat=cid, **result)

    def snapshot(self, cid=None):
        with self.store.lock:
            chats = [dict(zip(("id","created","updated","title"),r)) for r in self.store.db.execute("SELECT * FROM conversations ORDER BY updated DESC LIMIT 50")]
            cid = cid or (chats[0]["id"] if chats else None)
            rows = self.store.db.execute("""SELECT m.id,m.at,m.role,m.content,m.run,r.status,r.result,r.reason
                FROM chat_messages m LEFT JOIN runs r ON r.id=m.run WHERE m.chat=? ORDER BY m.at DESC LIMIT 100""", (cid,)).fetchall()
        messages = []
        for mid,at,role,content,run,status,result,reason in reversed(rows):
            if role == "assistant":
                content = result or reason or ("처리 중…" if status in {"running","paused","starting"} else "작업이 종료되었습니다. 관제실에서 기록을 확인하세요.")
            messages.append(dict(id=mid,at=at,role=role,content=content,run=run,status=status))
        return dict(chats=chats,chat=cid,messages=messages)

    def attach(self, data):
        name, text = data.get("name"), data.get("text")
        extensions = {".txt",".md",".py",".csv",".json",".js",".html",".css",".yaml",".yml",".toml",".sql",".log",".xml"}
        if not isinstance(name,str) or name != Path(name).name or "/" in name or "\\" in name or ":" in name or len(name)>120 or Path(name).suffix.lower() not in extensions:
            raise ValueError("지원하는 텍스트 파일 이름이 아닙니다.")
        if not isinstance(text,str) or len(text.encode("utf-8")) > 40000 or "\x00" in text:
            raise ValueError("첨부는 UTF-8 텍스트 파일당 40 KB까지 지원합니다.")
        with self.c.lock:
            if self.c.active:
                raise ValueError("작업 종료 후 첨부하세요.")
            path = self.c.body.resolve(str(Path(self.c.roots[0]) / "attachments" / ident() / name))
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(text,encoding="utf-8")
        return {"path": str(path), "name": name}
