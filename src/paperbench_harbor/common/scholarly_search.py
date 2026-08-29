"""Deterministic, cutoff-aware scholarly-search index and HTTP sidecar."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class SearchRecord:
    title: str
    abstract: str = ""
    year: int | None = None
    url: str = ""
    source: str = "local"


def load_index(path: Path) -> list[SearchRecord]:
    records: list[SearchRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        records.append(
            SearchRecord(
                title=str(item["title"]),
                abstract=str(item.get("abstract", "")),
                year=int(item["year"]) if item.get("year") is not None else None,
                url=str(item.get("url", "")),
                source=str(item.get("source", "local")),
            )
        )
    return records


def search(records: list[SearchRecord], query: str, cutoff_year: int | None, limit: int = 10) -> list[SearchRecord]:
    """Return deterministic token-overlap results published by the cutoff."""
    if limit < 1:
        return []
    tokens = {token.lower() for token in query.split() if token.strip()}
    candidates: list[tuple[int, int, str, SearchRecord]] = []
    for record in records:
        if cutoff_year is not None and record.year is not None and record.year > cutoff_year:
            continue
        haystack = f"{record.title} {record.abstract}".lower()
        score = sum(token in haystack for token in tokens)
        if score:
            year = record.year or 0
            candidates.append((-score, -year, record.title.lower(), record))
    candidates.sort(key=lambda item: item[:3])
    return [item[3] for item in candidates[:limit]]


def serve(index: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    records = load_index(index)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/search":
                self.send_error(404)
                return
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            cutoff = params.get("cutoff_year", [""])[0]
            limit = int(params.get("limit", ["10"])[0])
            results = search(records, query, int(cutoff) if cutoff else None, limit)
            payload = {
                "query": query,
                "cutoff_year": int(cutoff) if cutoff else None,
                "results": [record.__dict__ for record in results],
            }
            encoded = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_args: object) -> None:
            return

    ThreadingHTTPServer((host, port), Handler).serve_forever()
