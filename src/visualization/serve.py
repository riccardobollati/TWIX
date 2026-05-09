"""visualization.md §8 — local HTTP server for the extraction visualizer.

Usage:
    python src/visualization/serve.py results/<doc>__<model>.json [--port 8765]
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"

# Try to import the schema validator; degrade gracefully if unavailable.
try:
    _repo_root = Path(__file__).resolve().parents[2]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from src.eval.score import validate_tree
except ImportError:
    validate_tree = None  # type: ignore


def _load_and_validate(json_path: Path) -> dict:
    text = json_path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"Error: JSON parse failed: {e}")

    if validate_tree is not None:
        errors = validate_tree(data)
        if errors:
            print("Warning: JSON failed schema validation:")
            for e in errors[:10]:
                print(f"  - {e}")
            print("Serving anyway (this is a read-only viewer).")

    records = data.get("records")
    if not isinstance(records, list) or len(records) == 0:
        print("Warning: 'records' is empty or missing — page will show an error message.")

    return data


def make_handler(json_data: dict):
    json_bytes = json.dumps(json_data, ensure_ascii=False).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # suppress access log noise

        def do_GET(self):
            path = self.path.split("?")[0]

            if path == "/data.json":
                self._send(200, "application/json", json_bytes)
                return

            # Map "/" to index.html
            if path == "/":
                path = "/index.html"

            static_path = STATIC_DIR / path.lstrip("/")
            if static_path.exists() and static_path.is_file():
                mime = mimetypes.guess_type(str(static_path))[0] or "application/octet-stream"
                self._send(200, mime, static_path.read_bytes())
            else:
                self._send(404, "text/plain", b"Not found")

        def _send(self, code: int, content_type: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Serve the extraction visualizer.")
    parser.add_argument("json_path", help="Path to a stage-1 or stage-2 JSON file.")
    parser.add_argument("--port", type=int, default=8765, help="Port (default 8765).")
    args = parser.parse_args()

    json_path = Path(args.json_path)
    if not json_path.exists():
        sys.exit(f"Error: file not found: {json_path}")

    print(f"Loading {json_path} ...")
    data = _load_and_validate(json_path)
    doc_name = data.get("doc_name", str(json_path.stem))
    n_records = len(data.get("records") or [])
    print(f"  doc_name={doc_name!r}, {n_records} record(s)")

    handler = make_handler(data)
    server = HTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://localhost:{args.port}/"
    print(f"Visualization ready at {url}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
