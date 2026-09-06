"""Synthetic reference manuscript, authored from public inputs and rendered safely."""

import re
import shutil
import subprocess

from pydantic import Field

from paperbench_harbor.construction.core.state import atomic_json

from .integrity import artifact_hash, contained
from .operations import OperationalError, run
from .schema import Record


class Paragraph(Record):
    text: str = Field(
        min_length=1, description="Scientific manuscript prose, plain text, no TeX or Markdown"
    )
    citations: list[str]


class Table(Record):
    source_table: str = Field(description="Exact ID of an audited public structured table; values must match")
    caption: str = Field(min_length=1)
    columns: list[str] = Field(min_length=1)
    rows: list[list[str]] = Field(min_length=1)


class Figure(Record):
    public_path: str
    caption: str = Field(min_length=1)


class Section(Record):
    heading: str
    paragraphs: list[Paragraph] = Field(min_length=1)
    tables: list[Table]
    figures: list[Figure]


class Citation(Record):
    key: str = Field(pattern=r"^[A-Za-z0-9:_-]+$")
    author: str = Field(min_length=1)
    title: str = Field(min_length=1)
    year: str = Field(pattern=r"^[0-9]{4}$")
    publication: str = Field(min_length=1)


class Oracle(Record):
    title: str = Field(min_length=1)
    abstract: str = Field(min_length=1)
    sections: list[Section] = Field(min_length=1)
    bibliography: list[Citation] = Field(min_length=1)
    requirement_coverage: list[str] = Field(
        min_length=1,
        description="One explanation per writing requirement, in its declared order, naming the manuscript section and substantive treatment. These audit notes are NOT manuscript prose.",
    )


def tex(text):
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def render(oracle, materials, task, destination):
    """Only controller-owned TeX commands execute; model text is always escaped."""
    headings = [s.heading for s in oracle.sections]
    if headings != materials.submission_sections:
        raise ValueError("oracle must use the exact required sections in order")
    if len(oracle.requirement_coverage) != len(materials.requirements):
        raise ValueError("oracle must account for every explicit writing requirement")
    keys = {c.key for c in oracle.bibliography}
    if len(keys) != len(oracle.bibliography):
        raise ValueError("oracle bibliography keys must be unique")
    cited = {key for section in oracle.sections for p in section.paragraphs for key in p.citations}
    if not cited or not cited <= keys:
        raise ValueError("oracle has missing or undefined source citations")
    references = "\n".join(f.content for f in materials.files if f.role == "references")
    neutral = set(re.findall(r"^\[([A-Za-z0-9:_-]+)\]\s*=", references, re.MULTILINE))
    supplied = set(re.findall(r"@\w+\s*\{\s*([^,\s]+)", references))
    if not cited <= supplied:
        raise ValueError("oracle citations must use the actual public BibTeX bibliography")
    if (neutral and not neutral <= cited) or (not neutral and not supplied.intersection(cited)):
        raise ValueError("oracle fails the public source citation contract")
    word_counts = [
        len(re.findall(r"[^\W\d_]{2,}", " ".join(p.text for p in s.paragraphs)))
        for s in oracle.sections
    ]
    if min(word_counts) < 20 or sum(word_counts) < 200:
        raise ValueError("oracle manuscript lacks substantive body/section prose")
    destination.mkdir(exist_ok=True)
    manuscript = destination / "manuscript"
    manuscript.mkdir()
    lines = [
        r"\documentclass{article}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage{graphicx,longtable,geometry}",
        r"\geometry{margin=1in}",
        r"\title{" + tex(oracle.title) + "}",
        r"\author{PaperSmith synthetic reference baseline}",
        r"\date{}",
        r"\begin{document}",
        r"\maketitle",
        r"\begin{abstract}",
        tex(oracle.abstract),
        r"\end{abstract}",
    ]
    public_files = {f.path: f for f in materials.files}
    source_tables = {t.id: t for t in materials.tables}
    used_tables = set()
    body_start = len(lines)
    for section in oracle.sections:
        lines.append(r"\section{" + tex(section.heading) + "}")
        for paragraph in section.paragraphs:
            lines.append(
                tex(paragraph.text)
                + (r" \cite{" + ",".join(paragraph.citations) + "}" if paragraph.citations else "")
                + "\n"
            )
        for table in section.tables:
            original = source_tables.get(table.source_table)
            if original is None or table.columns != original.columns or table.rows != [[c.value for c in row] for row in original.rows]:
                raise ValueError("oracle table must preserve exact public source-table columns/cells")
            used_tables.add(table.source_table)
            if any(len(row) != len(table.columns) for row in table.rows):
                raise ValueError("oracle table row width mismatch")
            column = r"p{\dimexpr\linewidth/" + str(len(table.columns)) + r"-2\tabcolsep\relax}"
            lines.extend(
                [
                    r"\begin{longtable}{" + (column * len(table.columns)) + "}",
                    r"\caption{" + tex(table.caption) + r"}\\",
                    " & ".join(map(tex, table.columns)) + r"\\\hline",
                ]
            )
            lines.extend(" & ".join(map(tex, row)) + r"\\" for row in table.rows)
            lines.append(r"\end{longtable}")
            lines.append(tex("Units: " + "; ".join(original.units) + ". " + original.notes
                             + " Missing values: " + original.missing_values + ". Precision: " + original.precision))
        for figure in section.figures:
            item = public_files.get(figure.public_path)
            if item is None or item.role != "figure":
                raise ValueError("oracle figure must be an audited public figure")
            source = contained(
                task / "environment/materials", task / "environment/materials" / figure.public_path
            )
            if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".pdf"}:
                raise ValueError("oracle requires a pdflatex-compatible public figure")
            assets = manuscript / "assets"
            assets.mkdir(exist_ok=True)
            name = artifact_hash(source) + source.suffix.lower()
            shutil.copyfile(source, assets / name)
            lines.extend(
                [
                    r"\begin{figure}[htbp]\centering",
                    r"\includegraphics[width=0.9\linewidth,height=0.7\textheight,keepaspectratio]{assets/"
                    + name
                    + "}",
                    r"\caption{" + tex(figure.caption) + "}",
                    r"\end{figure}",
                ]
            )
    if used_tables != set(source_tables):
        raise ValueError("oracle must include every required public structured table")
    template = task / "environment/materials/template/main.tex"
    starter = template.read_text()
    starter = starter.replace(r"\title{Manuscript title}", r"\title{" + tex(oracle.title) + "}")
    starter = starter.replace(r"\author{Author}", r"\author{PaperSmith synthetic reference baseline}")
    starter = starter.replace("% Replace with a scientific abstract supported by the supplied materials.", tex(oracle.abstract))
    starter = starter.replace("% PAPERSMITH_BODY", "\n".join(lines[body_start:]))
    starter = starter.replace(r"\nocite{*}", "")
    (manuscript / "main.tex").write_text(starter)
    shutil.copyfile(task / "environment/materials/template/references.bib", manuscript / "references.bib")
    (destination / "solve.sh").write_text(
        '#!/bin/sh\nset -eu\nbase=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)\n'
        'mkdir -p /workspace/submission\ncp -R "$base/manuscript/." /workspace/submission/\n'
        "cd /workspace/submission\n"
        "pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape main.tex\n"
        "bibtex main\n"
        "pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape main.tex\n"
        "pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape main.tex\n"
    )
    atomic_json(
        destination / "provenance.json",
        {
            "kind": "synthetic_oracle_not_original_ground_truth",
            "authorship": "execution model, separate offline oracle builder session",
            "instruction_sha256": artifact_hash(task / "instruction.md"),
            "public_materials_sha256": artifact_hash(task / "environment/materials"),
            "public_template_sha256": artifact_hash(template),
            "manuscript_sha256": artifact_hash(manuscript),
            "requirement_coverage": oracle.requirement_coverage,
            "scientific_approval": "requires independent gate3 comparison with original and requirements",
        },
    )


def compile_oracle(solution, build, *, template_only=False):
    shutil.copytree(solution / "manuscript", build)
    commands = [
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "main.tex"],
        ["bibtex", "main"],
    ]
    commands += [commands[0], commands[0]]
    for command in commands:
        result = run(command, cwd=build, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode:
            atomic_json(solution / "validation.json", {"compiled": False, "classification": "compile",
                        "command": command, "build": str(build), "returncode": result.returncode,
                        "scope": "template only" if template_only else "synthetic oracle"})
            raise OperationalError("compile", "TeX compilation failed; retained source, model response and build logs")
    log = (build / "main.log").read_text()
    if re.search(
        r"Citation[^\n]*undefined|There were undefined (?:references|citations)|No file .*\.bbl",
        log,
    ):
        raise OperationalError("compile", "TeX has unresolved citations/references; retained build logs")
    shutil.copyfile(build / "main.pdf", solution / "preview.pdf")
    result = run(
        ["pdftotext", "-layout", str(build / "main.pdf"), str(solution / "preview.txt")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode or (not template_only and len((solution / "preview.txt").read_text().split()) < 200):
        raise ValueError("synthetic oracle rendered PDF is unreadable")
    atomic_json(
        solution / "validation.json",
        {
            "compiled": True,
            "commands": commands,
            "source_sha256": artifact_hash(solution / "manuscript"),
            "pdf_sha256": artifact_hash(solution / "preview.pdf"),
            "scope": "controller compilation and structural checks; Harbor oracle/nop trials not run",
            "template_only": template_only,
            "completed_submission": False,
        },
    )
