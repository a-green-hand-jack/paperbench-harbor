import json
import shutil
import sys
from pathlib import Path

from paperbench_harbor.sidecar import server
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
    assert "def _load_semantic_scholar_search" in source
    assert "def _load_gemini_literature_agent" in source


def test_semantic_scholar_loader_needs_only_the_runtime_subset(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "paper_orchestra" / "utils"
    runtime.mkdir(parents=True)
    source = Path("src/paperbench_harbor/vendor/paper_orchestra/upstream_pipeline/utils/scholar_utils.py")
    shutil.copy2(source, runtime / "scholar_utils.py")
    monkeypatch.setenv("PAPER_ORCHESTRA_ROOT", str(runtime.parent))
    sys.modules.pop("utils", None)
    sys.modules.pop("utils.scholar_utils", None)

    assert callable(server._load_semantic_scholar_search())


def test_task_image_installs_semantic_scholar_dependency() -> None:
    dockerfile = Path("src/paperbench_harbor/common/templates/environment.Dockerfile.j2")
    assert "requests thefuzz" in dockerfile.read_text(encoding="utf-8")
