"""The provenance manifest must not depend on where the build ran.

`write_source_manifest`'s docstring has always promised this -- "portable
across machines: the same fixed input must produce the same manifest regardless
of the absolute output directory" -- but `material_provenance` sources were
written absolute, so `v0.3.1` shipped 273 manifests naming
`/home/user/dev/paperbench-data/...`.

Two consequences, and the second is why this went unnoticed: the build host's
directory layout ended up in a public dataset, and byte-identical reproduction
required converting from that same absolute path. The audit's determinism check
converts twice from one source path, so it structurally could not see this.
"""

from __future__ import annotations

import json
from pathlib import Path

from paperbench_harbor.common.manifest import write_source_manifest


def _fixture(root: Path) -> tuple[Path, Path, Path]:
    source_root = root / "upstream"
    (source_root / "paper_1" / "resources").mkdir(parents=True)
    upstream = source_root / "paper_1" / "resources" / "template.tex"
    upstream.write_text("\\documentclass{article}", encoding="utf-8")

    task_dir = root / "out" / "pwb-0001"
    materials = task_dir / "environment" / "materials"
    materials.mkdir(parents=True)
    staged = materials / "template.tex"
    staged.write_text("\\documentclass{article}", encoding="utf-8")
    return source_root, task_dir, staged


def _write(root: Path, *, source_root: Path | None) -> dict:
    src_root, task_dir, staged = _fixture(root)
    destination = task_dir / "tests" / "private" / "source_manifest.json"
    write_source_manifest(
        destination=destination,
        benchmark="PaperWrite-Bench",
        upstream_id="paper_1",
        protocol="short",
        upstream_revision="rev",
        public_files=[staged],
        private_files=[],
        root=task_dir,
        source_root=src_root if source_root is not None else None,
        material_provenance={staged: ("upstream", src_root / "paper_1/resources/template.tex")},
    )
    return json.loads(destination.read_text(encoding="utf-8"))


def test_provenance_sources_are_relative_to_the_source_root(tmp_path: Path) -> None:
    payload = _write(tmp_path, source_root=tmp_path)
    entry = payload["material_provenance"]["environment/materials/template.tex"]
    assert entry["source_path"] == "paper_1/resources/template.tex"
    assert str(tmp_path) not in json.dumps(payload)


def test_the_same_input_from_two_directories_produces_one_manifest(tmp_path: Path) -> None:
    """The property the docstring promises, now actually checked.

    Two build trees with identical contents at different absolute paths -- the
    case the determinism check cannot construct, because it converts twice from
    the same source.
    """
    first = _write(tmp_path / "build-a", source_root=tmp_path / "build-a")
    second = _write(tmp_path / "somewhere" / "else" / "b", source_root=tmp_path)
    assert first == second


def test_a_source_outside_the_root_keeps_its_absolute_path(tmp_path: Path) -> None:
    """Not silently rewritten: a conversion reaching outside its source root is
    a fact the manifest should record, not hide."""
    src_root, task_dir, staged = _fixture(tmp_path)
    outside = tmp_path / "elsewhere.tex"
    outside.write_text("x", encoding="utf-8")
    destination = task_dir / "tests" / "private" / "source_manifest.json"
    write_source_manifest(
        destination=destination,
        benchmark="PaperWrite-Bench",
        upstream_id="paper_1",
        protocol="short",
        upstream_revision="rev",
        public_files=[staged],
        private_files=[],
        root=task_dir,
        source_root=src_root,
        material_provenance={staged: ("upstream", outside)},
    )
    payload = json.loads(destination.read_text(encoding="utf-8"))
    entry = payload["material_provenance"]["environment/materials/template.tex"]
    assert entry["source_path"] == str(outside)


def test_file_hashes_stay_keyed_by_task_relative_paths(tmp_path: Path) -> None:
    payload = _write(tmp_path, source_root=tmp_path)
    assert list(payload["public_file_hashes"]) == ["environment/materials/template.tex"]
