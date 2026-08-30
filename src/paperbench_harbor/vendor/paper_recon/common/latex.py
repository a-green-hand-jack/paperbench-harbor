"""Helpers for reading self-contained, multi-file LaTeX submissions."""

from __future__ import annotations

import re
from pathlib import Path

_SOURCE_COMMAND = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
FIGURE_REFERENCE_PATTERN = re.compile(r"\\(?:auto|[cC]|sub)?ref\{([^}]+)\}")


def extract_figure_reference_labels(text: str) -> list[str]:
    """Return figure labels from ref-like commands, including comma lists."""
    labels: list[str] = []
    for match in FIGURE_REFERENCE_PATTERN.finditer(text):
        labels.extend(
            label.strip()
            for label in match.group(1).split(",")
            if label.strip().startswith("fig:")
        )
    return labels


def expand_latex_source(latex_path: Path) -> str:
    """Expand local ``input``/``include`` files without leaving the source root."""

    root = latex_path.parent.resolve()

    def expand(path: Path, active: set[Path]) -> str:
        resolved = path.resolve()
        if resolved in active or not resolved.is_relative_to(root) or not resolved.is_file():
            return ""
        active = active | {resolved}
        text = resolved.read_text(encoding="utf-8", errors="replace")

        def replace(match: re.Match[str]) -> str:
            requested = Path(match.group(1).strip())
            candidates: list[Path] = []
            # The submission contract documents root-relative paths. Fall back
            # to the including file's directory for conventional LaTeX trees.
            for base in (root, resolved.parent):
                candidate = base / requested
                candidates.append(candidate)
                if requested.suffix == "":
                    candidates.append(base / f"{requested}.tex")
            for candidate in candidates:
                if candidate.is_file() and candidate.resolve().is_relative_to(root):
                    return expand(candidate, active)
            return match.group(0)

        return _SOURCE_COMMAND.sub(replace, text)

    return expand(latex_path, set())
