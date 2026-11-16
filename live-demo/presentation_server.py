"""Serve the prepared project presentation using only the Python standard library."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import webbrowser

HERE = Path(__file__).resolve().parent
FILES = {
    "/": ("presentation.html", "text/html; charset=utf-8"),
    "/presentation.html": ("presentation.html", "text/html; charset=utf-8"),
    "/presentation.js": ("presentation.js", "text/javascript; charset=utf-8"),
    "/presentation.css": ("presentation.css", "text/css; charset=utf-8"),
    "/live.css": ("live.css", "text/css; charset=utf-8"),
    "/presentation-data.json": ("presentation-data.json", "application/json; charset=utf-8"),
}
FILES["/recordings/manifest.json"] = ("recordings/manifest.json", "application/json; charset=utf-8")
for index in range(6):
    name = f"recordings/scenario-{index}.json.gz"
    FILES[f"/{name}"] = (name, "application/json; charset=utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path not in FILES:
            self.send_error(404)
            return
        name, mime = FILES[path]
        payload = (HERE / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        if name.endswith(".gz"):
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Prepared presentation at {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
