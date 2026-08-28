from pathlib import Path

import pytest

from paperbench_harbor.common.audit import LeakageError, audit_forbidden_names


def test_audit_detects_private_file(tmp_path: Path) -> None:
    leaked = tmp_path / "eval_points.json"
    leaked.write_text("{}", encoding="utf-8")

    with pytest.raises(LeakageError):
        audit_forbidden_names(tmp_path, {"eval_points.json"})


def test_audit_accepts_public_tree(tmp_path: Path) -> None:
    (tmp_path / "research_overview.md").write_text("overview", encoding="utf-8")
    audit_forbidden_names(tmp_path, {"eval_points.json", "gt_main.tex"})
