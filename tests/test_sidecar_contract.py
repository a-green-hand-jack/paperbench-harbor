import json
from pathlib import Path

from paperbench_harbor.sidecar.server import serve


def test_upstream_search_source_is_vendored() -> None:
    source = Path("src/paperbench_harbor/vendor/paper_orchestra/upstream_search/utils/scholar_utils.py")
    assert source.is_file()
    assert "def s2_title_search" in source.read_text(encoding="utf-8")


def test_sidecar_request_schema_is_json() -> None:
    payload = {"title": "Paper", "year_hint": 2024, "cutoff_date": "2024-11"}
    assert json.loads(json.dumps(payload))["cutoff_date"] == "2024-11"
    assert callable(serve)


def test_sidecar_declares_credential_free_discovery_fallback() -> None:
    source = Path("src/paperbench_harbor/sidecar/server.py").read_text(encoding="utf-8")
    assert "def _semantic_scholar_discover" in source
    assert "semantic-scholar-fallback" in source
    assert "PAPER_ORCHESTRA_RESEARCH_CUTOFF" in source
