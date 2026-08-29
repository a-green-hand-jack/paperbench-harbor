"""Deterministic, cutoff-aware scholarly-search index and HTTP sidecar."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
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


def semantic_scholar_title_search(
    title_query: str, year_hint: int | None = None, cutoff_date: str | None = None
) -> SearchRecord | None:
    """Match a candidate title using the upstream Semantic Scholar API flow."""
    params = urllib.parse.urlencode(
        {
            "query": title_query,
            "limit": 3,
            "fields": "title,year,abstract,authors,venue,citationCount,journal,publicationDate",
        }
    )
    request = urllib.request.Request(
        f"https://api.semanticscholar.org/graph/v1/paper/search?{params}",
        headers={"X-API-KEY": os.environ["SEMANTIC_SCHOLAR_API_KEY"]}
        if os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
    except (OSError, ValueError):
        return None

    cutoff = _parse_cutoff(cutoff_date)
    best: tuple[float, SearchRecord] | None = None
    for item in payload.get("data", []):
        title = item.get("title")
        if not title or not _date_allowed(item.get("publicationDate"), item.get("year"), cutoff):
            continue
        score = _similarity(title_query, title)
        if year_hint and item.get("year") == year_hint:
            score += 0.1
        record = SearchRecord(
            title=title,
            abstract=item.get("abstract") or "",
            year=item.get("year"),
            url=(item.get("openAccessPdf") or {}).get("url", "") if isinstance(item.get("openAccessPdf"), dict) else "",
            source="semantic_scholar",
        )
        if score > 0.7 and (best is None or score > best[0]):
            best = (score, record)
    return best[1] if best else None


def _similarity(left: str, right: str) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, left.lower(), right.lower()).ratio()


def _parse_cutoff(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    parts = [int(part) for part in value.split("-")]
    return (parts[0], parts[1] if len(parts) > 1 else 12, parts[2] if len(parts) > 2 else 1)


def _date_allowed(publication_date: str | None, year: int | None, cutoff: tuple[int, int, int] | None) -> bool:
    if cutoff is None:
        return True
    if publication_date:
        try:
            parts = [int(part) for part in publication_date.split("-")]
            published = (parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
            return published < cutoff
        except ValueError:
            pass
    return year is None or (year, 1, 1) < cutoff


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
            source = params.get("source", ["local"])[0]
            if source == "semantic_scholar":
                result = semantic_scholar_title_search(query, cutoff_date=cutoff or None)
                results = [result] if result else []
            else:
                results = search(records, query, int(cutoff.split("-", 1)[0]) if cutoff else None, limit)
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
