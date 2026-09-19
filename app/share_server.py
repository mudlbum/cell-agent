"""Read-only signed feed. Explicit separate launch; never exposes the dashboard or keys."""
import argparse
import json
from pathlib import Path
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_feed(state, host="127.0.0.1", port=0):
    directory = Path(state).resolve() / "mesh"
    class Feed(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            try:
                raw = (directory / "manifest.json").read_bytes()
                if self.path=="/manifest":
                    blob=raw
                elif re.fullmatch(r"/packages/[a-f0-9]{64}",self.path):
                    h = self.path.rsplit("/",1)[1]
                    if h not in json.loads(raw)["payload"]["packages"]:
                        raise ValueError("Not published")
                    blob = (directory / "objects" / (h+".json")).read_bytes()
                else:
                    raise ValueError("Not found")
                if len(blob)>131072:
                    raise ValueError("Oversize")
                self.send_response(200)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(blob)))
                self.send_header("X-Content-Type-Options","nosniff")
                self.end_headers()
                self.wfile.write(blob)
            except (OSError,ValueError,KeyError):
                self.send_error(404)
    server = ThreadingHTTPServer((host,port),Feed)
    server.daemon_threads = True
    return server


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state",default=str(Path(__file__).parent/"state-ui"))
    p.add_argument("--host",default="127.0.0.1")
    p.add_argument("--port",type=int,default=8766)
    a=p.parse_args()
    server=make_feed(a.state,a.host,a.port)
    print(f"Read-only feed: http://{a.host}:{a.port}; Internet peers require an HTTPS reverse proxy.",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
