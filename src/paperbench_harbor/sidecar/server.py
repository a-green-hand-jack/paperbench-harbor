"""HTTP wrapper around the PaperOrchestra scholarly-search implementation."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def serve(host: str, port: int) -> None:
    """Serve the upstream Semantic Scholar enrichment contract."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/v1/enrich-title":
                self.send_error(404)
                return
            try:
                try:
                    from paperbench_harbor.vendor.paper_orchestra.upstream_search.utils.scholar_utils import (
                        s2_title_search,
                    )
                except ModuleNotFoundError:
                    sys.path.insert(0, "/workspace/paper_orchestra_search")
                    from utils.scholar_utils import s2_title_search

                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                result = s2_title_search(
                    payload["title"], payload.get("year_hint"), payload.get("cutoff_date")
                )
                body = json.dumps({"result": result}, ensure_ascii=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (KeyError, TypeError, ValueError):
                self.send_error(400)

        def log_message(self, *_args: object) -> None:
            return

    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port)
