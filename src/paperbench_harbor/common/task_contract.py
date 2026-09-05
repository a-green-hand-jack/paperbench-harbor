"""Release-blocking validation for generated writer-facing task contracts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_MATERIAL_PATH_RE = re.compile(r"/workspace/materials/([^`\s)]+)")
_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}")


class TaskContractError(RuntimeError):
    """Raised when a generated task is not safe to release."""


@dataclass(frozen=True)
class ContractFinding:
    code: str
    detail: str


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

    requirements_path = materials / "writing_requirements.json"
    if requirements_path.is_file():
        from paperbench_harbor.construction.core.evidence import (
            file_hash,
            safe_file,
            validate_locator,
        )

        try:
            requirements = json.loads(requirements_path.read_text())
            if not isinstance(requirements, list) or not requirements:
                raise ValueError("writing requirements must be a nonempty array")
            for requirement in requirements:
                if not requirement.get("public_support"):
                    raise ValueError("writing requirement lacks public support")
                for location in requirement["public_support"]:
                    prefix = "/workspace/materials/"
                    if not location["path"].startswith(prefix):
                        raise ValueError("support must name its actual writer-visible path")
                    relative = location["path"][len(prefix):]
                    path = safe_file(materials, relative)
                    if file_hash(path) != location["sha256"]:
                        raise ValueError("writer support hash mismatch")
                    validate_locator(materials, relative, location["locator"])
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            findings.append(ContractFinding("invalid_writing_requirements", str(error)))

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
