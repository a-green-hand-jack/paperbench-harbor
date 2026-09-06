"""Versioned model output contracts. Sources are evidence, never instructions."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ScientificContract(Record):
    version: Literal[3] = 3
    task_kind: Literal["full_manuscript", "summary"] = "full_manuscript"
    identifiers: Literal["identified", "anonymized"] = "identified"
    identifier_policy: str = "Identified tasks preserve accurate source names and bibliography. Anonymized tasks withhold focal identifiers from scientific prompts and use honest local citation metadata, but retain legally required credit in asset attribution; never fabricate author/year details or silently waive attribution. Reviews explicitly assess the selected policy and any legally necessary disclosure."
    selection: Literal["discovery", "fixed"] = "discovery"
    papers: list[str] = Field(default_factory=list)
    replacement: Literal["discover", "block"] = "discover"
    objective: str = "Write a full scientific manuscript, not a concise summary or notes dump."
    scientific_requirements: list[str] = Field(default_factory=lambda: [
        "Research question and hypotheses, including negative or unsupported hypotheses",
        "Scientific context and grounded bibliography",
        "Methods, design, assumptions and analysis needed to interpret the evidence",
        "Source-supported numerical results with relevant structured tables and figures",
        "Authors' interpretation distinguished from observations and new inference",
        "Limitations, uncertainty, inconsistencies and generalizability",
    ])
    source_policy: str = "Authentic original PDF mandatory; original TeX and dependencies only when genuinely acquired, with honest inspected availability."
    coverage_policy: str = "Inventory relevant figures, tables, supplements, methods, claims, hypotheses, authors interpretation and limitations item by item: include/substitute/exclude/unavailable, with evidence and reasons. Not every photograph or full experiment reproduction is required."
    rights_policy: str = "Assess actual rights and required attribution for each redistributed asset, including third-party exceptions. Anonymization never waives legal attribution: retain required credit or exclude/substitute the asset with a lawful supported alternative."
    acceptance_policy: str = "Three independent reviews assess this locked objective; template compilation alone is not a submission. Gate3 requires actual Harbor oracle=1 and nop=0 plus independent scientific review. Synthetic oracle is never original ground truth."

    @model_validator(mode="after")
    def selection_policy(self):
        if self.selection == "fixed":
            if not self.papers or self.replacement != "block" or len(set(self.papers)) != len(self.papers):
                raise ValueError("fixed selection requires unique canonical papers and replacement=block")
        elif self.papers or self.replacement != "discover":
            raise ValueError("discovery has no fixed allowlist and uses discovery replacements")
        return self


class Locator(Record):
    kind: Literal["lines", "page", "asset"]
    start: int = Field(ge=1)
    end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.end is not None and self.end < self.start:
            raise ValueError("locator end precedes start")
        return self


class Source(Record):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    url: str = Field(pattern=r"^https://")
    version: str = Field(
        min_length=1,
        description="Claimed remote version; controller records actual SHA256 snapshot identity and does not assert remote immutability",
    )
    license: str = Field(min_length=1)
    license_url: str = Field(pattern=r"^https://")
    metadata_url: str = Field(
        pattern=r"^https://",
        description="Authoritative publisher/repository landing page binding this source to its identity and license, not a generic license text",
    )
    # Persisted proposal inputs can be reprocessed; these claims are never evidence.
    identity_quote: SkipJsonSchema[str | None] = Field(default=None, exclude=True)
    license_quote: SkipJsonSchema[str | None] = Field(default=None, exclude=True)
    role: Literal["paper", "data", "code", "figure", "supplement", "license"]
    redistribution_basis: str = Field(min_length=1)
    attribution: str = Field(
        min_length=1,
        description="Source creators, title and required attribution; retained with private provenance",
    )
    local_path: str | None = Field(
        default=None,
        description="Optional path relative to imported user sources; URL remains provenance",
    )
    original_source_urls: list[str] = Field(
        default_factory=list,
        description="Actual original TeX/dependency download URLs from publisher/repository search, never a model recreation. Empty if no original source found; controller also searches publisher links and arXiv.",
    )


class Proposal(Record):
    title: str = Field(min_length=1)
    identity: str = Field(
        pattern=r"^(?:10\.[0-9]{4,9}/\S+|doi:\S+|arxiv:\S+|https://\S+)$",
        description="Proposed DOI/arXiv/source URL; controller derives identity from retrieved metadata",
    )
    writing_goal: str = Field(min_length=1)
    suitability: str = Field(min_length=1)
    code_applicability: Literal["required", "not_applicable"]
    code_reason: str = Field(min_length=1)
    sources: list[Source] = Field(
        min_length=1,
        description="Select one focal source with role paper. Do not list HTML and PDF as separate papers: the controller automatically acquires citation_pdf_url. Other entries are data/code/figures/supplements/licenses.",
    )

    @model_validator(mode="after")
    def source_ids(self):
        if len({s.id for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source ids")
        if any(s.id.endswith(("-license", "-metadata", "-publisher")) for s in self.sources):
            raise ValueError("source ids ending in -license/-metadata/-publisher are reserved")
        if not any(s.role == "paper" for s in self.sources):
            raise ValueError("a paper source is required")
        if self.code_applicability == "required" and not any(
            s.role == "code" for s in self.sources
        ):
            raise ValueError("scientifically necessary code is missing")
        return self


class Support(Record):
    source: str
    evidence_id: str | None = Field(
        default=None, description="Select an ID from the controller source-support catalog"
    )
    quote: str | None = Field(
        default=None,
        description="Alternative: a unique verbatim source excerpt; the controller resolves its location",
    )
    locator: SkipJsonSchema[Locator | None] = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def supported(self):
        if bool(self.evidence_id) == bool(self.quote):
            raise ValueError("select evidence_id OR a unique source quote")
        return self


class Material(Record):
    path: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_./-]*$")
    role: Literal["notes", "methods", "results", "data", "figure", "references", "template"]
    content: str = ""
    copy_source: str | None = None
    support: list[Support] = Field(min_length=1)
    rights: str = Field(min_length=1, description="Actual redistribution basis, third-party exceptions and required attribution for this asset; generated material must be labeled as such")
    attribution: str = Field(min_length=1)

    @model_validator(mode="after")
    def payload(self):
        if bool(self.content) == bool(self.copy_source):
            raise ValueError("provide content OR copy_source")
        if any(part in {"", ".", ".."} for part in self.path.split("/")):
            raise ValueError("path traversal")
        return self


class Requirement(Record):
    requirement: str = Field(min_length=1)
    section: str = Field(
        min_length=1, description="Required manuscript section containing this requirement"
    )
    public_paths: list[str] = Field(min_length=1)
    support: list[Support] = Field(min_length=1)


class CoverageItem(Record):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal["figure", "table", "supplement", "method", "claim", "hypothesis", "interpretation", "limitation", "context", "reference"]
    description: str = Field(min_length=1)
    disposition: Literal["include", "substitute", "exclude", "unavailable"]
    reason: str = Field(min_length=1)
    public_paths: list[str]
    support: list[Support] = Field(min_length=1)


class TableCell(Record):
    value: str = Field(description="Exact displayed source value; never silently round, impute or correct")
    support: list[Support] = Field(min_length=1)


class SourceTable(Record):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    caption: str = Field(min_length=1)
    columns: list[str] = Field(min_length=1)
    units: list[str] = Field(min_length=1, description="One explicit unit per column, or not_applicable")
    rows: list[list[TableCell]] = Field(min_length=1)
    notes: str = Field(min_length=1)
    missing_values: str = Field(min_length=1)
    precision: str = Field(min_length=1)
    rights: str = Field(min_length=1, description="Actual legal basis for redistributing this extracted/derived table, including exceptions")
    attribution: str = Field(min_length=1)
    original_image: str | None = Field(description="Public original table image path when acquired and legally redistributable")
    image_availability: str = Field(min_length=1, description="Actual acquisition/rights evidence or reason image unavailable")
    support: list[Support] = Field(min_length=1)

    @model_validator(mode="after")
    def rectangular(self):
        if len(self.units) != len(self.columns) or any(len(r) != len(self.columns) for r in self.rows):
            raise ValueError("table columns, units and cell rows must have matching widths")
        return self


class Materials(Record):
    writing_brief: str = Field(min_length=1)
    files: list[Material] = Field(min_length=1)
    requirements: list[Requirement] = Field(min_length=1)
    coverage: dict[str, str] = Field(
        description="methods/results/figures/tables/references/context"
    )
    private_reference: str = Field(min_length=1)
    exclusions: list[str]
    items: list[CoverageItem] = Field(min_length=1)
    tables: list[SourceTable]
    submission_sections: list[str] = Field(
        min_length=1,
        description="Required manuscript section headings appropriate to this writing goal; the structural verifier checks these",
    )

    @model_validator(mode="after")
    def sections(self):
        if len({i.id for i in self.items}) != len(self.items) or len({t.id for t in self.tables}) != len(self.tables):
            raise ValueError("coverage and table IDs must be unique")
        if any(
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .,:'()/?!-]*", heading.strip())
            for heading in self.submission_sections
        ):
            raise ValueError(
                "required headings must be plain ASCII words/punctuation, without LaTeX commands or special characters; use 'and' rather than '&'"
            )
        normalized = {" ".join(heading.casefold().split()) for heading in self.submission_sections}
        if len(normalized) != len(self.submission_sections) or any(
            len(heading.strip()) < 3 for heading in self.submission_sections
        ):
            raise ValueError("required section headings must be nonempty and unique")
        if any(
            " ".join(requirement.section.casefold().split()) not in normalized
            for requirement in self.requirements
        ):
            raise ValueError("every writing requirement must map to a required section")
        return self


class Evidence(Record):
    path: str = Field(
        description="Exact workspace-relative path from the controller evidence catalog"
    )
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: Locator
    quote: str = Field(min_length=12, description="Verbatim evidence inside the selected locator")


class Checked(Record):
    assessment: str = Field(min_length=30)
    evidence_ids: list[str] = Field(
        min_length=1,
        description="Select controller catalog IDs. Do not calculate hashes or coordinates.",
    )


class Finding(Record):
    classification: Literal["source", "license", "sufficiency", "fidelity", "leakage", "conversion"]
    evidence: str = Field(min_length=1)
    repair: str = Field(min_length=1)


class Review(Record):
    decision: Literal["accept", "repair", "reject"]
    reasoning: str = Field(min_length=1)
    checked: dict[str, Checked] = Field(min_length=1)
    findings: list[Finding]

    @model_validator(mode="after")
    def verdict(self):
        if (self.decision == "accept") != (not self.findings):
            raise ValueError(
                "accept requires no findings; repair/reject requires concrete findings"
            )
        return self
