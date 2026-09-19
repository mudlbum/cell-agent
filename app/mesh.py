"""Opt-in signed retrieval-route exchange. No remote execution or automatic activation."""
import base64
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import threading
import time
import urllib.parse
import urllib.request

from cell_agent import dump

FIELDS = ("problem","locator","strategy","verification","fallback","related")
LIMIT = 131072


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def un64(value):
    if not isinstance(value,str) or len(value)>200:
        raise ValueError("Invalid key/signature")
    return base64.b64decode(value,validate=True)


def validate_url(url):
    if not isinstance(url,str) or len(url)>1000:
        raise ValueError("Invalid peer URL")
    p = urllib.parse.urlsplit(url)
    if p.username or p.password or p.query or p.fragment or not p.hostname:
        raise ValueError("Peer URL must not contain credentials, query or fragment")
    if p.scheme != "https":
        try:
            local = ipaddress.ip_address(p.hostname).is_loopback
        except ValueError:
            local = False
        if p.scheme != "http" or not local:
            raise ValueError("HTTPS required except literal loopback addresses")
    return url.rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("Peer redirects are not allowed")


def fetch(url):
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(urllib.request.Request(url,headers={"Accept":"application/json"}),timeout=5) as r:
        data = r.read(LIMIT+1)
    if len(data)>LIMIT:
        raise ValueError("Peer response exceeds 128 KB")
    return data


class Mesh:
    def __init__(self, controller):
        self.c, self.store = controller, controller.store
        self.lock = threading.RLock()
        self.available = False
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption
        except ImportError:
            return
        self.directory = self.store.directory / "mesh"
        self.objects = self.directory / "objects"
        self.objects.mkdir(parents=True,exist_ok=True)
        keyfile = self.directory / "identity.key"
        if keyfile.exists():
            self.key = Ed25519PrivateKey.from_private_bytes(keyfile.read_bytes())
        else:
            self.key = Ed25519PrivateKey.generate()
            # This file must be protected by the owner's OS account. It is never served.
            keyfile.write_bytes(self.key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()))
        self.public = base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
        with self.store.lock,self.store.db:
            self.store.db.executescript("""
                CREATE TABLE IF NOT EXISTS peers(id TEXT PRIMARY KEY,url TEXT,public TEXT,sequence INTEGER DEFAULT -1,enabled INTEGER DEFAULT 1,manifest_hash TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS packages(hash TEXT PRIMARY KEY,peer TEXT,name TEXT,status TEXT,at REAL);
                CREATE TABLE IF NOT EXISTS published(hash TEXT PRIMARY KEY);
            """)
        self.available = True

    def sign(self, payload):
        return canonical({"payload":payload,"signature":base64.b64encode(self.key.sign(canonical(payload))).decode()})

    @staticmethod
    def verify(blob, public, kind):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        if len(blob)>LIMIT:
            raise ValueError("Package too large")
        obj = json.loads(blob)
        if set(obj)!={"payload","signature"} or not isinstance(obj["payload"],dict):
            raise ValueError("Invalid signed envelope")
        payload = obj["payload"]
        if payload.get("schema")!=1 or payload.get("kind")!=kind or payload.get("author")!=public:
            raise ValueError("Unexpected author/schema/kind")
        Ed25519PublicKey.from_public_bytes(un64(public)).verify(un64(obj["signature"]),canonical(payload))
        if kind=="manifest":
            if set(payload)!={"schema","kind","author","sequence","packages"} or type(payload["sequence"]) is not int or payload["sequence"]<0:
                raise ValueError("Invalid manifest sequence")
            items = payload["packages"]
            if not isinstance(items,list) or len(items)>64 or len(items)!=len(set(items)) or not all(isinstance(x,str) and re.fullmatch("[a-f0-9]{64}",x) for x in items):
                raise ValueError("Invalid manifest hashes")
        else:
            if set(payload)!={"schema","kind","author","name","document"} or not isinstance(payload["name"],str) or not re.fullmatch("[a-z0-9_-]{1,60}",payload["name"]):
                raise ValueError("Invalid route package")
            doc = payload["document"]
            if not isinstance(doc,dict) or set(doc)!=set(FIELDS):
                raise ValueError("Invalid route fields")
            if not all(isinstance(doc[k],str) and doc[k].strip() and len(doc[k])<=3000 for k in FIELDS[:-1]):
                raise ValueError("Invalid route text")
            if not isinstance(doc["related"],list) or len(doc["related"])>12 or not all(isinstance(x,str) and len(x)<61 for x in doc["related"]):
                raise ValueError("Invalid related routes")
        return payload

    def put(self, blob):
        h = digest(blob)
        temporary = self.objects / (h+".tmp")
        temporary.write_bytes(blob)
        temporary.replace(self.objects / (h+".json"))
        return h

    def publish(self, name, expected):
        with self.lock,self.store.lock:
            row = self.store.db.execute("SELECT digest,document,status FROM routes WHERE name=?",(name,)).fetchone()
            if not row or row[0]!=expected or row[2]!="active":
                raise ValueError("현재 버전을 로컬에서 검토한 경로만 공유할 수 있습니다.")
            if self.store.db.execute("SELECT COUNT(*) FROM published").fetchone()[0]>=64:
                raise ValueError("Feed capacity reached (64)")
            blob = self.sign(dict(schema=1,kind="route",author=self.public,name=name,document=json.loads(row[1])))
            h = self.put(blob)
            with self.store.db:
                self.store.db.execute("INSERT OR IGNORE INTO published VALUES(?)",(h,))
            self.write_manifest()
        return {"hash":h}

    def write_manifest(self):
        with self.store.lock,self.store.db:
            row = self.store.db.execute("SELECT value FROM control WHERE key='mesh_sequence'").fetchone()
            seq = int(row[0])+1 if row else 1
            hashes = [r[0] for r in self.store.db.execute("SELECT hash FROM published ORDER BY hash")]
            self.store.db.execute("INSERT OR REPLACE INTO control VALUES('mesh_sequence',?)",(str(seq),))
        blob = self.sign(dict(schema=1,kind="manifest",author=self.public,sequence=seq,packages=hashes))
        temporary = self.directory / "manifest.tmp"
        temporary.write_bytes(blob)
        temporary.replace(self.directory / "manifest.json")

    def pair(self, url, public):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        url = validate_url(url)
        Ed25519PublicKey.from_public_bytes(un64(public))
        pid = digest(un64(public))
        if public==self.public:
            raise ValueError("Cannot pair with self")
        with self.lock,self.store.lock,self.store.db:
            if self.store.db.execute("SELECT COUNT(*) FROM peers").fetchone()[0]>=16 and not self.store.db.execute("SELECT 1 FROM peers WHERE id=?",(pid,)).fetchone():
                raise ValueError("Peer limit (16)")
            self.store.db.execute("INSERT INTO peers(id,url,public) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET url=excluded.url,enabled=1",(pid,url,public))
        return {"peer":pid}

    def sync(self, pid):
        # Network waits never hold the supervisor lock, so emergency stop stays responsive.
        with self.lock:
            with self.store.lock:
                peer = self.store.db.execute("SELECT url,public,sequence,enabled,manifest_hash FROM peers WHERE id=?",(pid,)).fetchone()
            if not peer or not peer[3]:
                raise ValueError("Peer disabled or unknown")
            url,public,previous,_,previous_hash = peer
            raw = fetch(url+"/manifest")
            manifest = self.verify(raw,public,"manifest")
            mh = digest(canonical(manifest))
            seq = manifest["sequence"]
            if seq<previous or (seq==previous and mh!=previous_hash):
                raise ValueError("Manifest rollback/conflicting sequence rejected")
            received = repaired = 0
            # Bound a single UI request; repeated syncs progress through a large feed.
            pending = []
            for h in manifest["packages"]:
                path = self.objects / (h+".json")
                if not path.exists() or digest(path.read_bytes())!=h:
                    pending.append(h)
            for h in pending[:4]:
                blob = fetch(url+"/packages/"+h)
                if digest(blob)!=h:
                    raise ValueError("Package hash mismatch")
                payload = self.verify(blob,public,"route")
                with self.store.lock:
                    old = self.store.db.execute("SELECT 1 FROM packages WHERE hash=?",(h,)).fetchone()
                self.put(blob)
                with self.store.lock,self.store.db:
                    self.store.db.execute("INSERT OR IGNORE INTO packages VALUES(?,?,?,?,?)",(h,pid,payload["name"],"quarantine",time.time()))
                repaired += int(bool(old))
                received += int(not old)
            with self.store.lock,self.store.db:
                self.store.db.execute("UPDATE peers SET sequence=?,manifest_hash=? WHERE id=?",(seq,mh,pid))
            return dict(received=received,repaired=repaired,remaining=max(0,len(pending)-4))

    def read_package(self, h):
        if not isinstance(h,str) or not re.fullmatch("[a-f0-9]{64}",h):
            raise ValueError("Invalid package hash")
        with self.store.lock:
            row = self.store.db.execute("SELECT p.public FROM packages k JOIN peers p ON k.peer=p.id WHERE k.hash=? AND p.enabled=1",(h,)).fetchone()
        if not row:
            raise ValueError("Unknown package or disabled peer")
        blob = (self.objects / (h+".json")).read_bytes()
        if digest(blob)!=h:
            raise ValueError("Package corrupted; synchronize with original peer to restore")
        return self.verify(blob,row[0],"route")

    def adopt(self, h):
        with self.lock:
            package = self.read_package(h)
            # Immutable version namespace prevents replacement of a previously reviewed version.
            name = "peer-"+h[:20]
            result = self.c.growth.propose(name,**package["document"])
            with self.store.lock,self.store.db:
                self.store.db.execute("UPDATE packages SET status='candidate_imported' WHERE hash=?",(h,))
            return result

    def snapshot(self):
        if not self.available:
            return {"available":False,"reason":"선택 의존성 cryptography를 설치하면 서명 공유가 활성화됩니다."}
        with self.store.lock:
            peers = [dict(zip(("id","url","public","sequence","enabled"),r)) for r in self.store.db.execute("SELECT id,url,public,sequence,enabled FROM peers")]
            packages = [dict(zip(("hash","peer","name","status","at"),r)) for r in self.store.db.execute("SELECT * FROM packages ORDER BY at DESC LIMIT 100")]
            published = [r[0] for r in self.store.db.execute("SELECT hash FROM published")]
        return dict(available=True,public=self.public,fingerprint=digest(un64(self.public)),peers=peers,packages=packages,published=published)

    def action(self, action, data):
        if not self.available:
            raise ValueError("Install optional cryptography dependency first")
        if action=="sync":
            return self.sync(data["peer"])
        if action=="preview":
            return self.read_package(data["hash"])
        if action=="pair":
            return self.pair(data["url"],data["public"])
        if action=="disable":
            with self.lock,self.store.lock,self.store.db:
                self.store.db.execute("UPDATE peers SET enabled=0 WHERE id=?",(data["peer"],))
            return {"disabled":True}
        if action=="publish":
            return self.publish(data["name"],data["digest"])
        if action=="adopt":
            return self.adopt(data["hash"])
        raise ValueError("Unknown mesh action")
