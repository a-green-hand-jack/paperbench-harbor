"""Auditable literature discovery for PaperSmith candidate screening.

Discovery only finds leads.  It is deliberately separate from screening because
neither LKM nor a bibliographic API can establish the paper licence, recoverable
TeX source, or code-evidence branch required by a PaperRecon task.  The caller
persists the returned snapshot and hands its compact lead list to the OpenCode
screening agent, which independently verifies every selected paper.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree

DEFAULT_LKM_TIMEOUT_SECONDS = 30
DEFAULT_LKM_TOP_K = 50
_ARXIV_ID_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arXiv:)?(\d{4}\.\d{4,5})(?:v\d+)?")


@dataclass(frozen=True)
class LiteratureHit:
    """One normalized discovery lead, without asserting it is eligible."""

    source: str
    identifier: str
    title: str
    url: str = ""
    arxiv_id: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DiscoveryRecord:
    query: str
    provider: str
    status: str
    hits: tuple[LiteratureHit, ...] = ()
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "provider": self.provider,
            "status": self.status,
            "hits": [hit.as_dict() for hit in self.hits],
            "error": self.error,
        }


@dataclass(frozen=True)
class DiscoverySnapshot:
    """The exact, reviewable result of one screening discovery pass."""

    generated_at: str
    lkm_client_version: str
    records: tuple[DiscoveryRecord, ...]
    fallback_used: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "provider": "bohrium-lkm",
            "lkm_client_version": self.lkm_client_version,
            "fallback_used": self.fallback_used,
            "records": [record.as_dict() for record in self.records],
        }

    def prompt_context(self, *, limit: int = 100) -> str:
        """Return compact leads suitable for an agent prompt, never raw output."""

        rows: list[str] = []
        for record in self.records:
            if record.status != "ok":
                rows.append(
                    f"- {record.provider} query failed: {record.query!r}: {record.error}"
                )
                continue
            for hit in record.hits:
                label = hit.arxiv_id or hit.identifier or "unidentified"
                details = f" ({hit.url})" if hit.url else ""
                rows.append(f"- [{hit.source}] {label}: {hit.title}{details}")
                if len(rows) >= limit:
                    return "\n".join(rows)
        return "\n".join(rows)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


class LiteratureDiscoveryError(RuntimeError):
    """An external literature service did not produce a usable response."""


def _arxiv_id(*values: object) -> str:
    for value in values:
        match = _ARXIV_ID_RE.search(str(value or ""))
        if match:
            return match.group(1)
    return ""


def _bohr_json(stdout: str) -> dict[str, Any]:
    """Accept normal JSON or the final JSON line emitted by older bohr versions."""

    text = stdout.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
        for line in reversed(text.splitlines()):
            if line.lstrip().startswith("{"):
                try:
                    payload = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
    if not isinstance(payload, dict):
        raise LiteratureDiscoveryError("bohr returned invalid JSON")
    return payload


def _lkm_hit(value: dict[str, Any]) -> LiteratureHit:
    identifier = str(value.get("id") or value.get("paperId") or value.get("doi") or "")
    url = str(value.get("paperUrl") or value.get("url") or "")
    title = str(
        value.get("en_title")
        or value.get("enName")
        or value.get("zh_title")
        or value.get("zhName")
        or ""
    ).strip()
    return LiteratureHit(
        source="bohrium-lkm",
        identifier=identifier,
        title=title,
        url=url,
        arxiv_id=_arxiv_id(identifier, url, title),
    )


class BohriumLKM:
    """Small safe boundary around the official ``bohr lkm search`` command."""

    def __init__(
        self,
        *,
        timeout: int = DEFAULT_LKM_TIMEOUT_SECONDS,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.timeout = timeout
        self._runner = runner
        self._which = which

    def version(self) -> str:
        if self._which("bohr") is None:
            return "unavailable"
        try:
            result = self._runner(
                ["bohr", "version"], capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return "unavailable"
        if result.returncode != 0 or not result.stdout.strip():
            return "unknown"
        try:
            payload = _bohr_json(result.stdout)
        except LiteratureDiscoveryError:
            return result.stdout.strip()
        data = payload.get("data")
        meta = payload.get("meta")
        if isinstance(data, dict) and isinstance(data.get("version"), str):
            return data["version"]
        if isinstance(meta, dict) and isinstance(meta.get("cli_version"), str):
            return meta["cli_version"]
        return "unknown"

    def search(
        self, query: str, *, top_k: int = DEFAULT_LKM_TOP_K, scopes: str = "claim,conclusion,abstract"
    ) -> tuple[LiteratureHit, ...]:
        if self._which("bohr") is None:
            raise LiteratureDiscoveryError("bohr CLI not found")
        try:
            result = self._runner(
                [
                    "bohr", "lkm", "search", query, "--top-k", str(top_k), "--scopes", scopes,
                    "--yes", "-o", "json",
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise LiteratureDiscoveryError(f"bohr command timed out after {self.timeout}s") from error
        except OSError as error:
            raise LiteratureDiscoveryError(f"could not run bohr: {error}") from error
        payload = _bohr_json(result.stdout)
        if not payload.get("ok", False):
            error = payload.get("error") or {}
            if isinstance(error, dict):
                error = error.get("message") or error.get("code") or error
            raise LiteratureDiscoveryError(str(error) or f"bohr exited {result.returncode}")
        data = payload.get("data") or {}
        papers = data.get("papers") or {}
        values = papers.values() if isinstance(papers, dict) else papers
        if not isinstance(values, (list, tuple)) and not hasattr(values, "__iter__"):
            raise LiteratureDiscoveryError("bohr response has no papers collection")
        return tuple(_lkm_hit(item) for item in values if isinstance(item, dict))


def _dedupe(hits: list[LiteratureHit]) -> tuple[LiteratureHit, ...]:
    seen: set[str] = set()
    deduped: list[LiteratureHit] = []
    for hit in hits:
        key = (hit.arxiv_id or hit.identifier or hit.title.casefold()).strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return tuple(deduped)


def search_arxiv(query: str, *, limit: int = 50, timeout: int = 30) -> tuple[LiteratureHit, ...]:
    """Search arXiv's public Atom API for LKM fallback leads."""

    url = "https://export.arxiv.org/api/query?" + urlencode(
        {"search_query": f"all:{query}", "start": 0, "max_results": limit}
    )
    try:
        with urlopen(url, timeout=timeout) as response:
            root = ElementTree.fromstring(response.read())
    except Exception as error:
        raise LiteratureDiscoveryError(f"arXiv fallback failed: {error}") from error
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    hits: list[LiteratureHit] = []
    for entry in root.findall("atom:entry", namespace):
        url_value = (entry.findtext("atom:id", default="", namespaces=namespace) or "").strip()
        title = " ".join((entry.findtext("atom:title", default="", namespaces=namespace) or "").split())
        arxiv_id = _arxiv_id(url_value)
        hits.append(LiteratureHit("arxiv", arxiv_id or url_value, title, url_value, arxiv_id))
    return tuple(hits)


def search_semantic_scholar(
    query: str, *, limit: int = 50, timeout: int = 30
) -> tuple[LiteratureHit, ...]:
    """Search Semantic Scholar's public graph endpoint for fallback leads."""

    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urlencode(
        {"query": query, "limit": limit, "fields": "paperId,title,externalIds,url"}
    )
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read())
    except Exception as error:
        raise LiteratureDiscoveryError(f"Semantic Scholar fallback failed: {error}") from error
    records = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise LiteratureDiscoveryError("Semantic Scholar fallback returned no data list")
    hits: list[LiteratureHit] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        external_ids = record.get("externalIds") or {}
        arxiv_id = str(external_ids.get("ArXiv") or "") if isinstance(external_ids, dict) else ""
        identifier = str(record.get("paperId") or arxiv_id or "")
        hits.append(
            LiteratureHit(
                "semantic-scholar", identifier, str(record.get("title") or ""),
                str(record.get("url") or ""), arxiv_id,
            )
        )
    return tuple(hits)


def fallback_search(query: str, *, limit: int = DEFAULT_LKM_TOP_K) -> tuple[LiteratureHit, ...]:
    """Use both independent public indexes when LKM cannot answer a query."""

    errors: list[str] = []
    hits: list[LiteratureHit] = []
    for search in (search_arxiv, search_semantic_scholar):
        try:
            hits.extend(search(query, limit=limit))
        except LiteratureDiscoveryError as error:
            errors.append(str(error))
    if not hits:
        raise LiteratureDiscoveryError("; ".join(errors) or "all fallback searches failed")
    return _dedupe(hits)


def discover_literature(
    queries: tuple[str, ...],
    *,
    lkm: BohriumLKM | None = None,
    fallback: Callable[[str], tuple[LiteratureHit, ...]] = fallback_search,
    top_k: int = DEFAULT_LKM_TOP_K,
) -> DiscoverySnapshot:
    """Search LKM first and independently fall back per failed query."""

    service = lkm or BohriumLKM()
    records: list[DiscoveryRecord] = []
    used_fallback = False
    for query in queries:
        try:
            records.append(
                DiscoveryRecord(query, "bohrium-lkm", "ok", service.search(query, top_k=top_k))
            )
        except LiteratureDiscoveryError as error:
            used_fallback = True
            records.append(DiscoveryRecord(query, "bohrium-lkm", "failed", error=str(error)))
            try:
                records.append(
                    DiscoveryRecord(
                        query, "arxiv+semantic-scholar", "ok", _dedupe(list(fallback(query)))
                    )
                )
            except LiteratureDiscoveryError as fallback_error:
                records.append(
                    DiscoveryRecord(
                        query, "arxiv+semantic-scholar", "failed", error=str(fallback_error)
                    )
                )
    return DiscoverySnapshot(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        lkm_client_version=service.version(),
        records=tuple(records),
        fallback_used=used_fallback,
    )
