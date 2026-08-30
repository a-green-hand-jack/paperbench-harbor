"""HTTP wrapper around the PaperOrchestra scholarly-search implementation."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def serve(host: str, port: int) -> None:
    """Serve the upstream Semantic Scholar enrichment contract."""

    class Handler(BaseHTTPRequestHandler):
        def _write_json(self, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path not in {"/v1/enrich-title", "/v1/discover"}:
                self.send_error(404)
                return
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                if self.path == "/v1/discover":
                    sys.path.insert(0, "/workspace/paper_orchestra_search")
                    from google.genai import types
                    from methods.agents.literature_review_agent import HybridLiteratureAgent

                    agent = object.__new__(HybridLiteratureAgent)
                    agent.google_search_tool = types.Tool(google_search=types.GoogleSearch())
                    task = {
                        "section": payload.get("section", "Literature Review"),
                        "focus": payload["query"],
                        "context": payload.get("context", ""),
                        "search_type": payload.get("search_type", "exploration"),
                    }
                    outline = {
                        "intro_related_work_plan": {
                            "introduction_strategy": {
                                "problem_gap_hypothesis": payload.get("context", "")
                            }
                        }
                    }
                    candidates = agent._discover_candidates(
                        task, outline, payload.get("cutoff_date", "")
                    )
                    self._write_json({"candidates": [item.model_dump() for item in candidates]})
                    return

                try:
                    from paperbench_harbor.vendor.paper_orchestra.upstream_search.utils.scholar_utils import (
                        s2_title_search,
                    )
                except ModuleNotFoundError:
                    sys.path.insert(0, "/workspace/paper_orchestra_search")
                    from utils.scholar_utils import s2_title_search

                result = s2_title_search(
                    payload["title"], payload.get("year_hint"), payload.get("cutoff_date")
                )
                self._write_json({"result": result})
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
