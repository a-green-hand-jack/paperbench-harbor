"""Typed, located research evidence and explicit public/private material gates."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .knowledge import get_knowledge_package

Text = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Location(Record):
    path: Text
    locator: Annotated[str, Field(pattern=r"^(?:image|line:[1-9][0-9]*|lines:[1-9][0-9]*-[1-9][0-9]*|page:[1-9][0-9]*|(?:figure|table|equation|lemma):[^\s:]+)$")]
    sha256: Digest


class Fact(Record):
    id: Text
    kind: Text
    statement: Text
    sources: list[Location] = Field(min_length=1)
    public_support: list[Location] = Field(min_length=1)


class Claim(Fact):
    evidence_ids: list[Text] = Field(min_length=1)
    limitations: list[Text] = Field(min_length=1)
    causal: bool = False


class Asset(Record):
    path: Text
    source_url: Text
    revision: Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64}|[^\s]+v[1-9][0-9]*)$")]
    license: Text
    sha256: Digest | None = None
    status: Literal["included", "missing", "excluded"]
    required: bool
    reason: str = ""

    @model_validator(mode="after")
    def complete(self):
        if self.status == "included" and self.sha256 is None:
            raise ValueError("included asset requires hash")
        if self.status != "included" and not self.reason.strip():
            raise ValueError("missing/excluded asset requires reason")
        return self


class LifeSciChecks(Record):
    biological_replicates: int = Field(ge=1)
    technical_replicates: int = Field(ge=1)
    design: Literal["interventional", "observational"]


class PhysicsChecks(Record):
    convergence_tolerance: float = Field(gt=0, allow_inf_nan=False)
    error_bound: float = Field(ge=0, allow_inf_nan=False)
    refinements: list[float] = Field(min_length=2)


class ChemistryChecks(Record):
    yield_percent: float = Field(ge=0, le=100)
    purity_percent: float = Field(ge=0, le=100)
    product_identity: Text
    characterized_identity: Text


class MathematicsChecks(Record):
    lemma_dependencies: dict[str, list[str]]
    requires_proof_discovery: Literal[False]


class ResearchEvidence(Record):
    schema_version: Literal[1]
    domain: Text
    research_type: Text
    knowledge_version: Text
    capability: Literal["writing_reconstruction"]
    question: Fact
    methods: list[Fact] = Field(min_length=1)
    assumptions: list[Fact] = Field(min_length=1)
    facts: list[Fact] = Field(min_length=1)
    claims: list[Claim] = Field(min_length=1)
    requirements: list[Fact] = Field(min_length=1)
    assets: list[Asset] = Field(min_length=1)
    # Research-type quantitative/relational checks supplement located facts.
    domain_checks: LifeSciChecks | PhysicsChecks | ChemistryChecks | MathematicsChecks


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_file(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if root.is_symlink() or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe material path: {relative}")
    target = root / path
    if any((root / Path(*path.parts[:i])).is_symlink() for i in range(1, len(path.parts) + 1)):
        raise ValueError(f"symlink material: {relative}")
    if not target.is_file() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"missing material: {relative}")
    return target


def contained_path(root: Path, path: Path, *, directory: bool = False) -> Path:
    """Accept only existing, unlinked paths lexically and physically beneath root."""
    root, path = root.absolute(), path.absolute()
    if not path.is_relative_to(root) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"artifact escapes run root: {path}")
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError(f"symlink artifact: {path}")
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError(f"missing artifact: {path}")
    return path


def source_fingerprint(root: Path) -> str:
    """Extraction depends on actual private assets and archived source code."""
    trees = {"original": tree_hash(root / "original")}
    if (root / "resources" / "code").exists():
        trees["code"] = tree_hash(root / "resources" / "code")
    return hashlib.sha256(json.dumps(trees, sort_keys=True).encode()).hexdigest()


def validate_locator(root: Path, relative: str, locator: str) -> None:
    path = safe_file(root, relative)
    if re.fullmatch(r"line:[1-9][0-9]*", locator):
        number = locator.split(":")[1]
        locator = f"lines:{number}-{number}"
    if locator == "image" and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        return
    match = re.fullmatch(r"lines:([1-9][0-9]*)-([1-9][0-9]*)", locator)
    if match:
        if int(match[1]) <= int(match[2]) <= len(path.read_text(encoding="utf-8").splitlines()):
            return
    elif re.fullmatch(r"page:[1-9][0-9]*", locator) and path.suffix.lower() == ".pdf":
        # PDF page existence is checked by the reviewer's PDF tool; syntax is not proof of content.
        return
    elif re.fullmatch(r"(?:figure|table|equation|lemma):[^\s:]+", locator):
        label = locator.split(":", 1)[1]
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".pdf") or label in path.read_text(encoding="utf-8"):
            return
    raise ValueError(f"invalid source locator: {relative}:{locator}")


def tree_hash(root: Path, *, exclude: tuple[str, ...] = ()) -> str:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"missing or linked material tree: {root}")
    entries = {}
    for path in sorted(root.rglob("*")):
        if set(path.relative_to(root).parts) & {".git", ".opencode", "__pycache__"} or path.relative_to(root).as_posix() in exclude:
            continue
        if path.is_symlink():
            raise ValueError(f"symlink material: {path.relative_to(root)}")
        if path.is_file():
            entries[path.relative_to(root).as_posix()] = file_hash(path)
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def validate_research_evidence(
    root: Path, domain: str, research_type: str, *, public_ready: bool = True
) -> ResearchEvidence:
    evidence = ResearchEvidence.model_validate_json(
        safe_file(root, "original/research_evidence.json").read_text(encoding="utf-8")
    )
    package = get_knowledge_package(domain, research_type)
    if (evidence.domain, evidence.research_type, evidence.knowledge_version) != (
        domain, research_type, package.version
    ):
        raise ValueError("evidence knowledge package mismatch")
    facts = [evidence.question, *evidence.methods, *evidence.assumptions, *evidence.facts,
             *evidence.claims, *evidence.requirements]
    ids = {fact.id for fact in facts}
    if len(ids) != len(facts):
        raise ValueError("duplicate fact IDs")
    missing = set(package.required_facts) - {fact.kind for fact in facts}
    if missing:
        raise ValueError(f"missing {domain} evidence: {', '.join(sorted(missing))}")
    for fact in facts:
        for private, locations in ((True, fact.sources), (False, fact.public_support)):
            if not private:
                for location in locations:
                    if public_ready and location.path == "resources/research_overview_long.md":
                        raise ValueError("short-protocol public requirement depends on the private long overview")
                    if not (location.path in {"resources/research_overview_short.md", "resources/research_overview_long.md", "resources/references.bib", "resources/figure_summary.txt", "resources/table_summary.txt", "resources/template.tex"}
                            or location.path.startswith(("resources/figures/", "resources/tables/", "resources/code/"))):
                        raise ValueError(f"public support is outside the adapter material allowlist: {location.path}")
            if not private and not public_ready:
                continue
            for location in locations:
                prefix = "original/" if private else "resources/"
                if not location.path.startswith(prefix):
                    raise ValueError(f"{fact.id}: wrong public/private location")
                path = safe_file(root, location.path)
                if file_hash(path) != location.sha256:
                    raise ValueError(f"{fact.id}: stale evidence hash: {location.path}")
                validate_locator(root, location.path, location.locator)
    for claim in evidence.claims:
        if set(claim.evidence_ids) - ids or claim.id in claim.evidence_ids:
            raise ValueError(f"{claim.id}: missing or self-referential support")
    for asset in evidence.assets:
        if asset.required and asset.status != "included":
            raise ValueError(f"required asset {asset.status}: {asset.path}: {asset.reason}")
        if asset.status == "included":
            if file_hash(safe_file(root, asset.path)) != asset.sha256:
                raise ValueError(f"stale source asset: {asset.path}")
            if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64}|[^\s]+v[1-9][0-9]*)", asset.revision):
                raise ValueError(f"asset revision is not immutable: {asset.path}")
    expected_checks = {"lifesci": LifeSciChecks, "physics": PhysicsChecks,
                       "chemistry": ChemistryChecks, "mathematics": MathematicsChecks}[domain]
    if not isinstance(evidence.domain_checks, expected_checks):
        raise ValueError("domain check schema does not match research type")  # noqa: TRY004
    checks = evidence.domain_checks.model_dump()
    if domain == "lifesci":
        for key in ("biological_replicates", "technical_replicates"):
            if type(checks.get(key)) is not int or checks[key] < 1:
                raise ValueError(f"{key} must be an explicit positive integer")
        if checks.get("design") not in ("interventional", "observational"):
            raise ValueError("explicit experimental design is required")
        if any(claim.causal for claim in evidence.claims) and checks["design"] != "interventional":
            raise ValueError("observational design cannot support causal claims")
    elif domain == "physics":
        for key in ("convergence_tolerance", "error_bound"):
            value = checks.get(key)
            if type(value) not in (int, float) or not 0 <= value < float("inf"):
                raise ValueError(f"{key} must be finite and nonnegative")
        if checks["convergence_tolerance"] == 0:
            raise ValueError("convergence_tolerance must be positive")
        grids = checks.get("refinements")
        if not isinstance(grids, list) or len(grids) < 2 or len(set(map(str, grids))) < 2:
            raise ValueError("convergence requires distinct refinements")
    elif domain == "chemistry":
        for key in ("yield_percent", "purity_percent"):
            if type(checks.get(key)) not in (int, float) or not 0 <= checks[key] <= 100:
                raise ValueError(f"{key} must be between 0 and 100")
        if not checks.get("product_identity") or checks.get("product_identity") != checks.get("characterized_identity"):
            raise ValueError("characterization identity must match product")
    else:
        graph = checks.get("lemma_dependencies")
        if not isinstance(graph, dict) or not graph:
            raise ValueError("lemma dependency graph required")
        pending = dict(graph)
        resolved = set()
        while pending:
            ready = [key for key, deps in pending.items()
                     if isinstance(deps, list) and all(isinstance(d, str) for d in deps)
                     and set(deps) <= resolved]
            if not ready:
                raise ValueError("circular or undefined lemma dependency")
            for key in ready:
                resolved.add(key)
                del pending[key]
        if checks.get("requires_proof_discovery") is not False:
            raise ValueError("proof discovery was not authorized")
    if public_ready:
        validate_boundary(root)
        public_requirements = json.loads(safe_file(root, "resources/writing_requirements.json").read_text())
        expected = [public_requirement(fact) for fact in evidence.requirements]
        if public_requirements != expected:
            raise ValueError("public writing requirements do not match private evaluation basis")
    return evidence


def public_requirement(fact: Fact) -> dict:
    supports = []
    for location in fact.public_support:
        relative = location.path.removeprefix("resources/")
        if relative in ("research_overview_short.md", "research_overview_long.md"):
            relative = "research_overview.md"
        supports.append({**location.model_dump(), "path": f"/workspace/materials/{relative}"})
    return {"id": fact.id, "statement": fact.statement, "public_support": supports}


def synchronize_research_materials(root: Path) -> None:
    """Generate mechanical public bindings after material/table generation, never private facts."""
    path = safe_file(root, "original/research_evidence.json")
    raw = json.loads(path.read_text())
    if isinstance(raw, dict):
        facts = [raw.get("question")]
        for group in ("methods", "assumptions", "facts", "claims", "requirements"):
            if isinstance(raw.get(group), list):
                facts.extend(raw[group])
        for fact in facts:
            if isinstance(fact, dict) and isinstance(fact.get("public_support"), list):
                for location in fact["public_support"]:
                    if isinstance(location, dict):
                        # Public hashes are derived output, not claims supplied by the model.
                        location["sha256"] = "0" * 64
    evidence = ResearchEvidence.model_validate(raw)
    for fact in (evidence.question, *evidence.methods, *evidence.assumptions,
                 *evidence.facts, *evidence.claims, *evidence.requirements):
        for location in fact.public_support:
            if not location.path.startswith("resources/"):
                raise ValueError("cannot bind private material as public evidence")
            location.sha256 = file_hash(safe_file(root, location.path))
    path.write_text(evidence.model_dump_json(indent=2) + "\n")
    requirements = [public_requirement(fact) for fact in evidence.requirements]
    (root / "resources" / "writing_requirements.json").write_text(json.dumps(requirements, indent=2) + "\n")


def validate_boundary(root: Path) -> None:
    from paperbench_harbor.common.audit import audit_public_materials

    code_approved = False
    provenance = root / "original" / "provenance.json"
    if provenance.is_file():
        record = json.loads(safe_file(root, "original/provenance.json").read_text())
        code_approved = (record.get("code_status", "available") == "available"
                         and bool(record.get("code_repo"))
                         and bool(re.fullmatch(r"[0-9a-f]{40}", record.get("code_commit", ""))))
    audit_public_materials(root / "resources", code_prefix="code", code_approved=code_approved)
    private = root / "original"
    private_hashes = {file_hash(p) for p in (private / "main.tex", private / "main.pdf")
                      if p.is_file() and not p.is_symlink()}
    for path in (root / "resources").rglob("*"):
        if path.is_symlink():
            raise ValueError(f"public symlink: {path.name}")
        if not path.is_file():
            continue
        # Whole-document copies are not shared scientific terminology or equations.
        if file_hash(path) in private_hashes:
            raise ValueError(f"whole source answer in public materials: {path.name}")
        if code_approved and path.is_relative_to(root / "resources" / "code"):
            continue
        if path.suffix in (".json", ".md", ".txt", ".tex", ".yaml"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"(?:original/|/tests/ground_truth|eval_points\.json|research_evidence\.json)", text):
                raise ValueError(f"private path or label in public materials: {path.name}")
