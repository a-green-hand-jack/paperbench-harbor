"""The deterministic gate between an opencode construction run and the corpus.

Everything in this module is contract checking, not paper-specific judgment,
which is exactly why it is plain code rather than more agent turns: the agent
decides *how* to make a paper fit the layout, and this module decides whether it
actually did. The agent cannot negotiate with it.

Three properties matter, in increasing order of how expensive they are to
discover later:

1. **Layout** — the files the Harbor converter reads are present, and the ones
   that would leak the answer are not.
2. **Provenance** — what the agent recorded matches what a human approved in
   the domain's paper set. A silently substituted paper is worse than a failed
   build, so a mismatch is a hard failure and never a warning.
3. **Solvability** — the oracle scores `1.0`. This is checked by *reproducing
   the oracle*: the real `normalize.py` template is rendered and run against a
   real `materials/` tree built by the converter's own copy helper, and the
   result is recompiled with the verifier's restricted flags. Reimplementing
   any of that here would let the check and the thing it checks drift apart.

A failing report is written to be read by the construction agent
(:meth:`ValidationReport.agent_feedback`), because the designed response to a
failure is another opencode turn, not a hand-written patch.

Only four checks consult the domain at all — the paper-type taxonomy and its
writing instructions, the overview skeleton and its length bounds, and an
opt-in source-table inventory contract — and all four read them off the
:class:`~.plugin.DomainPlugin` they are handed. Nothing in this module knows
what discipline it is validating.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from paperbench_harbor.adapters.paperwrite_bench.converter import (
    FORBIDDEN_PUBLIC_NAMES,
    OVERVIEW_FILENAMES,
    _read_config,
)
from paperbench_harbor.adapters.paperwrite_bench.spec import SPEC as PWB_LAYOUT
from paperbench_harbor.adapters.spec import stage_declared_copies
from paperbench_harbor.common.audit import LeakageError, audit_forbidden_names
from paperbench_harbor.construction.core.latex import (
    CompileResult,
    compile_restricted,
)
from paperbench_harbor.construction.core.plugin import DomainPlugin
from paperbench_harbor.construction.core.spec import ACCEPTED_LICENSES, PaperSpec

_TEMPLATES_DIR = (
    Path(__file__).resolve().parents[2] / "common" / "templates"
)

#: Ground truth, verifier-only. `provenance.json` is this benchmark's addition
#: to the upstream layout (approved plan, Phase 1 step 9).
REQUIRED_ORIGINAL_FILES = ("config.yaml", "main.tex", "main.pdf", "provenance.json")

#: Writer-visible. `research_overview_long.md` is required even though the
#: pilot converts with `--overview short`: the converter files the unselected
#: variant under `tests/private/`, and building only one closes off the long
#: protocol for good.
REQUIRED_RESOURCE_FILES = (
    "template.tex",
    OVERVIEW_FILENAMES["short"],
    OVERVIEW_FILENAMES["long"],
    "references.bib",
    "figure_summary.txt",
    "table_summary.txt",
)

#: Figures are universal public reconstruction material.  Code is conditional
#: on the human-approved code-evidence branch in :class:`PaperSpec`.
REQUIRED_RESOURCE_DIRS = ("figures",)

#: Names that must never appear under `resources/`, which the converter copies
#: wholesale into the writer-visible environment. `resources/code/` is exempt
#: because it is a verbatim third-party source tree and the converter exempts
#: it too.
FORBIDDEN_RESOURCE_NAMES = FORBIDDEN_PUBLIC_NAMES | {"provenance.json"}

REQUIRED_PROVENANCE_FIELDS = (
    "title",
    "arxiv_id",
    "arxiv_version",
    "arxiv_category",
    "license_label",
    "license_url",
    "source_url",
    "fetch_date",
    "code_status",
)

_SOURCE_COMMAND_RE = re.compile(
    r"\\(?:input|include)\s*(?:\{(?P<braced>[^}]+)\}|(?P<bare>[^\s%]+))"
)
_TABLE_BEGIN_RE = re.compile(
    r"\\begin\s*\{(?P<environment>table\*?|longtable\*?|sidewaystable\*?)\}"
)
TABLE_INVENTORY_FILENAME = "table_inventory.json"
_CITE_RE = re.compile(
    r"\\(?P<command>[A-Za-z]*cite[A-Za-z]*\*?)"
    r"(?:\s*\[[^\]]*\]){0,2}\s*\{(?P<keys>[^}]*)\}",
    flags=re.DOTALL,
)
_BIB_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)")
_SECTION_RE = re.compile(r"\\(?:sub)*section\*?\s*\{")
_COLUMN_RE = re.compile(r"^\d+column$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class ValidationIssue:
    """One contract violation, phrased so the construction agent can act on it.

    `remedy` is not decoration: the retry turn is driven by this text, and an
    issue that only says what is wrong tends to produce a fix to the symptom.
    """

    code: str
    message: str
    remedy: str = ""

    def render(self) -> str:
        line = f"[{self.code}] {self.message}"
        return f"{line}\n    -> {self.remedy}" if self.remedy else line


@dataclass
class ValidationReport:
    paper_id: str
    paper_dir: Path
    issues: list[ValidationIssue] = field(default_factory=list)
    compiles: list[CompileResult] = field(default_factory=list)
    #: Set when compilation was deliberately not attempted, so a caller never
    #: mistakes "not checked" for "passed".
    compile_skipped_reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.issues and all(result.ok for result in self.compiles)

    def fail(self, code: str, message: str, remedy: str = "") -> None:
        self.issues.append(ValidationIssue(code=code, message=message, remedy=remedy))

    def summary(self) -> str:
        lines = [f"{self.paper_id}: {'PASS' if self.ok else 'FAIL'}"]
        if self.compile_skipped_reason:
            lines.append(f"  compile: SKIPPED ({self.compile_skipped_reason})")
        for result in self.compiles:
            lines.append(f"  compile {result.summary()}")
        for issue in self.issues:
            lines.append(f"  {issue.render()}")
        return "\n".join(lines)

    def agent_feedback(self) -> str:
        """The failure, formatted as the body of a follow-up opencode turn."""

        blocks: list[str] = []
        if self.issues:
            blocks.append(
                "Contract violations:\n"
                + "\n".join(f"- {issue.render()}" for issue in self.issues)
            )
        broken = [result for result in self.compiles if not result.ok]
        if broken:
            blocks.append(
                "Compilation failures (same flags the Harbor verifier uses, "
                "`pdflatex -interaction=nonstopmode -halt-on-error "
                "-no-shell-escape`, no network):\n\n"
                + "\n\n".join(result.summary() for result in broken)
            )
        return "\n\n".join(blocks)


@dataclass(frozen=True)
class SourceTable:
    """One table environment recovered from the ground-truth TeX tree."""

    id: str
    source_path: str
    line_start: int
    environment: str
    caption: str
    label: str
    content: str
    content_sha256: str


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _source_command_target(match: re.Match[str]) -> str:
    """Return the braced or bare filename from an input/include command."""

    return (match.group("braced") or match.group("bare")).strip()


def _mask_latex_comments(text: str) -> str:
    """Replace real TeX comments with spaces while preserving source offsets."""

    masked = list(text)
    index = 0
    while index < len(text):
        if text[index] != "%":
            index += 1
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and text[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            index += 1
            continue
        end = text.find("\n", index)
        if end < 0:
            end = len(text)
        for position in range(index, end):
            masked[position] = " "
        index = end + 1
    return "".join(masked)


def _expand_tex(path: Path, root: Path | None = None, active: set[Path] | None = None) -> str:
    """Inline `\\input`/`\\include` exactly as the shipped verifier does.

    Copied deliberately from `common/templates/test_state.py.j2` rather than
    approximated: a paper that splits its body across `\\input` files would
    otherwise pass a citation check here that the verifier fails.
    """

    root = (root or path.parent).resolve()
    active = active or set()
    resolved = path.resolve()
    if resolved in active or not resolved.is_relative_to(root) or not resolved.is_file():
        return ""
    active = active | {resolved}
    text = resolved.read_text(encoding="utf-8", errors="replace")

    def replace(match: re.Match[str]) -> str:
        requested = Path(_source_command_target(match))
        candidates = []
        for base in (root, resolved.parent):
            candidates.append(base / requested)
            if requested.suffix == "":
                candidates.append(base / f"{requested}.tex")
        for candidate in candidates:
            if candidate.is_file() and candidate.resolve().is_relative_to(root):
                return _expand_tex(candidate, root, active)
        return match.group(0)

    return _SOURCE_COMMAND_RE.sub(replace, text)


def _included_tex_files(
    path: Path, root: Path | None = None, active: set[Path] | None = None
) -> list[tuple[Path, str]]:
    """Return reachable TeX files in a deterministic source traversal."""

    root = (root or path.parent).resolve()
    active = active if active is not None else set()
    resolved = path.resolve()
    if resolved in active or not resolved.is_relative_to(root) or not resolved.is_file():
        return []
    active.add(resolved)
    text = resolved.read_text(encoding="utf-8", errors="replace")
    files = [(resolved, text)]
    for match in _SOURCE_COMMAND_RE.finditer(text):
        requested = Path(_source_command_target(match))
        candidates: list[Path] = []
        for base in (root, resolved.parent):
            candidates.append(base / requested)
            if requested.suffix == "":
                candidates.append(base / f"{requested}.tex")
        for candidate in candidates:
            if candidate.is_file() and candidate.resolve().is_relative_to(root):
                files.extend(_included_tex_files(candidate, root, active))
                break
    return files


def _latex_command_argument(text: str, command: str) -> str:
    """Read one braced LaTeX command argument without flattening nested braces."""

    match = re.search(rf"\\{command}(?:\s*\[[^]]*\])?\s*\{{", text)
    if match is None:
        return ""
    start = match.end() - 1
    depth = 0
    for index in range(start, len(text)):
        token = text[index]
        if token == "{":
            depth += 1
        elif token == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index].strip()
    return ""


def collect_source_tables(original: Path) -> list[SourceTable]:
    """Inventory source table environments from main.tex and included TeX."""

    main = original / "main.tex"
    if not main.is_file():
        return []
    discovered: list[tuple[str, int, str, str, str, str]] = []
    for source, text in _included_tex_files(main):
        scanned = _mask_latex_comments(text)
        source_path = source.relative_to(original.resolve()).as_posix()
        for begin in _TABLE_BEGIN_RE.finditer(scanned):
            environment = begin.group("environment")
            end = re.search(
                rf"\\end\s*\{{{re.escape(environment)}\}}", scanned[begin.end():]
            )
            if end is None:
                continue
            finish = begin.end() + end.end()
            content = text[begin.start():finish]
            discovered.append(
                (
                    source_path,
                    text.count("\n", 0, begin.start()) + 1,
                    environment,
                    _latex_command_argument(content, "caption"),
                    _latex_command_argument(content, "label"),
                    content,
                )
            )
    return [
        SourceTable(
            id=f"table-{index:03d}",
            source_path=source_path,
            line_start=line_start,
            environment=environment,
            caption=caption,
            label=label,
            content=content,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        for index, (source_path, line_start, environment, caption, label, content) in
        enumerate(discovered, start=1)
    ]


def synchronize_source_table_materials(paper_dir: Path) -> list[SourceTable]:
    """Regenerate public table evidence from the verifier-only TeX source.

    Table fragments and their inventory are mechanical projections of the
    source tree, not a reconstruction task for the construction agent.  Keeping
    this projection here means the exact source traversal, escaping and byte
    hashing are shared by the writer pipeline and the validation gate.
    """

    resources = paper_dir / "resources"
    tables = collect_source_tables(paper_dir / "original")
    table_dir = resources / "tables"
    if table_dir.exists():
        shutil.rmtree(table_dir)
    table_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    ledger: list[str] = []
    for table in tables:
        public_path = f"tables/{table.id}.tex"
        (resources / public_path).write_text(table.content, encoding="utf-8")
        records.append(
            {
                "id": table.id,
                "source_path": table.source_path,
                "line_start": table.line_start,
                "environment": table.environment,
                "caption": table.caption,
                "label": table.label,
                "content_sha256": table.content_sha256,
                "public_path": public_path,
            }
        )
        ledger.append(f"{public_path}: {table.caption}")

    resources.mkdir(parents=True, exist_ok=True)
    (resources / TABLE_INVENTORY_FILENAME).write_text(
        json.dumps({"schema_version": 1, "tables": records}, indent=2) + "\n",
        encoding="utf-8",
    )

    summary_path = resources / "table_summary.txt"
    existing_lines = (
        summary_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if summary_path.is_file()
        else []
    )
    if tables:
        # Keep qualitative descriptions from the agent, but remove the stale
        # no-tables claim that would contradict the regenerated source ledger.
        preserved = [
            line
            for line in existing_lines
            if line.strip() and "no table" not in line.lower() and line not in ledger
        ]
        summary_lines = ledger + preserved
    else:
        preserved = [line for line in existing_lines if line.strip()]
        summary_lines = ["The source has no tables."] + [
            line for line in preserved if "no table" not in line.lower()
        ]
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return tables


def _citation_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for match in _CITE_RE.finditer(text):
        if match.group("command").lower().startswith("nocite"):
            continue
        for key in match.group("keys").split(","):
            key = key.strip()
            if key:
                keys.add(key)
    return keys


def _bib_keys(bibliography: Path) -> set[str]:
    text = bibliography.read_text(encoding="utf-8", errors="replace")
    return set(_BIB_KEY_RE.findall(text))


def _is_complete_document(text: str) -> bool:
    return bool(re.search(r"\\documentclass\s*(\[[^]]*\])?\s*\{", text)) and (
        "\\begin{document}" in text and "\\end{document}" in text
    )


def _render_normalize_script(destination: Path) -> Path:
    """Write out the *shipped* oracle normalizer, not a copy of its behaviour."""

    environment = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    destination.write_text(
        environment.get_template("normalize.py.j2").render(), encoding="utf-8"
    )
    return destination


# --------------------------------------------------------------------------- #
# individual checks
# --------------------------------------------------------------------------- #


def _check_layout(report: ValidationReport, spec: PaperSpec) -> None:
    original = report.paper_dir / "original"
    resources = report.paper_dir / "resources"

    for filename in REQUIRED_ORIGINAL_FILES:
        if not (original / filename).is_file():
            report.fail(
                "missing-original",
                f"original/{filename} is missing",
                "Produce every file in the contract; the Harbor converter reads "
                "them by exact name.",
            )
    for filename in REQUIRED_RESOURCE_FILES:
        if not (resources / filename).is_file():
            report.fail(
                "missing-resource",
                f"resources/{filename} is missing",
                "Produce every file in the contract; the Harbor converter reads "
                "them by exact name.",
            )
    for dirname in REQUIRED_RESOURCE_DIRS:
        # Proof-only PaperRecon samples may have structured results without
        # extractable image assets; the overview and source remain the inputs.
        if dirname == "figures" and spec.code_status == "not_applicable":
            continue
        directory = resources / dirname
        if not directory.is_dir() or not any(directory.rglob("*")):
            report.fail(
                "missing-resource-dir",
                f"resources/{dirname}/ is missing or empty",
                "figures/ must hold the paper's extracted figure assets.",
            )

    code_dir = resources / "code"
    if spec.requires_code:
        if not code_dir.is_dir() or not any(code_dir.rglob("*")):
            report.fail(
                "missing-resource-dir",
                "resources/code/ is missing or empty",
                "code_status='available' requires a non-empty checkout of the "
                "approved public repository.",
            )
    elif code_dir.exists():
        report.fail(
            "unexpected-code-resource",
            "resources/code/ exists for an approved no-code paper",
            "Do not add code to a code_status='not_applicable' sample. Keep the "
            "reviewed reason only in provenance.json.",
        )

    if resources.is_dir():
        try:
            audit_forbidden_names(
                resources, FORBIDDEN_RESOURCE_NAMES, ignore_globs=("code/**",)
            )
        except LeakageError as error:
            report.fail(
                "leakage",
                str(error),
                "resources/ is copied verbatim into the writer's environment. "
                "Ground truth (main.tex, main.pdf, config.yaml, provenance.json) "
                "belongs under original/ only.",
            )


def _check_config(report: ValidationReport, spec: PaperSpec, plugin: DomainPlugin) -> None:
    config_path = report.paper_dir / "original" / "config.yaml"
    if not config_path.is_file():
        return
    metadata = _read_config(config_path)

    if metadata.paper_type not in plugin.paper_types:
        report.fail(
            "config-type",
            f"config.yaml type={metadata.paper_type!r} is not one of {plugin.paper_types}",
            f"Write `type: {spec.paper_type}`.",
        )
    elif metadata.paper_type != spec.paper_type:
        report.fail(
            "config-type",
            f"config.yaml type={metadata.paper_type!r} but this paper was "
            f"approved as {spec.paper_type!r}",
            f"Write `type: {spec.paper_type}`. The paper type is a human "
            "selection decision and is not the agent's to change.",
        )
    else:
        # The converter silently falls back to a default AGENTS_*.md for an
        # unknown type, which would hand a paper the wrong writing instructions
        # without any error.
        agents_md = plugin.agents_md_dir / f"AGENTS_{metadata.paper_type}.md"
        if not agents_md.is_file():
            report.fail(
                "config-type",
                f"no writing instructions exist for type={metadata.paper_type!r} "
                f"({agents_md} not found)",
            )

    if not metadata.num_page.isdigit() or int(metadata.num_page) <= 0:
        report.fail(
            "config-num-page",
            f"config.yaml num_page={metadata.num_page!r} is not a positive integer",
            "Write the ground-truth paper's page count, e.g. `num_page: 16`.",
        )
    if not _COLUMN_RE.match(metadata.column):
        report.fail(
            "config-column",
            f"config.yaml column={metadata.column!r} does not match `<n>column`",
            "Write `column: 1column` or `column: 2column`, matching the paper's "
            "actual layout.",
        )
    if not metadata.conference.strip():
        report.fail(
            "config-conference",
            "config.yaml conference is empty",
            f"Write the arXiv venue, e.g. `conference: arXiv {spec.expected_category}`.",
        )


def _check_provenance(report: ValidationReport, spec: PaperSpec) -> None:
    path = report.paper_dir / "original" / "provenance.json"
    if not path.is_file():
        return
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        report.fail(
            "provenance-parse",
            f"provenance.json is not valid JSON: {error}",
            "Write a single JSON object with the required fields.",
        )
        return
    if not isinstance(record, dict):
        report.fail("provenance-parse", "provenance.json is not a JSON object")
        return

    for field_name in REQUIRED_PROVENANCE_FIELDS:
        if not str(record.get(field_name, "")).strip():
            report.fail(
                "provenance-field",
                f"provenance.json is missing a non-empty {field_name!r}",
                "Record what you actually observed on the live arXiv page and "
                "repository; do not copy it from the task prompt.",
            )

    code_status = str(record.get("code_status", "")).strip()
    if code_status != spec.code_status:
        report.fail(
            "provenance-mismatch",
            f"provenance.json code_status={code_status!r} but the approved selection "
            f"says {spec.code_status!r}",
            "Keep the approved code-evidence branch. If the live source contradicts "
            "it, stop and record a top-level blocked reason instead of changing it.",
        )

    # Substitution guard. These are the facts a human approved, so a mismatch
    # stops the build rather than adjusting the expectation.
    checks = (
        ("arxiv_id", spec.arxiv_id),
        ("arxiv_version", spec.expected_version),
        ("arxiv_category", spec.expected_category),
        ("license_label", spec.expected_license),
    )
    for field_name, expected in checks:
        if not expected:
            continue
        actual = str(record.get(field_name, "")).strip()
        if actual and actual != expected:
            report.fail(
                "provenance-mismatch",
                f"provenance.json {field_name}={actual!r} but the approved "
                f"selection says {expected!r}",
                "Do not substitute a different paper or version. If the live "
                "arXiv page really disagrees with the approved selection, stop "
                "and say so in provenance.json's `blocked` field instead of "
                "building the paper.",
            )

    license_label = str(record.get("license_label", "")).strip()
    if license_label and license_label not in ACCEPTED_LICENSES:
        report.fail(
            "provenance-license",
            f"license {license_label!r} is not redistribution-permissive "
            f"(accepted: {', '.join(ACCEPTED_LICENSES)})",
            "This benchmark redistributes material derived from the paper, so a "
            "non-permissive license disqualifies it. Stop rather than proceed.",
        )

    code_fields = ("code_repo", "code_commit", "code_license")
    if spec.requires_code:
        for field_name in code_fields:
            if not str(record.get(field_name, "")).strip():
                report.fail(
                    "provenance-field",
                    f"provenance.json is missing a non-empty {field_name!r}",
                    "Record the checked-out repository, immutable commit and observed "
                    "license for a code_status='available' paper.",
                )
        if str(record.get("code_not_applicable_reason", "")).strip():
            report.fail(
                "provenance-code-status",
                "code_not_applicable_reason must be empty when code_status='available'",
            )
        repo = str(record.get("code_repo", "")).strip().rstrip("/").removesuffix(".git")
        expected_repo = spec.code_repo.rstrip("/").removesuffix(".git")
        if repo and repo.lower() != expected_repo.lower():
            report.fail(
                "provenance-mismatch",
                f"provenance.json code_repo={repo!r} but the approved selection "
                f"says {expected_repo!r}",
            )
    else:
        for field_name in code_fields:
            if str(record.get(field_name, "")).strip():
                report.fail(
                    "provenance-code-status",
                    f"{field_name} must be empty when code_status='not_applicable'",
                )
        reason = str(record.get("code_not_applicable_reason", "")).strip()
        if not reason:
            report.fail(
                "provenance-field",
                "provenance.json is missing non-empty 'code_not_applicable_reason'",
                "Record the approved evidence that code is not a reconstruction input.",
            )
        elif reason != spec.code_not_applicable_reason:
            report.fail(
                "provenance-mismatch",
                "provenance.json code_not_applicable_reason does not match the approved "
                "selection",
            )

    fetch_date = str(record.get("fetch_date", "")).strip()
    if fetch_date:
        if not _ISO_DATE_RE.match(fetch_date):
            report.fail(
                "provenance-date",
                f"fetch_date={fetch_date!r} is not an ISO `YYYY-MM-DD` date",
            )
        else:
            try:
                date.fromisoformat(fetch_date)
            except ValueError:
                report.fail("provenance-date", f"fetch_date={fetch_date!r} is not a real date")


def _check_template(report: ValidationReport) -> None:
    """The template is a skeleton the writer fills in, not a draft of the paper."""

    template = report.paper_dir / "resources" / "template.tex"
    main = report.paper_dir / "original" / "main.tex"
    if not template.is_file():
        return
    text = template.read_text(encoding="utf-8", errors="replace")

    if not _is_complete_document(text):
        report.fail(
            "template-not-a-document",
            "resources/template.tex is not a complete LaTeX document",
            "It must carry the paper's own preamble and a "
            "\\begin{document}...\\end{document} body, and compile on its own.",
        )
    sections = len(_SECTION_RE.findall(text))
    main_sections = 0
    if main.is_file():
        main_sections = len(_SECTION_RE.findall(main.read_text(encoding="utf-8", errors="replace")))
    # Short papers can legitimately have fewer than three headings.  The
    # contract is that the template preserves the paper's full skeleton.
    if sections < main_sections:
        report.fail(
            "template-no-skeleton",
            f"resources/template.tex declares {sections} sectioning commands but the ground-truth paper has {main_sections}",
            "The template is the paper's section skeleton: keep every "
            "\\section/\\subsection heading from the ground truth, with the "
            "prose removed.",
        )
    if _citation_keys(text):
        report.fail(
            "template-leaks-citations",
            "resources/template.tex contains \\cite commands",
            "Citations are part of the answer. Strip the body text, including "
            "its citations, and keep only headings and the "
            "\\bibliography/\\bibliographystyle lines.",
        )

    if main.is_file():
        body_ratio = _body_size(text) / max(_body_size(_expand_tex(main)), 1)
        if body_ratio > 0.25:
            report.fail(
                "template-leaks-prose",
                f"resources/template.tex retains {body_ratio:.0%} of the ground "
                "truth's body text",
                "Remove the paper's prose from the template; a writing agent "
                "that is handed the text has nothing left to reconstruct.",
            )


def _body_size(text: str) -> int:
    """Characters of prose between `\\begin{document}` and `\\end{document}`."""

    start = text.find("\\begin{document}")
    end = text.rfind("\\end{document}")
    if start < 0 or end < 0:
        return len(text)
    body = text[start + len("\\begin{document}") : end]
    body = re.sub(r"%.*", "", body)
    body = re.sub(r"\\[A-Za-z@]+\*?(\[[^\]]*\])?(\{[^{}]*\})?", " ", body)
    return len(re.sub(r"\s+", " ", body).strip())


def _check_overviews(report: ValidationReport, plugin: DomainPlugin) -> None:
    resources = report.paper_dir / "resources"
    lengths: dict[str, int] = {}
    for filename, (floor, ceiling) in plugin.overview_bounds.items():
        path = resources / filename
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lengths[filename] = len(text)

        if not floor <= len(text) <= ceiling:
            report.fail(
                "overview-length",
                f"resources/{filename} is {len(text)} characters, outside the "
                f"{floor}-{ceiling} range",
                "The short overview is a compact brief; the long one adds "
                "detail. Neither is the paper itself.",
            )
        lowered = text.lower()
        missing = [
            " / ".join(variants)
            for variants in plugin.overview_headings
            if not any(variant in lowered for variant in variants)
        ]
        if missing:
            report.fail(
                "overview-skeleton",
                f"resources/{filename} is missing required sections: "
                + "; ".join(missing),
                plugin.overview_skeleton_remedy(),
            )
        if "\\begin{document}" in text or _SECTION_RE.search(text):
            report.fail(
                "overview-is-latex",
                f"resources/{filename} contains LaTeX document structure",
                "The overview is Markdown prose describing the study, not a "
                "copy of the paper source.",
            )

    short_name = OVERVIEW_FILENAMES["short"]
    long_name = OVERVIEW_FILENAMES["long"]
    if (
        short_name in lengths
        and long_name in lengths
        and lengths[long_name] <= lengths[short_name]
    ):
        report.fail(
            "overview-ordering",
            f"{long_name} ({lengths[long_name]}) is not longer than "
            f"{short_name} ({lengths[short_name]})",
            "The two variants are different protocols: the long overview "
            "must carry strictly more detail.",
        )


def _check_table_inventory(report: ValidationReport) -> None:
    """Prove every table in the source TeX tree reaches public materials."""

    original = report.paper_dir / "original"
    resources = report.paper_dir / "resources"
    source_tables = collect_source_tables(original)
    inventory_path = resources / TABLE_INVENTORY_FILENAME
    if not inventory_path.is_file():
        report.fail(
            "table-inventory-missing",
            f"resources/{TABLE_INVENTORY_FILENAME} is missing",
            "Generate the source-table inventory and public table fragments before retrying.",
        )
        return
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        report.fail(
            "table-inventory-invalid",
            f"resources/{TABLE_INVENTORY_FILENAME} is not valid JSON: {error}",
            "Write the required schema_version=1 inventory object.",
        )
        return
    if (
        not isinstance(inventory, dict)
        or inventory.get("schema_version") != 1
        or not isinstance(inventory.get("tables"), list)
    ):
        report.fail(
            "table-inventory-invalid",
            f"resources/{TABLE_INVENTORY_FILENAME} must contain schema_version=1 and a tables list",
            "Write the required source-table inventory schema exactly.",
        )
        return
    records = inventory["tables"]
    if any(not isinstance(record, dict) for record in records):
        report.fail(
            "table-inventory-invalid",
            f"resources/{TABLE_INVENTORY_FILENAME} contains a non-object table record",
            "Every table inventory entry must be a JSON object.",
        )
        return
    records_by_id: dict[str, dict[object, object]] = {}
    for record in records:
        table_id = record.get("id")
        if not isinstance(table_id, str) or table_id in records_by_id:
            report.fail(
                "table-inventory-invalid",
                f"resources/{TABLE_INVENTORY_FILENAME} has a missing or duplicate id",
                "Use the unique table-001, table-002, ... ids from the source traversal.",
            )
            return
        records_by_id[table_id] = record

    table_dir = resources / "tables"
    actual_paths = (
        {
            f"tables/{path.relative_to(table_dir).as_posix()}"
            for path in table_dir.rglob("*")
            if path.is_file()
        }
        if table_dir.is_dir()
        else set()
    )
    summary = resources / "table_summary.txt"
    summary_text = summary.read_text(encoding="utf-8", errors="replace") if summary.is_file() else ""

    if not source_tables:
        if records_by_id:
            report.fail(
                "table-inventory-mismatch",
                "the source-table inventory is empty but the published inventory is not",
                "Remove table materials only when the complete source TeX tree has no tables.",
            )
        if actual_paths:
            report.fail(
                "table-material-untracked",
                "the source-table inventory is empty but tables/ contains public files",
                "Keep tables/ empty when the source inventory is empty.",
            )
        if "no table" not in summary_text.lower():
            report.fail(
                "table-summary-absence",
                "table_summary.txt does not explicitly state that the source has no tables",
                "Only an empty source inventory may use a no-tables summary.",
            )
        return

    expected_ids = {table.id for table in source_tables}
    extras = sorted(set(records_by_id) - expected_ids)
    if extras:
        report.fail(
            "table-inventory-mismatch",
            "inventory has table id(s) absent from the source: " + ", ".join(extras[:10]),
            "Regenerate the inventory from original/main.tex and its included TeX files.",
        )
    referenced_paths: set[str] = set()
    missing_summary_details: list[str] = []
    for table in source_tables:
        record = records_by_id.get(table.id)
        if record is None:
            report.fail(
                "table-inventory-mismatch",
                f"source table {table.id} from {table.source_path}:{table.line_start} is absent",
                "Extract every source table into a public table fragment.",
            )
            continue
        expected = {
            "source_path": table.source_path,
            "line_start": table.line_start,
            "environment": table.environment,
            "caption": table.caption,
            "label": table.label,
            "content_sha256": table.content_sha256,
        }
        mismatched = [key for key, value in expected.items() if record.get(key) != value]
        if mismatched:
            report.fail(
                "table-inventory-mismatch",
                f"{table.id} disagrees with source metadata: {', '.join(mismatched)}",
                "Regenerate the inventory directly from the source TeX table environment.",
            )
        public_path = record.get("public_path")
        if not isinstance(public_path, str):
            report.fail(
                "table-material-missing",
                f"{table.id} has no public_path",
                "Point every source table at a file below resources/tables/.",
            )
            continue
        relative = Path(public_path)
        if (
            relative.is_absolute()
            or len(relative.parts) < 2
            or relative.parts[0] != "tables"
            or ".." in relative.parts
        ):
            report.fail(
                "table-material-missing",
                f"{table.id} has unsafe public_path={public_path!r}",
                "Use a relative path below resources/tables/.",
            )
            continue
        if public_path in referenced_paths:
            report.fail(
                "table-material-duplicate",
                f"{table.id} reuses {public_path} from another source table",
                "Publish one distinct immutable table fragment for every source table.",
            )
            continue
        referenced_paths.add(public_path)
        material = resources / relative
        if not material.is_file():
            report.fail(
                "table-material-missing",
                f"{table.id} points to missing {public_path}",
                "Write the exact source table environment to the declared public file.",
            )
            continue
        if hashlib.sha256(material.read_bytes()).hexdigest() != table.content_sha256:
            report.fail(
                "table-material-content",
                f"{public_path} is not the exact source content for {table.id}",
                "Preserve the full source table environment, including captions and values.",
            )
        if public_path not in summary_text:
            missing_summary_details.append(f"{public_path} (path)")
        if table.caption and table.caption not in summary_text:
            missing_summary_details.append(f"{public_path} (caption)")
    untracked = sorted(actual_paths - referenced_paths)
    if untracked:
        report.fail(
            "table-material-untracked",
            "tables/ has file(s) absent from the source inventory: " + ", ".join(untracked[:10]),
            "Derive every public table fragment from the source-table inventory.",
        )
    if "no table" in summary_text.lower():
        missing_summary_details.append("summary falsely says no tables")
    if missing_summary_details:
        report.fail(
            "table-summary-incomplete",
            "table_summary.txt is inconsistent with the source-table inventory: "
            + ", ".join(missing_summary_details[:10]),
            "Enumerate every public table fragment with its source caption in table_summary.txt.",
        )


def _check_summaries(report: ValidationReport) -> None:
    """Every extracted asset must be described, or the writer cannot place it."""

    resources = report.paper_dir / "resources"
    pairs = (("figures", "figure_summary.txt"), ("tables", "table_summary.txt"))
    for dirname, summary_name in pairs:
        summary = resources / summary_name
        directory = resources / dirname
        if not summary.is_file():
            continue
        text = summary.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            report.fail(
                "summary-empty",
                f"resources/{summary_name} is empty",
                f"Describe each file in {dirname}/, or state explicitly that "
                "the paper has none.",
            )
            continue
        if not directory.is_dir():
            continue
        undescribed = sorted(
            path.name
            for path in directory.rglob("*")
            if path.is_file() and path.name not in text and path.stem not in text
        )
        if undescribed:
            report.fail(
                "summary-incomplete",
                f"{summary_name} does not mention: {', '.join(undescribed[:10])}"
                + (f" (+{len(undescribed) - 10} more)" if len(undescribed) > 10 else ""),
                f"Give every asset in {dirname}/ a caption keyed by its "
                "filename; an asset the writer cannot identify is unusable.",
            )


def _check_citations(report: ValidationReport) -> None:
    """The exact check the verifier runs, applied to the ground truth.

    If it fails here, the oracle cannot score `1.0` and the task is broken.
    """

    main = report.paper_dir / "original" / "main.tex"
    bibliography = report.paper_dir / "resources" / "references.bib"
    if not main.is_file() or not bibliography.is_file():
        return
    defined = _bib_keys(bibliography)
    if not defined:
        report.fail(
            "bib-empty",
            "resources/references.bib defines no entries",
            "Convert the paper's bibliography (including a `.bbl`-only or "
            "inline `\\bibitem` one) into real BibTeX entries.",
        )
        return
    missing = sorted(_citation_keys(_expand_tex(main)) - defined)
    if missing:
        report.fail(
            "citations-unresolved",
            f"main.tex cites {len(missing)} key(s) absent from references.bib: "
            f"{', '.join(missing[:10])}"
            + (f" (+{len(missing) - 10} more)" if len(missing) > 10 else ""),
            "The verifier fails a submission whose citations are not in "
            "references.bib, so the ground truth must satisfy it too. Add the "
            "real entries; never invent one.",
        )


# --------------------------------------------------------------------------- #
# oracle-equivalent compilation
# --------------------------------------------------------------------------- #


def _check_compiles(report: ValidationReport, build_root: Path) -> None:
    resources = report.paper_dir / "resources"
    if not (resources / "template.tex").is_file():
        return

    build_root.mkdir(parents=True, exist_ok=True)

    # 1. The writer's starting point. The task is unsolvable if the skeleton
    #    handed to the agent does not compile before it writes a word.
    report.compiles.append(
        compile_restricted(resources, "template.tex", build_root / "template")
    )

    # 2. The oracle. Reproduced rather than approximated: the converter's own
    #    materials copy, the shipped normalize.py, then the verifier's flags.
    original = report.paper_dir / "original"
    if not (original / "main.tex").is_file():
        return

    staging = build_root / "oracle"
    if staging.exists():
        shutil.rmtree(staging)
    environment_dir = staging / "environment"
    submission = staging / "submission"
    submission.mkdir(parents=True)
    try:
        stage_declared_copies(PWB_LAYOUT, report.paper_dir, staging, "short")
    except FileNotFoundError as error:
        report.fail("oracle-materials", str(error))
        return

    script = _render_normalize_script(staging / "normalize.py")
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(environment_dir / "materials"),
            str(submission),
            str(original),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        report.fail(
            "oracle-normalize",
            "the oracle's normalize.py failed on this paper:\n"
            + (result.stderr or result.stdout)[-2000:],
            "The oracle resolves every \\includegraphics/\\input against the "
            "public materials. Make sure each referenced asset exists in "
            "resources/figures/ or resources/tables/ under a resolvable name.",
        )
        return

    report.compiles.append(compile_restricted(submission, "main.tex", build_root / "oracle-build"))


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def validate_paper(
    paper_dir: Path,
    spec: PaperSpec,
    plugin: DomainPlugin,
    *,
    build_root: Path,
    run_compile: bool = True,
) -> ValidationReport:
    """Check one constructed paper against everything downstream assumes.

    `plugin` supplies the domain's paper-type taxonomy, overview skeleton and
    length bounds; everything else checked here is the same for every domain.

    `run_compile=False` exists for fast structural iteration only. It is never
    a way to admit a paper: :attr:`ValidationReport.compile_skipped_reason`
    records that solvability went unchecked.
    """

    report = ValidationReport(paper_id=spec.paper_id, paper_dir=paper_dir)
    if not paper_dir.is_dir():
        report.fail("missing-paper", f"{paper_dir} does not exist")
        return report

    _check_layout(report, spec)
    _check_config(report, spec, plugin)
    _check_provenance(report, spec)
    _check_template(report)
    _check_overviews(report, plugin)
    if plugin.require_table_inventory:
        _check_table_inventory(report)
    _check_summaries(report)
    _check_citations(report)

    if spec.research_type:
        from .evidence import validate_research_evidence

        try:
            validate_research_evidence(paper_dir, plugin.name, spec.research_type)
        except (ValueError, OSError) as error:
            report.fail("research-evidence", str(error), remedy="Repair located evidence and public support; do not weaken requirements.")

    if run_compile:
        _check_compiles(report, build_root)
    else:
        report.compile_skipped_reason = "run_compile=False"

    return report
