"""Content-addressed origin recovery, and the disagreement it can produce.

The point of `fidelity/origin.py` is that it reaches its conclusions from bytes
rather than from a declaration, so it can contradict one. These tests are
mostly about making it contradict things: a spec that names the wrong source, a
file whose content was quietly edited, upstream material that reached the
writer without being declared.
"""

from __future__ import annotations

from pathlib import Path

from paperbench_harbor.adapters.paperwrite_bench import spec as pwb_spec
from paperbench_harbor.adapters.paperwrite_bench.converter import (
    PaperWriteBenchConversionConfig,
    convert_paperwrite_bench,
)
from paperbench_harbor.adapters.paperwritingbench import spec as pwbw_spec
from paperbench_harbor.adapters.spec import (
    find_paper_dirs,
    predict_copies,
    rewritable_targets,
)
from paperbench_harbor.fidelity.origin import (
    compare_to_expectation,
    derive_origins,
    index_by_content,
)
from tests.test_paperwrite_bench_converter import _make_source as _make_pwb_source


def _convert(tmp_path: Path) -> tuple[Path, Path]:
    source = _make_pwb_source(tmp_path)
    out = tmp_path / "out"
    convert_paperwrite_bench(
        PaperWriteBenchConversionConfig(
            source=source, output_dir=out, overwrite=True, upstream_revision="rev"
        )
    )
    return source, out / "pwb-0001"


def test_index_groups_duplicate_content(tmp_path: Path) -> None:
    """Duplicates are a fact about the corpus, not an error.

    Upstream `code/` trees routinely carry several empty `__init__.py` files.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.py").write_text("", encoding="utf-8")
    (tmp_path / "a" / "two.py").write_text("", encoding="utf-8")
    (tmp_path / "a" / "three.py").write_text("x", encoding="utf-8")
    index = index_by_content(tmp_path)
    groups = sorted(sorted(paths) for paths in index.values())
    assert groups == [["a/one.py", "a/two.py"], ["a/three.py"]]


def test_every_writer_file_is_upstream_or_accounted_for(tmp_path: Path) -> None:
    source, task_dir = _convert(tmp_path)
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    report = derive_origins(task_dir, paper_dir, generated=pwb_spec.SPEC.generated_public)
    assert report.unexplained == []
    assert report.from_upstream
    assert report.checked == len(report.from_upstream) + len(report.generated_or_vendor)


def test_the_spec_agrees_with_the_bytes(tmp_path: Path) -> None:
    source, task_dir = _convert(tmp_path)
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    report = derive_origins(task_dir, paper_dir, generated=pwb_spec.SPEC.generated_public)
    expected = predict_copies(pwb_spec.SPEC, paper_dir, "short")
    assert compare_to_expectation(report, expected, paper_dir) == []


def test_edited_content_stops_being_upstream(tmp_path: Path) -> None:
    """The check the hash comparison exists for, reached without a declaration."""
    source, task_dir = _convert(tmp_path)
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    staged = task_dir / "environment" / "materials" / "research_overview.md"
    staged.write_text(staged.read_text(encoding="utf-8") + "\nsmuggled\n", encoding="utf-8")

    report = derive_origins(task_dir, paper_dir, generated=pwb_spec.SPEC.generated_public)
    assert "environment/materials/research_overview.md" in report.unexplained

    expected = predict_copies(pwb_spec.SPEC, paper_dir, "short")
    findings = compare_to_expectation(report, expected, paper_dir)
    assert any("does not have" in f for f in findings)


def test_a_spec_naming_the_wrong_source_is_caught(tmp_path: Path) -> None:
    """A declaration that disagrees with the bytes loses.

    This is the case a table-versus-table audit cannot reach: both tables can
    name the same wrong source and agree with each other.
    """
    source, task_dir = _convert(tmp_path)
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    report = derive_origins(task_dir, paper_dir, generated=pwb_spec.SPEC.generated_public)

    expected = predict_copies(pwb_spec.SPEC, paper_dir, "short")
    expected["environment/materials/research_overview.md"] = (
        paper_dir / "resources" / "research_overview_long.md"
    )
    findings = compare_to_expectation(report, expected, paper_dir)
    assert any("but the bytes came from" in f for f in findings)


def test_undeclared_upstream_content_is_reported(tmp_path: Path) -> None:
    """Upstream material reaching the writer that no rule claimed."""
    source, task_dir = _convert(tmp_path)
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    smuggled = task_dir / "environment" / "materials" / "extra.tex"
    smuggled.write_bytes((paper_dir / "original" / "main.tex").read_bytes())

    report = derive_origins(task_dir, paper_dir, generated=pwb_spec.SPEC.generated_public)
    expected = predict_copies(pwb_spec.SPEC, paper_dir, "short")
    findings = compare_to_expectation(report, expected, paper_dir)
    assert any("undeclared upstream content" in f for f in findings)


def test_a_generated_file_the_spec_calls_a_copy_is_reported(tmp_path: Path) -> None:
    source, task_dir = _convert(tmp_path)
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    report = derive_origins(task_dir, paper_dir, generated=pwb_spec.SPEC.generated_public)

    expected = predict_copies(pwb_spec.SPEC, paper_dir, "short")
    expected["environment/materials/AGENTS.md"] = paper_dir / "resources" / "template.tex"
    findings = compare_to_expectation(report, expected, paper_dir)
    assert any("the bytes are generated" in f for f in findings)


def test_ground_truth_staged_publicly_is_not_this_module_s_job(tmp_path: Path) -> None:
    """Content addressing cannot see a leak, by construction.

    Ground truth staged into the writer environment is a perfect content match
    to its upstream source, so it reads as a faithful copy. `audit.py`'s
    verifier-only and forbidden-name checks remain the authority; this test
    pins the boundary so nobody mistakes one layer for the other.
    """
    source, task_dir = _convert(tmp_path)
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    leak = task_dir / "environment" / "materials" / "main.tex"
    leak.write_bytes((paper_dir / "original" / "main.tex").read_bytes())

    report = derive_origins(task_dir, paper_dir, generated=pwb_spec.SPEC.generated_public)
    assert "environment/materials/main.tex" in report.from_upstream
    assert report.unexplained == []


def test_an_empty_generated_file_is_not_attributed_to_upstream(tmp_path: Path) -> None:
    """Content addressing's one systematic false positive, and the fix.

    Every empty file matches every other empty file. `environment/texmf/.keep`
    is zero bytes and so is many an upstream `__init__.py`, so looking up its
    content produced a confident wrong origin on 29 of the 51 published
    PaperWrite-Bench tasks. Classification is settled first: where a file is
    known to be produced, its origin is not a question worth asking.
    """
    source, task_dir = _convert(tmp_path)
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    (paper_dir / "resources" / "code").mkdir(exist_ok=True)
    (paper_dir / "resources" / "code" / "__init__.py").write_text("", encoding="utf-8")
    keep = task_dir / "environment" / "texmf" / ".keep"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("", encoding="utf-8")

    report = derive_origins(task_dir, paper_dir, generated=pwb_spec.SPEC.generated_public)
    assert "environment/texmf/.keep" in report.generated_or_vendor
    assert "environment/texmf/.keep" not in report.from_upstream


def test_a_sanitized_template_is_not_a_missing_file(tmp_path: Path) -> None:
    """The graphics safeguard rewrites template.tex; that is it working.

    4 of the 51 published PaperWrite-Bench tasks ship a template whose
    `\\includegraphics` of an unshipped asset was stripped, rather than one
    that fails the oracle compile. Each also ships upstream_data_warnings.md.
    """
    source, task_dir = _convert(tmp_path)
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    staged = task_dir / "environment" / "materials" / "template.tex"
    staged.write_text(staged.read_text(encoding="utf-8") + "\n% sanitized\n", encoding="utf-8")

    report = derive_origins(task_dir, paper_dir, generated=pwb_spec.SPEC.generated_public)
    expected = predict_copies(pwb_spec.SPEC, paper_dir, "short")
    rewritable = rewritable_targets(pwb_spec.SPEC)
    assert "environment/materials/template.tex" in rewritable
    assert compare_to_expectation(report, expected, paper_dir, rewritable=rewritable) == []


def test_only_template_tex_may_be_rewritten(tmp_path: Path) -> None:
    """The exemption stays narrow. Everything else must match upstream bytes."""
    assert rewritable_targets(pwb_spec.SPEC) == {"environment/materials/template.tex"}


def test_tree_copies_exclude_build_environment_residue(tmp_path: Path) -> None:
    """A `.git` or `__pycache__` in an upstream checkout is not task material.

    The converters drop both; a spec that predicted them would report every
    task as missing files it was never supposed to have. Found against the
    published LifeSci corpus, two of whose papers carry one.
    """
    source = _make_pwb_source(tmp_path)
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    code = paper_dir / "resources" / "code"
    (code / ".git").mkdir(parents=True, exist_ok=True)
    (code / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (code / "__pycache__").mkdir(exist_ok=True)
    (code / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"\x00")

    predicted = predict_copies(pwb_spec.SPEC, paper_dir, "short")
    assert not [p for p in predicted if ".git" in p or "__pycache__" in p or p.endswith(".pyc")]


def test_pwbw_declares_its_normalized_log_rewritable() -> None:
    """`experimental_log.md` is rewritten on all 200 published tasks.

    Upstream logs carry short alignment rows, bare pipes inside math, and
    unlabeled columns; `normalize_markdown_tables` repairs the structure
    without touching a result value. A spec that called it a plain copy would
    report every PaperWritingBench task as defective -- which is exactly what
    the content-addressed check reported before this was declared.
    """
    assert rewritable_targets(pwbw_spec.SPEC) == {
        "environment/materials/experimental_log.md"
    }
