from __future__ import annotations

import json
import subprocess

import pytest

from paperbench_harbor.construction.core.literature import (
    BohriumLKM,
    LiteratureDiscoveryError,
    LiteratureHit,
    discover_literature,
)


def _payload(*, ok: bool = True) -> str:
    return json.dumps(
        {
            "ok": ok,
            "data": {
                "papers": {
                    "first": {
                        "id": "2401.01234",
                        "en_title": "A useful result",
                        "paperUrl": "https://arxiv.org/abs/2401.01234v2",
                    }
                }
            },
            "error": {"message": "not authenticated"},
        }
    )


def test_bohrium_search_normalizes_arxiv_hits() -> None:
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, _payload(), "")

    service = BohriumLKM(runner=runner, which=lambda _: "/usr/bin/bohr")
    hits = service.search("mathematical proof")

    assert hits[0].arxiv_id == "2401.01234"
    assert hits[0].title == "A useful result"


def test_invalid_lkm_json_is_a_clear_error() -> None:
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, "not json", "")

    service = BohriumLKM(runner=runner, which=lambda _: "/usr/bin/bohr")
    with pytest.raises(LiteratureDiscoveryError, match="invalid JSON"):
        service.search("physics")


def test_lkm_timeout_is_a_clear_error() -> None:
    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    service = BohriumLKM(runner=runner, which=lambda _: "/usr/bin/bohr")
    with pytest.raises(LiteratureDiscoveryError, match="timed out"):
        service.search("chemistry")


def test_failed_lkm_query_falls_back_and_records_both_outcomes() -> None:
    class BrokenLKM:
        def version(self):
            return "2.6.74"

        def search(self, query, *, top_k):
            raise LiteratureDiscoveryError("not authenticated")

    fallback_calls: list[str] = []

    def fallback(query: str):
        fallback_calls.append(query)
        return (
            LiteratureHit(
                "arxiv", "2401.01234", "A fallback paper", "https://arxiv.org/abs/2401.01234", "2401.01234"
            ),
        )

    snapshot = discover_literature(("proof systems",), lkm=BrokenLKM(), fallback=fallback)

    assert snapshot.fallback_used is True
    assert [record.status for record in snapshot.records] == ["failed", "ok"]
    assert fallback_calls == ["proof systems"]
    assert "not authenticated" in snapshot.prompt_context()
    assert "2401.01234" in snapshot.prompt_context()


def test_duplicate_leads_are_deduplicated_by_fallback() -> None:
    class BrokenLKM:
        def version(self):
            return "unknown"

        def search(self, query, *, top_k):
            raise LiteratureDiscoveryError("offline")

    snapshot = discover_literature(
        ("one",),
        lkm=BrokenLKM(),
        fallback=lambda _: (
            LiteratureHit("arxiv", "2401.01234", "One", arxiv_id="2401.01234"),
            LiteratureHit("semantic-scholar", "same", "One", arxiv_id="2401.01234"),
        ),
    )
    assert len(snapshot.records[-1].hits) == 1
