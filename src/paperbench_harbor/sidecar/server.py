"""HTTP wrapper around the PaperOrchestra scholarly-search implementation."""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _upstream_root() -> str:
    configured = os.environ.get("PAPER_ORCHESTRA_ROOT")
    if configured:
        return configured
    local_root = (
        Path(__file__).resolve().parents[1]
        / "vendor"
        / "paper_orchestra"
        / "upstream_pipeline"
    )
    if local_root.is_dir():
        return str(local_root)
    return "/workspace/paper_orchestra"


def _load_upstream():
    root = _upstream_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    from methods.agents.literature_review_agent import HybridLiteratureAgent
    from utils.scholar_utils import s2_title_search

    return HybridLiteratureAgent, s2_title_search


def _new_literature_agent(hybrid_agent):
    return hybrid_agent(
        idea_path="",
        experimental_log_path="",
        latex_template_path="",
        conference_guidelines_path="",
        output_dir="/tmp/paper_orchestra_sidecar",
    )


def serve(host: str, port: int) -> None:
    """Serve the upstream PaperOrchestra search contract."""

    hybrid_agent, s2_title_search = _load_upstream()

    class Handler(BaseHTTPRequestHandler):
        def _write_json(self, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._write_json({"status": "ok"})
                return
            self.send_error(404)

        def do_POST(self) -> None:
            if self.path not in {"/v1/enrich-title", "/v1/discover"}:
                self.send_error(404)
                return
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                if self.path == "/v1/discover":
                    from google.genai import types

                    agent = _new_literature_agent(hybrid_agent)
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
                    print("sidecar request endpoint=/v1/discover result=ok", flush=True)
                    return

                result = s2_title_search(
                    payload["title"], payload.get("year_hint"), payload.get("cutoff_date")
                )
                self._write_json({"result": result})
                print("sidecar request endpoint=/v1/enrich-title result=ok", flush=True)
            except (KeyError, TypeError, ValueError):
                self.send_error(400)
                print(f"sidecar request endpoint={self.path} result=bad-request", flush=True)
            except Exception as exc:  # noqa: BLE001 - keep upstream failures visible at the HTTP boundary
                self.send_error(502)
                print(
                    f"sidecar request endpoint={self.path} result=upstream-error type={type(exc).__name__}",
                    flush=True,
                )

        def log_message(self, *_args: object) -> None:
            return

    print(f"sidecar ready host={host} port={port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port)
