from __future__ import annotations

from pathlib import Path

from scripts.check_documentation_references import validate_documentation


def test_cross_dataset_documentation_is_linked_and_inventoried() -> None:
    root = Path(__file__).resolve().parents[1]
    assert validate_documentation(root) == []
