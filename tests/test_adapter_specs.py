"""Does the declarative layout actually describe what the converters do?

`adapters/spec.py` claims each benchmark's layout can be expressed as data.
This module is the evidence for that claim, and it is the only thing standing
behind it: nothing consumes a spec as the source of truth yet.

The check runs a real conversion over each benchmark's existing fixture and
compares the files that came out against what the spec predicts, both ways.
A spec that under-describes fails on an unpredicted file; a spec that
over-describes fails on a prediction with nothing behind it. Bytes are compared
too, so a rule pointing at the wrong upstream source is caught rather than
merely counted.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from paperbench_harbor.adapters.lifesci_paperrecon.harbor import SPEC as LSPR_SPEC
from paperbench_harbor.adapters.paperwrite_bench import spec as pwb_spec
from paperbench_harbor.adapters.paperwrite_bench.converter import (
    PaperWriteBenchConversionConfig,
    convert_paperwrite_bench,
)
from paperbench_harbor.adapters.paperwritingbench import spec as pwbw_spec
from paperbench_harbor.adapters.paperwritingbench.converter import (
    PaperWritingBenchConversionConfig,
    convert_paperwritingbench,
)
from paperbench_harbor.adapters.spec import find_paper_dirs, predict_copies
from paperbench_harbor.fidelity.transforms import classify_generated_vendor
from tests.test_paperwrite_bench_converter import _make_source as _make_pwb_source
from tests.test_paperwritingbench_converter import _make_source as _make_pwbw_source


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _actual_writer_copies(task_dir: Path, spec) -> set[str]:
    """Writer-visible files the conversion copied, as opposed to produced.

    Two subtractions, and they are different things.
    `classify_generated_vendor` is the audit's own answer to "is this generated
    or vendored for any benchmark", reused rather than restated so the two
    cannot disagree about, say, `environment/texmf/`. The spec's
    `generated_public` covers what only this benchmark produces -- AGENTS.md is
    assembled from a paper-type template, not copied from upstream.
    """
    root = task_dir / "environment"
    return {
        rel
        for path in root.rglob("*")
        if path.is_file()
        for rel in [f"environment/{path.relative_to(root).as_posix()}"]
        if not classify_generated_vendor(rel) and rel not in spec.generated_public
    }


def _actual_private_copies(task_dir: Path, spec) -> set[str]:
    found: set[str] = set()
    for area in ("solution/private", "tests/private"):
        root = task_dir / area
        if not root.is_dir():
            continue
        found |= {
            f"{area}/{path.relative_to(root).as_posix()}"
            for path in root.rglob("*")
            if path.is_file()
        }
    return found - set(spec.generated_private)


def test_pwb_spec_finds_the_same_papers_as_the_converter(tmp_path: Path) -> None:
    source = _make_pwb_source(tmp_path)
    convert_paperwrite_bench(
        PaperWriteBenchConversionConfig(
            source=source, output_dir=tmp_path / "out", upstream_revision="rev"
        )
    )
    found = find_paper_dirs(pwb_spec.SPEC, source)
    converted = sorted(p.name for p in (tmp_path / "out").iterdir() if p.is_dir())
    assert len(found) == len(converted)


def test_pwbw_spec_finds_the_same_papers_as_the_converter(tmp_path: Path) -> None:
    source = _make_pwbw_source(tmp_path)
    convert_paperwritingbench(
        PaperWritingBenchConversionConfig(
            source=source, output_dir=tmp_path / "out", upstream_revision="rev"
        )
    )
    found = find_paper_dirs(pwbw_spec.SPEC, source)
    converted = sorted(p.name for p in (tmp_path / "out").iterdir() if p.is_dir())
    assert len(found) == len(converted) == 3


@pytest.mark.parametrize("protocol", ["short", "long"])
def test_pwb_spec_predicts_the_writer_surface(tmp_path: Path, protocol: str) -> None:
    source = _make_pwb_source(tmp_path)
    out = tmp_path / "out"
    convert_paperwrite_bench(
        PaperWriteBenchConversionConfig(
            source=source, output_dir=out, overview=protocol, upstream_revision="rev"
        )
    )
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    task_dir = out / "pwb-0001"

    predicted = predict_copies(pwb_spec.SPEC, paper_dir, protocol)
    assert set(predicted) == _actual_writer_copies(task_dir, pwb_spec.SPEC)
    for target, upstream in predicted.items():
        assert _sha256(task_dir / target) == _sha256(upstream), target


def test_pwbw_spec_predicts_the_writer_surface(tmp_path: Path) -> None:
    source = _make_pwbw_source(tmp_path)
    out = tmp_path / "out"
    convert_paperwritingbench(
        PaperWritingBenchConversionConfig(
            source=source, output_dir=out, upstream_revision="rev"
        )
    )
    paper_dir = find_paper_dirs(pwbw_spec.SPEC, source)[0]
    task_dir = out / "pwbw-0001"

    predicted = predict_copies(pwbw_spec.SPEC, paper_dir)
    # The conference kit is Harbor-supplied rather than upstream, and
    # classify_generated_vendor already treats it as vendored.
    assert set(predicted) == _actual_writer_copies(task_dir, pwbw_spec.SPEC)
    for target, upstream in predicted.items():
        assert _sha256(task_dir / target) == _sha256(upstream), target


def test_pwb_spec_predicts_the_verifier_surface(tmp_path: Path) -> None:
    source = _make_pwb_source(tmp_path)
    out = tmp_path / "out"
    convert_paperwrite_bench(
        PaperWriteBenchConversionConfig(
            source=source, output_dir=out, upstream_revision="rev"
        )
    )
    paper_dir = find_paper_dirs(pwb_spec.SPEC, source)[0]
    task_dir = out / "pwb-0001"

    predicted = predict_copies(pwb_spec.SPEC, paper_dir, "short", private=True)
    actual = _actual_private_copies(task_dir, pwb_spec.SPEC)
    # The unselected overview is verifier-only and lands under tests/private.
    # It is a protocol-dependent path rather than a rule, so it is asserted
    # here instead of being predicted.
    assert "tests/private/research_overview_long.md" in actual
    assert set(predicted) <= actual
    unaccounted = actual - set(predicted) - {"tests/private/research_overview_long.md"}
    assert not unaccounted, unaccounted
    for target, upstream in predicted.items():
        assert _sha256(task_dir / target) == _sha256(upstream), target


def test_pwbw_spec_predicts_the_verifier_surface(tmp_path: Path) -> None:
    source = _make_pwbw_source(tmp_path)
    out = tmp_path / "out"
    convert_paperwritingbench(
        PaperWritingBenchConversionConfig(
            source=source, output_dir=out, upstream_revision="rev"
        )
    )
    paper_dir = find_paper_dirs(pwbw_spec.SPEC, source)[0]
    task_dir = out / "pwbw-0001"

    predicted = predict_copies(pwbw_spec.SPEC, paper_dir, private=True)
    assert set(predicted) == _actual_private_copies(task_dir, pwbw_spec.SPEC)
    for target, upstream in predicted.items():
        assert _sha256(task_dir / target) == _sha256(upstream), target


def test_specs_agree_with_their_converters_forbidden_names() -> None:
    """The leakage denylist is part of the layout, not a separate opinion."""
    from paperbench_harbor.adapters.paperwrite_bench.converter import FORBIDDEN_PUBLIC_NAMES as PWB
    from paperbench_harbor.adapters.paperwritingbench.converter import (
        FORBIDDEN_PUBLIC_NAMES as PWBW,
    )

    assert pwb_spec.SPEC.forbidden_public_names == PWB
    assert pwbw_spec.SPEC.forbidden_public_names == PWBW


def test_lifesci_spec_differs_from_paperwrite_bench_only_in_identity_and_provenance() -> None:
    assert LSPR_SPEC.public == pwb_spec.SPEC.public
    assert LSPR_SPEC.private == pwb_spec.SPEC.private
    assert LSPR_SPEC.benchmark == "LifeSci-PaperRecon"
    assert LSPR_SPEC.task_id_prefix == "lspr"
    assert (
        LSPR_SPEC.forbidden_public_names - pwb_spec.SPEC.forbidden_public_names
        == {"provenance.json"}
    )


def test_unknown_protocol_is_rejected() -> None:
    rule = pwb_spec.PUBLIC_RULES[0]
    with pytest.raises(ValueError, match="unknown protocol"):
        pwb_spec.SPEC.resolve(rule, "medium")


def test_unselected_variants_are_the_ones_the_writer_must_not_see() -> None:
    assert pwb_spec.SPEC.unselected_variants("short") == (
        "resources/research_overview_long.md",
    )
    assert pwb_spec.SPEC.unselected_variants("long") == (
        "resources/research_overview_short.md",
    )
