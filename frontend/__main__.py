"""Run the frontend with `python3 -m frontend`.

Serves index.html and static/ as plain static files (no build step). By
default it injects `window.PROTORAG_DEFAULT_BACKEND_URL` into index.html
pointing at `--backend` (default `http://localhost:8000`), so the "Connect
with backend" gate button works with no manual Settings step for the common
"backend and frontend on the same machine, different ports" case. Pass
`--backend ""` to opt back out and get the plain same-origin default.
"""

import argparse
import functools
import http.server
import os


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(ROOT_DIR, "index.html")


def make_handler(backend_url):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=ROOT_DIR, **kwargs)

        def do_GET(self):
            if backend_url and self.path in ("/", "/index.html"):
                self._serve_index_with_backend_url()
            else:
                super().do_GET()

        def _serve_index_with_backend_url(self):
            with open(INDEX_PATH, "rb") as f:
                body = f.read()
            injection = (
                f'\n    <script>window.PROTORAG_DEFAULT_BACKEND_URL = {backend_url!r};</script>'
            ).encode("utf-8")
            body = body.replace(b"<head>", b"<head>" + injection, 1)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Serve the protoRAG+ frontend (index.html + static/).")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=4444, help="Bind port (default: 4444)")
    parser.add_argument(
        "--backend",
        default="http://localhost:8000",
        help="Backend URL to auto-wire into the page (default: http://localhost:8000). "
             "Pass an empty string to disable and fall back to same-origin.",
    )
    args = parser.parse_args()

    handler = make_handler(args.backend.strip())
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        print(f"Serving protoRAG+ frontend from {ROOT_DIR}")
        print(f"Open http://{args.host}:{args.port} in your browser.")
        if args.backend.strip():
            print(f"Auto-wired to backend at {args.backend.strip()} — Connect with backend should just work.")
        else:
            print("Set the Backend URL in Settings to wherever `python -m backend` / uvicorn is running.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
