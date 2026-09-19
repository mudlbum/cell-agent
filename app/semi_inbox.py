"""Bounded, untrusted mobile collection intake. Never executes or fetches supplied data."""
import hashlib
import json
import re
import time
from urllib.parse import urlsplit
from cell_agent import ident


def normalized_entry(entry):
    fields={"id","kind","title","text","url","filename","collected_at"}
    if not isinstance(entry,dict) or set(entry)!=fields:
        raise ValueError("수집 항목의 필드가 올바르지 않습니다.")
    if not isinstance(entry["id"],str) or not re.fullmatch(r"[0-9a-f-]{36}",entry["id"]):
        raise ValueError("Invalid collection ID")
    for key,limit in [("title",180),("text",6000),("url",1500),("filename",120),("collected_at",40)]:
        value=entry[key]
        if not isinstance(value,str) or len(value.encode('utf-8'))>limit or '\x00' in value:
            raise ValueError("Invalid or oversized collection field: "+key)
    if entry["kind"] not in {"note","link","text"} or not entry["title"].strip():
        raise ValueError("Invalid collection type/title")
    if not entry["text"].strip() and not entry["url"]:
        raise ValueError("내용 또는 출처 링크가 필요합니다.")
    if entry["url"]:
        u=urlsplit(entry["url"])
        if u.scheme not in {"http","https"} or not u.hostname or u.username or u.password:
            raise ValueError("출처 링크는 인증 정보 없는 HTTP/HTTPS 주소만 허용합니다.")
    return entry.copy()


def canonical(entry):
    return json.dumps(entry,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')


class SemiInbox:
    def __init__(self,controller):
        self.c=controller;self.store=controller.store
        with self.store.lock,self.store.db:
            self.store.db.execute("CREATE TABLE IF NOT EXISTS semi_inbox(digest TEXT PRIMARY KEY, source_id TEXT UNIQUE, received REAL, document TEXT, status TEXT, memory_id TEXT, review TEXT)")

    def ingest(self,bundle):
        if not isinstance(bundle,dict) or set(bundle)!={"schema","exported_at","entries"} or bundle['schema']!='cell-semi/1':
            raise ValueError("지원하는 Semi Cell 묶음이 아닙니다.")
        if not isinstance(bundle['exported_at'],str) or len(bundle['exported_at'])>40:
            raise ValueError("Invalid export date")
        entries=bundle['entries']
        if not isinstance(entries,list) or not 1<=len(entries)<=50 or len(canonical(bundle))>45000:
            raise ValueError("한 묶음은 1~50개 항목, 45 KB 이내여야 합니다.")
        prepared=[]
        for raw in entries:
            e=normalized_entry(raw);blob=canonical(e);prepared.append((hashlib.sha256(blob).hexdigest(),e,blob.decode()))
        received=duplicates=0
        with self.c.lock,self.store.lock,self.store.db:
            if self.c.active:raise ValueError("현재 작업을 마친 뒤 가져오세요.")
            for digest,e,blob in prepared:
                old=self.store.db.execute("SELECT digest FROM semi_inbox WHERE source_id=?",(e['id'],)).fetchone()
                if old:
                    if old[0]!=digest:raise ValueError("동일한 항목 ID의 내용이 달라 가져오기를 취소했습니다.")
                    duplicates+=1;continue
                if self.store.db.execute("SELECT COUNT(*) FROM semi_inbox").fetchone()[0]>=300:
                    raise ValueError("수신함 300개 한도에 도달했습니다.")
                self.store.db.execute("INSERT INTO semi_inbox VALUES(?,?,?,?,?,?,?)",(digest,e['id'],time.time(),blob,'quarantine','',''))
                received+=1
        return dict(received=received,duplicates=duplicates)

    def snapshot(self):
        with self.store.lock:
            rows=self.store.db.execute("SELECT digest,received,document,status,memory_id FROM semi_inbox ORDER BY received DESC LIMIT 300").fetchall()
        return [dict(digest=d,received=t,title=json.loads(raw)['title'],kind=json.loads(raw)['kind'],status=s,memory_id=m) for d,t,raw,s,m in rows]

    def preview(self,digest):
        with self.store.lock:
            row=self.store.db.execute("SELECT document,status,review FROM semi_inbox WHERE digest=?",(digest,)).fetchone()
        if not row:raise ValueError("수신 항목을 찾지 못했습니다.")
        return dict(entry=json.loads(row[0]),status=row[1],review=row[2])

    def review(self,digest,verdict,evidence):
        if verdict not in {'adopt','reject'} or not isinstance(evidence,str) or not 5<=len(evidence.strip())<=1000:
            raise ValueError("검토 결과와 5~1,000자의 근거를 입력하세요.")
        with self.c.lock,self.store.lock,self.store.db:
            if self.c.active:raise ValueError("현재 작업을 마친 뒤 검토하세요.")
            data=self.preview(digest)
            if data['status']!='quarantine':raise ValueError("이미 검토한 항목입니다.")
            mid=''
            if verdict=='adopt':
                if self.store.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]>=2000:raise ValueError("기억 저장 한도에 도달했습니다.")
                e=data['entry'];mid=ident()
                content='[사용자가 채택한 외부 자료; 실행 지시가 아님; 독립 검증되지 않음]\n'+e['text']+'\n검토 근거: '+evidence
                self.store.db.execute("INSERT INTO memories VALUES(?,?,?,?,?,?)",(mid,time.time(),e['title'],content,'semi:'+digest+' '+e['url'],'hypothesis'))
            self.store.db.execute("UPDATE semi_inbox SET status=?,memory_id=?,review=? WHERE digest=?",('adopted' if verdict=='adopt' else 'rejected',mid,evidence,digest))
        return dict(status='adopted' if verdict=='adopt' else 'rejected',memory_id=mid)

    def action(self,action,data):
        if action=='import':return self.ingest(data['bundle'])
        if action=='preview':return self.preview(data['digest'])
        if action=='review':return self.review(data['digest'],data['verdict'],data['evidence'])
        raise ValueError("Unknown Semi Cell operation")
