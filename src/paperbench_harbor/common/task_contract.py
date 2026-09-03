"""Release-blocking validation for generated writer-facing task contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_MATERIAL_PATH_RE = re.compile(r"/workspace/materials/([^`\s)]+)")
_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}")
_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")


class TaskContractError(RuntimeError):
    """Raised when a generated task is not safe to release."""


@dataclass(frozen=True)
class ContractFinding:
    code: str
    detail: str


def _markdown_cells(line: str) -> list[str]:
    stripped = line.strip().removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator_row(line: str) -> bool:
    cells = _markdown_cells(line)
    return bool(cells) and all(_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells)


def normalize_markdown_tables(path: Path) -> list[str]:
    """Make structural Markdown repairs explicit without changing result values.

    Upstream logs occasionally have a short alignment row, bare pipes in math,
    or unlabeled data columns. The conversion records each correction as an
    upstream warning and uses neutral labels rather than guessing semantics.
    """

    lines = path.read_text(encoding="utf-8").splitlines()
    warnings: list[str] = []
    for index, line in enumerate(lines):
        if "$" in line and "|" in line:
            parts = line.split("$")
            for part_index in range(1, len(parts), 2):
                parts[part_index] = parts[part_index].replace("|", r"\|")
            normalized = "$".join(parts)
            if normalized != line:
                lines[index] = normalized
                warnings.append(f"Escaped a pipe in math notation at line {index + 1}.")

    index = 0
    while index + 1 < len(lines):
        header = lines[index]
        separator = lines[index + 1]
        if "|" not in header or not _is_separator_row(separator):
            index += 1
            continue
        header_cells = _markdown_cells(header)
        data_end = index + 2
        data_counts: list[int] = []
        while data_end < len(lines) and "|" in lines[data_end] and lines[data_end].strip():
            data_counts.append(len(_markdown_cells(lines[data_end])))
            data_end += 1
        target = max([len(header_cells), *data_counts], default=len(header_cells))
        if len(header_cells) < target:
            missing = target - len(header_cells)
            header_cells.extend(
                f"Unspecified upstream field {position}"
                for position in range(1, missing + 1)
            )
            lines[index] = "| " + " | ".join(header_cells) + " |"
            warnings.append(
                f"Added {missing} neutral header label(s) for extra upstream table values at line {index + 1}."
            )
        if len(_markdown_cells(lines[index + 1])) != target:
            lines[index + 1] = "| " + " | ".join("---" for _ in range(target)) + " |"
            warnings.append(f"Normalized the Markdown alignment row at line {index + 2}.")
        for row_index in range(index + 2, data_end):
            cells = _markdown_cells(lines[row_index])
            if len(cells) < target:
                cells.extend("NA (upstream omitted)" for _ in range(target - len(cells)))
                lines[row_index] = "| " + " | ".join(cells) + " |"
                warnings.append(f"Marked missing upstream table cells as NA at line {row_index + 1}.")
        index = data_end

    normalized = "\n".join(lines) + "\n"
    if normalized != path.read_text(encoding="utf-8"):
        path.write_text(normalized, encoding="utf-8")
    return warnings


def _active_graphics(tex_path: Path) -> list[str]:
    matches: list[str] = []
    for raw_line in tex_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split("%", 1)[0]
        matches.extend(_GRAPHICS_RE.findall(line))
    return matches


def _graphics_exists(materials: Path, graphic: str) -> bool:
    candidate = materials / graphic.lstrip("./")
    if candidate.is_file():
        return True
    if candidate.suffix:
        return False
    return any(candidate.with_suffix(extension).is_file() for extension in (".png", ".jpg", ".jpeg", ".pdf"))


def validate_task_contract(task_dir: Path) -> list[ContractFinding]:
    """Validate all public writer-facing release requirements for one task."""

    findings: list[ContractFinding] = []
    instruction_path = task_dir / "instruction.md"
    environment = task_dir / "environment"
    materials = environment / "materials"
    if not instruction_path.is_file():
        return [ContractFinding("missing_instruction", "instruction.md is absent")]
    instruction = instruction_path.read_text(encoding="utf-8")

    for reference in sorted(set(_MATERIAL_PATH_RE.findall(instruction))):
        if "..." in reference:
            continue
        if not (materials / reference.rstrip("/")).exists():
            findings.append(ContractFinding("missing_instruction_material", reference))

    conference = materials / "conference_template"
    if conference.is_dir():
        guidelines = (conference / "guidelines.md").read_text(encoding="utf-8", errors="replace")
        template = (conference / "template.tex").read_text(encoding="utf-8", errors="replace")
        if "double-blind" in guidelines.lower():
            if any(value in template for value in ("Ambitious AI Researcher", "AI Research Institute", "researcher@")):
                findings.append(ContractFinding("identifying_author_placeholder", "review template has a named affiliation"))
            if "cvpr" in template.lower() and not re.search(r"\\usepackage\[review\]\{cvpr\}", template):
                findings.append(ContractFinding("cvpr_review_mode_missing", "CVPR review template lacks [review]"))
            if "iclr" in template.lower() and "\\iclrfinalcopy" in template:
                findings.append(ContractFinding("iclr_review_mode_missing", "ICLR template enables final mode"))
        for tex_path in conference.rglob("*.tex"):
            for graphic in _active_graphics(tex_path):
                if not _graphics_exists(materials, graphic):
                    findings.append(ContractFinding("missing_graphic", f"{tex_path.name}: {graphic}"))

    template = materials / "template.tex"
    if template.is_file():
        expected = re.search(r"suitable for a [^\n]* (single|double)-column paper", instruction)
        if expected:
            source = "\n".join(
                line.split("%", 1)[0]
                for line in template.read_text(encoding="utf-8", errors="replace").splitlines()
            )
            has_two_columns = bool(
                re.search(r"\\documentclass\[[^]]*twocolumn", source)
                or re.search(r"\\twocolumn\b", source)
                or re.search(r"\\documentclass(?:\[[^]]*\])?\{acmart\}", source)
            )
            if has_two_columns and expected.group(1) != "double":
                findings.append(ContractFinding("format_template_mismatch", expected.group(0)))

    log_path = materials / "experimental_log.md"
    if log_path.is_file():
        lines = log_path.read_text(encoding="utf-8").splitlines()
        for index in range(len(lines) - 1):
            if "|" not in lines[index] or not _is_separator_row(lines[index + 1]):
                continue
            count = len(_markdown_cells(lines[index]))
            cursor = index + 2
            while cursor < len(lines) and "|" in lines[cursor] and lines[cursor].strip():
                if len(_markdown_cells(lines[cursor])) != count:
                    findings.append(ContractFinding("malformed_markdown_table", f"line {cursor + 1}"))
                cursor += 1

    sidecar = environment / "paper_orchestra_sidecar.py"
    if sidecar.is_file():
        if not re.search(r"(?:research|literature-review) cutoff.{0,120}2024-10-01", instruction, flags=re.IGNORECASE | re.DOTALL):
            findings.append(ContractFinding("missing_research_cutoff", "instruction lacks the fixed cutoff"))
        if "credential-free Semantic Scholar fallback" not in instruction:
            findings.append(ContractFinding("missing_credential_fallback", "instruction does not declare fallback"))
        if "_semantic_scholar_discover" not in sidecar.read_text(encoding="utf-8"):
            findings.append(ContractFinding("missing_sidecar_fallback", "sidecar lacks direct Semantic Scholar discovery"))

    return findings


def assert_valid_task_contract(task_dir: Path) -> None:
    findings = validate_task_contract(task_dir)
    if findings:
        rendered = "\n".join(f"- {item.code}: {item.detail}" for item in findings)
        raise TaskContractError(f"Task contract validation failed for {task_dir}:\n{rendered}")
