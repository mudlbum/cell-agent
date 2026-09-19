"""Versioned retrieval routes. Only operator-reviewed evidence affects ratings."""
import hashlib
import json
import re
import time

from cell_agent import dump, function, STR


class Growth:
    def __init__(self, store):
        self.store = store
        with store.lock, store.db:
            store.db.executescript("""
                CREATE TABLE IF NOT EXISTS routes(
                    name TEXT PRIMARY KEY, at REAL, digest TEXT, document TEXT,
                    status TEXT DEFAULT 'candidate');
                CREATE TABLE IF NOT EXISTS route_reviews(
                    id INTEGER PRIMARY KEY, at REAL, name TEXT, digest TEXT,
                    verdict TEXT, evidence TEXT, run TEXT);
                CREATE TABLE IF NOT EXISTS evaluations(
                    id INTEGER PRIMARY KEY, at REAL, run TEXT UNIQUE, verdict TEXT, evidence TEXT);
            """)

    @staticmethod
    def tools():
        return [
            function("find_routes", "Find knowledge-acquisition procedures and operator-reviewed outcomes. Candidate or stale routes require verification; ratings are sparse evidence, not calibrated probabilities.", {"query": STR}),
            function("propose_route", "Propose a versioned way to obtain and verify knowledge. Does not activate it or prove it works. Store pointers and recovery queries, not entire documents.",
                     {"name": STR, "problem": STR, "locator": STR, "strategy": STR,
                      "verification": STR, "fallback": STR, "related": {"type": "array", "items": STR}})
        ]

    def propose(self, name, problem, locator, strategy, verification, fallback, related):
        if not re.fullmatch(r"[a-z0-9_-]{1,60}", name):
            raise ValueError("Use an ASCII slug for route name")
        document = dict(problem=problem, locator=locator, strategy=strategy,
                        verification=verification, fallback=fallback, related=related)
        if not all(isinstance(v, str) and v.strip() and len(v) <= 3000
                   for v in (problem, locator, strategy, verification, fallback)):
            raise ValueError("Route text fields must be nonempty and <= 3000 characters")
        if not isinstance(related, list) or len(related) > 12 or not all(isinstance(v, str) and len(v) < 61 for v in related):
            raise ValueError("At most 12 related route names")
        encoded = dump(document)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.store.lock, self.store.db:
            old = self.store.db.execute("SELECT digest FROM routes WHERE name=?", (name,)).fetchone()
            if old and old[0] == digest:
                return {"name": name, "digest": digest, "unchanged": True}
            if not old and self.store.db.execute("SELECT COUNT(*) FROM routes").fetchone()[0] >= 500:
                raise ValueError("Route capacity reached (500)")
            self.store.db.execute("INSERT OR REPLACE INTO routes VALUES(?,?,?,?,?)",
                                  (name, time.time(), digest, encoded, "candidate"))
        return {"name": name, "digest": digest, "status": "candidate"}

    def find(self, query=""):
        tokens = set(re.findall(r"[\w-]+", query.lower()))
        result = []
        with self.store.lock:
            rows = self.store.db.execute("SELECT name,at,digest,document,status FROM routes").fetchall()
            for name, at, digest, document, status in rows:
                data = json.loads(document)
                text = (name + " " + document).lower()
                relevance = sum(t in text for t in tokens)
                if tokens and not relevance:
                    continue
                counts = dict(self.store.db.execute("SELECT verdict,COUNT(*) FROM route_reviews WHERE name=? AND digest=? GROUP BY verdict",
                                                    (name, digest)).fetchall())
                latest = self.store.db.execute("SELECT MAX(at) FROM route_reviews WHERE name=? AND digest=?", (name, digest)).fetchone()[0]
                good, bad = counts.get("pass", 0), counts.get("fail", 0)
                result.append(dict(name=name, digest=digest, status=status, **data,
                    successes=good, failures=bad, score=(good + 1) / (good + bad + 2),
                    reviewed_at=latest, stale=latest is None or time.time() - latest > 30 * 86400,
                    relevance=relevance, created_at=at))
        result.sort(key=lambda x: (x["relevance"], x["status"] == "active", x["score"]), reverse=True)
        return result[:50 if not query else 10]

    def review(self, name, digest, verdict, evidence, run=""):
        if verdict not in {"pass", "fail"} or not isinstance(evidence, str) or not 5 <= len(evidence.strip()) <= 8000:
            raise ValueError("A pass/fail verdict requires concrete evidence (5-8000 characters)")
        with self.store.lock, self.store.db:
            row = self.store.db.execute("SELECT digest FROM routes WHERE name=?", (name,)).fetchone()
            if not row or row[0] != digest:
                raise ValueError("Route changed since review; reload before reviewing")
            if self.store.db.execute("SELECT 1 FROM route_reviews WHERE name=? AND digest=? AND verdict=? AND evidence=? AND run=?",
                                     (name, digest, verdict, evidence, run)).fetchone():
                return {"recorded": True, "duplicate": True}
            self.store.db.execute("INSERT INTO route_reviews(at,name,digest,verdict,evidence,run) VALUES(?,?,?,?,?,?)",
                                  (time.time(), name, digest, verdict, evidence, run))
            self.store.db.execute("UPDATE routes SET status=? WHERE name=?",
                                  ("active" if verdict == "pass" else "needs_review", name))
        return {"recorded": True, "note": "Operator observation, not universal proof of competence"}

    def evaluate(self, run, verdict, evidence):
        if verdict not in {"pass", "fail"} or not isinstance(evidence, str) or not 5 <= len(evidence.strip()) <= 8000:
            raise ValueError("Evaluation requires pass/fail and evidence")
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT OR REPLACE INTO evaluations(at,run,verdict,evidence) VALUES(?,?,?,?)",
                                  (time.time(), run, verdict, evidence))
