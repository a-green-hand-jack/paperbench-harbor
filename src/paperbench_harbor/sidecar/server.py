"""HTTP wrapper around the PaperOrchestra scholarly-search implementation."""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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


def _research_cutoff() -> str:
    return os.environ.get("PAPER_ORCHESTRA_RESEARCH_CUTOFF", "2024-10-01")


def _has_gemini_credentials() -> bool:
    return bool(
        os.environ.get("GEMINI_API_KEY")
        or (
            os.environ.get("VERTEX_AI_PROJECT")
            and os.environ.get("VERTEX_AI_LOCATION")
        )
    )


def _is_before_cutoff(record: dict[str, object], cutoff: str) -> bool:
    date = str(record.get("publicationDate") or "")
    if date:
        return date < cutoff
    year = record.get("year")
    return not isinstance(year, int) or year < int(cutoff[:4])


def _semantic_scholar_discover(query: str, cutoff: str) -> list[dict[str, object]]:
    """Credential-free discovery path for task environments without Gemini."""

    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urlencode(
        {
            "query": query,
            "limit": 10,
            "fields": "title,authors,venue,year,abstract,publicationDate",
        }
    )
    headers = {"Accept": "application/json"}
    if api_key := os.environ.get("SEMANTIC_SCHOLAR_API_KEY"):
        headers["X-API-KEY"] = api_key
    with urlopen(Request(url, headers=headers), timeout=10) as response:  # nosec B310 - fixed HTTPS host
        payload = json.loads(response.read().decode("utf-8"))
    candidates = []
    for item in payload.get("data", []):
        if item.get("title") and _is_before_cutoff(item, cutoff):
            candidates.append(
                {
                    "title": item["title"],
                    "authors": item.get("authors", []),
                    "venue": item.get("venue"),
                    "year": item.get("year"),
                    "abstract": item.get("abstract"),
                    "source": "semantic-scholar-fallback",
                }
            )
    return candidates


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
                    cutoff = _research_cutoff()
                    if _has_gemini_credentials():
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
                        candidates = [
                            item.model_dump() if hasattr(item, "model_dump") else item
                            for item in agent._discover_candidates(task, outline, cutoff)
                        ]
                        mode = "gemini"
                    else:
                        candidates = _semantic_scholar_discover(payload["query"], cutoff)
                        mode = "semantic-scholar-fallback"
                    self._write_json(
                        {
                            "candidates": candidates,
                            "cutoff_date": cutoff,
                            "mode": mode,
                        }
                    )
                    print(f"sidecar request endpoint=/v1/discover result=ok mode={mode}", flush=True)
                    return

                result = s2_title_search(
                    payload["title"], payload.get("year_hint"), _research_cutoff()[:7]
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
