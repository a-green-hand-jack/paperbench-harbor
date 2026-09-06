"""Four phases, three independent reviews, and hash-bound local delivery."""

import fcntl
import html
import json
import mimetypes
import re
import shutil
import signal
import subprocess
import time
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from paperbench_harbor.adapters.core.convert import (
    create_template_environment,
    prepare_task_directories,
    render_templates,
)
from paperbench_harbor.common.task_contract import assert_valid_task_contract
from paperbench_harbor.construction.core.state import atomic_json, fingerprint

from .ground_truth import acquire as acquire_ground_truth
from .ground_truth import validate as validate_ground_truth
from .identity import canonical_identity
from .integrity import (
    CONVERSION_EVIDENCE,
    MODEL_ROLES,
    bind_quote,
    catalog_paths,
    check_review,
    contained,
    evidence_catalog,
    load_state,
    located_quote,
    model_receipt,
    oracle_receipt,
    terminal_integrity,
)
from .integrity import (
    artifact_hash as digest,
)
from .metadata import SourceMetadata
from .network import retrieve
from .oracle import Oracle, compile_oracle
from .oracle import render as render_oracle
from .runtime import call, event
from .schema import Materials, Proposal, Review

ORDER = ("proposal", "gate1", "materials", "gate2", "convert", "gate3", "deliver")
MODEL = "openai/gpt-5.6-terra"
REVIEW_MODEL = "openai/gpt-5.6-sol"
TEMPLATES = Path(__file__).resolve().parents[1] / "common/templates"
GATES = {
    "gate1": (
        "original_availability",
        "sources",
        "licenses",
        "accessibility",
        "writing_suitability",
        "code_applicability",
        "answer_isolation",
    ),
    "gate2": (
        "ground_truth_comparison",
        "facts",
        "methods",
        "results",
        "figures",
        "tables",
        "references",
        "context",
        "writing_sufficiency",
        "answer_isolation",
    ),
    "gate3": (
        "ground_truth_packaging",
        "oracle",
        "layout",
        "instruction",
        "environment",
        "verifier",
        "submission",
        "fidelity",
        "determinism",
        "answer_isolation",
    ),
}


def read(path):
    return json.loads(path.read_text())


def implementation(stage):
    paths = [
        Path(__file__),
        Path(__file__).with_name("schema.py"),
        Path(__file__).with_name("integrity.py"),
        Path(__file__).with_name("ground_truth.py"),
        Path(__file__).with_name("oracle.py"),
    ]
    if stage == "proposal":
        paths.append(Path(__file__).with_name("network.py"))
        paths.append(Path(__file__).with_name("identity.py"))
        paths.append(Path(__file__).with_name("metadata.py"))
    if stage in {"proposal", "materials", "convert", "gate1", "gate2", "gate3"}:
        paths.append(Path(__file__).with_name("runtime.py"))
    if stage in {"convert", "gate3", "deliver"}:
        paths.append(TEMPLATES)
        package = Path(__file__).resolve().parents[1]
        paths.extend([package / "common/task_contract.py", package / "adapters/core/convert.py"])
    return fingerprint([digest(p) for p in paths])


def import_sources(source, destination):
    source = source.expanduser().absolute()
    if source.is_symlink() or not source.exists():
        raise ValueError("source must exist and cannot be a symlink")
    files = sorted(source.rglob("*")) if source.is_dir() else [source]
    allowed = {
        ".pdf",
        ".md",
        ".txt",
        ".tex",
        ".bib",
        ".csv",
        ".tsv",
        ".json",
        ".xml",
        ".html",
        ".png",
        ".jpg",
        ".jpeg",
        ".svg",
        ".py",
        ".r",
    }
    selected, size = [], 0
    for path in files:
        relative = path.relative_to(source) if source.is_dir() else Path(path.name)
        if path.is_symlink():
            raise ValueError("source tree contains a symlink")
        if path.is_dir():
            continue
        if (
            any(p.startswith(".") for p in relative.parts)
            or re.search(r"auth|credential|secret|token|api[-_]?key", path.name, re.IGNORECASE)
            or path.suffix.lower() not in allowed
        ):
            raise ValueError(
                "source tree contains a disallowed filename; provide a scoped research directory"
            )
        size += path.stat().st_size
        if (
            path.stat().st_size > 64 * 1024 * 1024
            or size > 256 * 1024 * 1024
            or len(selected) >= 5000
        ):
            raise ValueError("source import exceeds 64 MiB/file, 256 MiB total or 5000 files")
        selected.append((path, relative))
    destination.mkdir()
    for path, relative in selected:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def fetch_sources(proposal, destination, imported, cache=None):
    destination.mkdir()
    manifest = []
    provenance = []
    reused = []
    cache_records = read(cache / "manifest.json") if cache else []
    downloaded = {}
    for source in proposal.sources:
        captures = {}
        queue = [(source.id, source.url), (source.id + "-metadata", source.metadata_url)]
        publisher = None
        for label, url in queue:
            retrieved_at = time.time()
            cache_origin = None
            if label == source.id and source.local_path:
                local = contained(imported, imported / source.local_path)
                if not local.is_file():
                    raise ValueError("local source is outside the imported evidence")
                data = local.read_bytes()
                media = mimetypes.guess_type(local.name)[0] or "text/plain"
                final_url = url
                headers = {}
            else:
                cached = next(
                    (r for r in cache_records if url in {r["url"], r["resolved_url"]}), None
                )
                if cached:
                    raw_cache = contained(cache, cache / (cached["id"] + ".bin"))
                    if digest(raw_cache) != cached["sha256"]:
                        raise ValueError("source cache hash mismatch")
                    data, media, final_url, headers = (
                        raw_cache.read_bytes(),
                        cached["media_type"],
                        cached["resolved_url"],
                        cached.get("response_headers", {}),
                    )
                    reused.append({"path": str(raw_cache), "sha256": cached["sha256"]})
                    retrieved_at = cached["retrieved_at"]
                    cache_origin = str(raw_cache)
                else:
                    if url not in downloaded:
                        downloaded[url] = retrieve(url)
                    data, media, final_url, headers = downloaded[url]
            metadata = SourceMetadata(final_url)
            if "html" in media:
                metadata.feed(data.decode("utf-8", errors="replace"))
            elif label.endswith("-metadata") and (
                media == "application/json" or media.endswith("+json")
            ):
                metadata.structured(json.loads(data.decode("utf-8")))
            if label.endswith("-metadata"):
                publisher = metadata
                legal_url = next(
                    (record["url"] for record in publisher.licenses if record.get("url")),
                    source.license_url,
                )
                queue.append((source.id + "-license", legal_url))
            raw = destination / f"{label}.bin"
            raw.write_bytes(data)
            text_path = destination / f"{label}.txt"
            if data.startswith(b"%PDF"):
                shutil.copyfile(raw, destination / f"{label}.pdf")
                subprocess.run(
                    ["pdftotext", "-layout", str(raw), str(text_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif (
                media.startswith("text/")
                or media in {"application/json", "application/xml"}
                or media.endswith(("+json", "+xml"))
            ):
                text = data.decode("utf-8", errors="replace")
                if "html" in media:
                    text = re.sub(
                        r"<(script|style)\b[^>]*>.*?</\1>",
                        "",
                        text,
                        flags=re.DOTALL | re.IGNORECASE,
                    )
                    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
                text_path.write_text(text)
            else:
                text_path.write_text(
                    "Binary source; inspect the original asset visually if applicable."
                )
                extension = {
                    "image/png": ".png",
                    "image/jpeg": ".jpg",
                    "image/svg+xml": ".svg",
                }.get(media)
                if extension:
                    shutil.copyfile(raw, destination / f"{label}{extension}")
            record = {
                "claimed_version": source.version,
                "claimed_license": source.license,
                "version": "sha256:" + digest(raw),
                "remote_immutability": "not_asserted",
                "role": source.role if label == source.id else label.rsplit("-", 1)[1],
                "attribution": source.attribution,
                "redistribution_basis_claim": source.redistribution_basis,
                "id": label,
                "url": url,
                "resolved_url": final_url,
                "media_type": media,
                "sha256": digest(raw),
                "text_sha256": digest(text_path),
                "retrieved_at": retrieved_at,
                "reused_from": cache_origin,
                "response_headers": headers,
                "canonical_metadata": metadata.records,
            }
            manifest.append(record)
            captures[label] = record
        identity_binding, license_binding = publisher.bindings(
            destination, source.id, destination / f"{source.id}-metadata.bin"
        )
        acquired_assets, unavailable_assets = [], []
        if source.role == "paper":
            for asset_doi, asset in sorted(publisher.assets.items()):
                asset_id = source.id + "-asset-" + asset_doi.rsplit(".", 1)[1]
                if any(r["id"] == asset_id for r in manifest):
                    raise ValueError("publisher asset identifier collision")
                cached = next((r for r in cache_records if r["url"] == asset["url"]), None)
                try:
                    if cached:
                        cached_path = contained(cache, cache / (cached["id"] + ".bin"))
                        if digest(cached_path) != cached["sha256"]:
                            raise ValueError("cached publisher asset hash mismatch")
                        data, media, final_url, headers = (
                            cached_path.read_bytes(),
                            cached["media_type"],
                            cached["resolved_url"],
                            cached.get("response_headers", {}),
                        )
                        reused.append({"path": str(cached_path), "sha256": cached["sha256"]})
                    else:
                        data, media, final_url, headers = retrieve(asset["url"])
                    extension = (
                        ".png"
                        if data.startswith(b"\x89PNG\r\n\x1a\n")
                        else ".jpg"
                        if data.startswith(b"\xff\xd8")
                        else ".gif"
                        if data.startswith(b"GIF8")
                        else ".pdf"
                        if data.startswith(b"%PDF-")
                        else None
                    )
                    if extension is None:
                        raise ValueError("publisher asset is not a supported inspectable image/PDF")
                    raw = destination / f"{asset_id}.bin"
                    raw.write_bytes(data)
                    preview = destination / f"{asset_id}{extension}"
                    preview.write_bytes(data)
                    record = {
                        "id": asset_id,
                        "role": "figure",
                        "asset_kind": asset["kind"],
                        "url": asset["url"],
                        "resolved_url": final_url,
                        "media_type": media,
                        "sha256": digest(raw),
                        "version": "sha256:" + digest(raw),
                        "preview": preview.name,
                        "parent_source": source.id,
                        "retrieved_at": cached["retrieved_at"] if cached else time.time(),
                        "response_headers": headers,
                        "publisher_link": asset,
                        "rights_basis": "Parent article declaration; independent review must check caption exceptions",
                    }
                    manifest.append(record)
                    acquired_assets.append(record)
                except (OSError, RuntimeError, ValueError) as error:
                    unavailable_assets.append(
                        {"url": asset["url"], "kind": asset["kind"], "error": type(error).__name__}
                    )
        provenance.append(
            {
                "source_id": source.id,
                "source": captures[source.id],
                "metadata": captures[source.id + "-metadata"],
                "license_document": captures[source.id + "-license"],
                "identity_binding": identity_binding,
                "license_binding": license_binding,
                "publisher_license_identified": bool(publisher.licenses),
                "license_document_basis": "publisher_link"
                if any(r.get("url") for r in publisher.licenses)
                else "proposal_hint_only; publisher statement captured, no license version inferred",
                "authority_and_license_applicability": "requires_independent_gate1_review",
                "publisher_assets": acquired_assets,
                "unavailable_assets": unavailable_assets,
                "original_source_links": publisher.original_source_links,
                "original_source_candidates": publisher.original_source_candidates,
            }
        )
    atomic_json(destination / "manifest.json", manifest)
    atomic_json(destination / "provenance.json", provenance)
    atomic_json(destination / "identity.json", canonical_identity(destination))
    reused.extend(acquire_ground_truth(destination, proposal, cache))
    root = imported.parent
    atomic_json(destination / "source-support.json", catalog_paths(root, [destination], prefix="S"))
    return reused


def import_source_cache(previous, destination):
    """Copy verified acquisition inputs into a new run, never previous approvals."""
    state = load_state(previous, ORDER)
    destination.mkdir()
    records = []
    for candidate in state["candidates"]:
        entry = candidate["stages"].get("proposal", {})
        if entry.get("status") != "passed":
            continue
        model_receipt(previous, state["request"], "proposal", entry)
        source = contained(previous, Path(entry["path"]) / "sources")
        target = destination / candidate["id"]
        shutil.copytree(source, target)
        records.append({"candidate": candidate["id"], "proposal_sha256": entry["output_sha256"],
                        "sources_sha256": digest(target), "origin": str(source),
                        "acceptance": "cached bytes only; new proposal and all reviews required"})
    if not records:
        raise ValueError("source cache has no hash-verified completed proposal inputs")
    atomic_json(destination / "index.json", records)


def check_materials(materials, sources):
    paths = [f.path for f in materials.files]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate public paths")
    for path in paths:
        if any(path.startswith(other + "/") for other in paths):
            raise ValueError("public file/directory collision")
    required = {"methods", "results", "figures", "tables", "references", "context"}
    if not required <= materials.coverage.keys() or any(not v for v in materials.coverage.values()):
        raise ValueError(
            "coverage must explain each required dimension, including non-applicability"
        )
    manifest = {s["id"]: s for s in read(sources / "manifest.json")}
    source_catalog = read(sources / "source-support.json")
    root = sources.parents[3]
    for item in [*materials.files, *materials.requirements]:
        for support in item.support:
            if support.source not in manifest:
                raise ValueError("unknown evidence source")
            if support.evidence_id:
                anchor = source_catalog.get(support.evidence_id)
                if not anchor:
                    raise ValueError("unknown source-support evidence ID")
                path = contained(sources, root / anchor["path"])
                if not path.name.startswith(support.source + ".") and not path.name.startswith(
                    support.source + "-"
                ):
                    raise ValueError("support ID does not belong to the named source")
                if digest(path) != anchor["sha256"]:
                    raise ValueError("source-support hash mismatch")
                located_quote(path, anchor["locator"], anchor["quote"])
            else:
                bind_quote(sources / f"{support.source}.txt", support.quote)
        if hasattr(item, "public_paths") and not set(item.public_paths) <= set(paths):
            raise ValueError("writing requirement has no actual public support path")
    for item in materials.files:
        if any(
            word in item.path.lower() for word in ("private", "ground_truth", "oracle", "answer")
        ):
            raise ValueError("private answer filenames cannot enter public materials")
        if item.copy_source:
            source = manifest.get(item.copy_source)
            if not source or source["role"] not in {"figure", "data"}:
                raise ValueError(
                    "only explicitly reviewed data/figure assets may be copied publicly"
                )
    return materials


def convert(materials, sources, task):
    check_materials(materials, sources)
    validate_ground_truth(sources / "ground_truth")
    references = "\n".join(f.content for f in materials.files if f.role == "references")
    neutral_keys = set(re.findall(r"^\[([A-Za-z0-9:_-]+)\]\s*=", references, flags=re.MULTILINE))
    bib_keys = set(
        re.findall(
            r"@(?:article|book|inproceedings|misc|techreport|incollection|phdthesis)\s*\{\s*([^,\s]+)",
            references,
            flags=re.IGNORECASE,
        )
    )
    citation_keys = sorted(neutral_keys or bib_keys)
    if not citation_keys:
        raise ValueError(
            "reference materials must declare neutral [key] = mappings or BibTeX entries"
        )
    dirs = prepare_task_directories(task)
    public = dirs.environment / "materials"
    public.mkdir()
    for item in materials.files:
        target = public / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.copy_source:
            shutil.copyfile(sources / f"{item.copy_source}.bin", target)
        else:
            target.write_text(item.content)
    (dirs.tests_private / "reference_notes.md").write_text(
        "# Model-Generated Reference Notes\n\nNot original ground truth or an authoritative manuscript.\n\n"
        + materials.private_reference
    )
    shutil.copytree(sources / "ground_truth", dirs.tests_private / "ground_truth")
    shutil.copytree(sources, dirs.tests_private / "sources", ignore=shutil.ignore_patterns("ground_truth"))
    atomic_json(dirs.tests_private / "materials.json", materials.model_dump())
    env = create_template_environment(TEMPLATES)
    render_templates(
        env,
        task,
        templates={
            "task.toml": "task.toml.j2",
            "environment/Dockerfile": "environment_papersmith.Dockerfile.j2",
            "tests/Dockerfile": "tests.Dockerfile.j2",
            "tests/test.sh": "test.sh.j2",
            "tests/test_state.py": "test_state.py.j2",
        },
        context={
            "difficulty_explanation": "Scientific writing from reviewed research materials",
            "solution_explanation": "Synthetic grounded reference manuscript; not original ground truth",
            "verification_explanation": "Structural submission verification, not scientific certification",
            "category": "scientific-writing",
            "tags_toml": '["science", "writing"]',
            "relevant_experience": "Scientific reading and writing",
            "include_paper_orchestra": False,
            "grader_module": None,
            "papersmith_contract": materials.submission_sections,
            "papersmith_citation_keys": citation_keys,
            "papersmith_require_all_citations": bool(neutral_keys),
        },
    )
    (dirs.tests / "texmf").mkdir()
    (dirs.tests / "texmf/.keep").touch()
    instruction = materials.writing_brief + "\n\n## Materials\n"
    instruction += "\n".join(f"- `/workspace/materials/{p.path}`" for p in materials.files)
    instruction += "\n\n## Writing Requirements\n"
    for requirement in materials.requirements:
        instruction += (
            "\n- "
            + requirement.requirement
            + " Section: "
            + requirement.section
            + ". Support: "
            + ", ".join(f"`/workspace/materials/{path}`" for path in requirement.public_paths)
            + "\n"
        )
    instruction += (
        "\n\n## Submission Contract\nWrite a new scientific manuscript grounded in the supplied "
        "materials, not a reproduction of the source paper's prose. Do not retrieve the original "
        "paper or private reference answer. No new experiments or full reproduction is required. "
        "Submit `/workspace/submission/main.tex` and `/workspace/submission/references.bib`, "
        "with all figure and local source dependencies. main.tex must compile with pdflatex "
        "without shell escape. Every citation must be defined in references.bib. "
        "The verifier checks structure, compilation and citation integrity, not scientific quality.\n"
    )
    instruction += "\nStructural completeness: at least 200 prose words in the document body. "
    instruction += "Include these section headings, each with at least 20 prose words: "
    instruction += (
        ", ".join(materials.submission_sections)
        + ". These checks do not score scientific meaning.\n"
    )
    instruction += (
        "\nSource citation keys: " + ", ".join(f"`{key}`" for key in citation_keys) + ". "
    )
    instruction += (
        "Cite all declared neutral keys. "
        if neutral_keys
        else "Cite at least one supplied source key. "
    )
    instruction += "Define every cited key in references.bib and ensure BibTeX succeeds without undefined citations. For anonymized sources, cite the supplied local research materials; do not invent bibliographic details withheld by the task. The writer environment has no network access.\n"
    (task / "instruction.md").write_text(instruction)
    atomic_json(
        task / "manifest.json",
        {
            "schema_version": 2,
            "benchmark": "PaperSmith",
            "sources_sha256": digest(sources),
            "materials_sha256": fingerprint(materials.model_dump()),
            "public_files": {p.path: digest(public / p.path) for p in materials.files},
            "ground_truth_sha256": digest(sources / "ground_truth"),
        },
    )
    check_ground_truth_packaging(task, sources)
    assert_valid_task_contract(task)
    from harbor.models.task.task import Task

    if not Task.is_valid_dir(task):
        raise ValueError("installed Harbor rejects the task directory")
    parsed_task = Task(task)
    atomic_json(
        task / "harbor-validation.json",
        {
            "valid": True,
            "schema_version": parsed_task.config.schema_version,
            "validator": "harbor.models.task.task.Task",
            "harbor_version": version("harbor"),
            "scope": "configuration and artifact contract only; no Docker build or writer trial",
        },
    )


def check_ground_truth_packaging(task, sources):
    original = sources / "ground_truth"
    packaged = task / "tests/private/ground_truth"
    validate_ground_truth(packaged)
    if digest(original) != digest(packaged):
        raise ValueError("task does not contain the exact acquired private ground truth")
    private_hashes = {digest(p) for p in original.rglob("*") if p.is_file()}
    # Approved figures/data can also occur among original TeX dependencies.
    materials = Materials.model_validate(read(task / "tests/private/materials.json"))
    allowed_assets = {
        digest(task / "environment/materials" / item.path)
        for item in materials.files if item.copy_source and item.role in {"figure", "data"}
    }
    manuscript_hashes = {digest(original / name) for name in ("paper.pdf", "paper.txt", "paper.html")}
    for path in (task / "environment").rglob("*"):
        if path.is_file() and digest(path) in private_hashes and (
            digest(path) in manuscript_hashes or digest(path) not in allowed_assets
        ):
            raise ValueError("original ground truth leaked into writer image")
    # Full prose leakage is also reviewed semantically; exact long passages fail mechanically.
    private_texts = [(original / "paper.txt").read_text(),
                     (task / "tests/private/reference_notes.md").read_text()]
    public = " ".join((task / "instruction.md").read_text().split())
    for path in (task / "environment/materials").rglob("*"):
        if path.is_file() and path.suffix in {".txt", ".md", ".tex", ".json", ".html"}:
            public += " " + " ".join(path.read_text().split())
    for text in private_texts:
        words = text.split()
        if any(" ".join(words[i:i + 100]) in public for i in range(0, len(words) - 99, 20)):
            raise ValueError("long private manuscript/reference passage leaked publicly")


def inputs(request, candidate, stage):
    prior = ORDER[: ORDER.index(stage)]
    recovery = candidate["stages"].get(stage, {}).get("recovery_input")
    return fingerprint(
        {
            "request": request,
            "imported_sha256": digest(Path(request["imported"])),
            "source_cache_sha256": digest(Path(request["imported"]).parent / "source-cache"),
            "implementation": implementation(stage),
            "recovery_input": {**recovery, "actual_sha256": digest(Path(recovery["path"]))}
            if recovery
            else None,
            "previous": {
                key: candidate["stages"].get(key, {}).get("output_sha256") for key in prior
            },
        }
    )


def reusable(request, candidate, stage):
    entry = candidate["stages"].get(stage, {})
    if entry.get("evidence_version") != 2:
        return False
    if stage in MODEL_ROLES and entry.get("status") == "passed":
        try:
            model_receipt(Path(request["imported"]).parent, request, stage, entry)
        except (ValueError, OSError, KeyError, TypeError):
            return False
    if stage == "convert" and entry.get("status") == "passed":
        try:
            if not oracle_receipt(Path(request["imported"]).parent, request, entry):
                return False
        except (ValueError, OSError, KeyError, TypeError):
            return False
    return (
        entry.get("status") == "passed"
        and entry.get("input_sha256") == inputs(request, candidate, stage)
        and entry.get("output_sha256") == digest(Path(entry["path"]))
    )


def validate(root):
    state = load_state(root, ORDER)
    integrity_failures, legacy_evidence = terminal_integrity(root, state)
    ready, failures = [], []
    admitted_aliases = set()
    for candidate in state["candidates"]:
        if candidate.get("excluded"):
            continue
        try:
            for stage in ORDER:
                if not reusable(state["request"], candidate, stage):
                    raise ValueError(f"{stage}: missing, incomplete or stale evidence")
                if stage in GATES:
                    result = Review.model_validate(
                        read(Path(candidate["stages"][stage]["path"]) / "response.json")
                    )
                    check_review(root, candidate["stages"], stage, result, GATES, ORDER)
                    if (
                        result.decision != "accept"
                        or not set(GATES[stage]) <= result.checked.keys()
                    ):
                        raise ValueError(f"{stage}: review did not accept all dimensions")
            sessions = [
                model_receipt(root, state["request"], s, candidate["stages"][s])["sessions"][0]
                for s in ("proposal", "gate1", "materials", "gate2", "gate3")
            ]
            sessions += oracle_receipt(root, state["request"], candidate["stages"]["convert"])["sessions"]
            if len(sessions) != len(set(sessions)):
                raise ValueError("review/build sessions were reused")
            sources = Path(candidate["stages"]["proposal"]["path"]) / "sources"
            identity = canonical_identity(sources)
            if read(sources / "identity.json") != identity:
                raise ValueError("paper identity differs from retrieved metadata")
            if admitted_aliases.intersection(identity["aliases"]):
                raise ValueError("duplicate canonical paper identity/source")
            delivery = Path(candidate["stages"]["deliver"]["path"])
            if read(delivery / "delivery.json")["identity"] != identity["identity"]:
                raise ValueError("delivery identity does not match canonical source metadata")
            task = delivery / candidate["id"]
            check_ground_truth_packaging(task, sources)
            if not (task / "solution/solve.sh").is_file():
                raise ValueError("task lacks a real Harbor oracle solution")
            assert_valid_task_contract(task)
            if digest(task) != digest(Path(candidate["stages"]["convert"]["path"]) / "task"):
                raise ValueError("delivered task differs from reviewed conversion")
            ready.append(str(task))
            admitted_aliases.update(identity["aliases"])
        except (ValueError, OSError, KeyError, TypeError, IndexError) as error:
            failures.append({"candidate": candidate["id"], "reason": str(error)})
    return {
        "workspace": str(root),
        "status": state["status"],
        "target_count": state["request"]["count"],
        "task_ready": not integrity_failures and len(ready) >= state["request"]["count"],
        "task_ready_count": len(ready),
        "tasks": ready,
        "failures": failures,
        "integrity_failures": integrity_failures,
        "legacy_evidence": legacy_evidence,
        "candidates": state["candidates"],
        "events": str(root / "events.jsonl"),
        "checkpoint": str(root / "run.json"),
        "blocked_reason": state.get("blocked_reason"),
    }


def run(root):
    with contained(root, root / ".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("workspace already has an active controller") from None
        state = load_state(root, ORDER)
        integrity_failures, _ = terminal_integrity(root, state)
        if integrity_failures:
            raise ValueError(
                "terminal evidence integrity failure; inspect papersmith validate before resuming"
            )
        request = state["request"]
        invocation = uuid4().hex

        def save():
            atomic_json(root / "run.json", state)

        def stop(signum, frame):
            raise KeyboardInterrupt

        old = signal.signal(signal.SIGTERM, stop)
        state["status"] = "running"
        state.pop("error", None)
        state.pop("blocked_reason", None)
        save()
        try:
            while not validate(root)["task_ready"]:
                candidate = next(
                    (
                        c
                        for c in state["candidates"]
                        if not c.get("excluded") and not all(reusable(request, c, s) for s in ORDER)
                    ),
                    None,
                )
                if candidate is None:
                    candidate = {
                        "id": f"candidate-{len(state['candidates']) + 1:04d}",
                        "stages": {},
                        "history": [],
                        "feedback": "",
                    }
                    state["candidates"].append(candidate)
                for stage in ORDER:
                    if reusable(request, candidate, stage):
                        event(root, "checkpoint_reused", candidate=candidate["id"], phase=stage)
                        continue
                    previous = candidate["stages"].get(stage)
                    if previous and previous["status"] == "passed":
                        event(
                            root,
                            "checkpoint_invalidated",
                            candidate=candidate["id"],
                            phase=stage,
                            reason="implementation, inputs or evidence contract changed",
                            previous_input_sha256=previous["input_sha256"],
                            previous_output_sha256=previous["output_sha256"],
                        )
                    for later in ORDER[ORDER.index(stage) :]:
                        if later in candidate["stages"]:
                            candidate["history"].append(
                                {"phase": later, **candidate["stages"].pop(later)}
                            )
                    attempt = root / "attempts" / candidate["id"] / f"{stage}-{uuid4().hex}"
                    attempt.mkdir(parents=True)
                    entry = {
                        "evidence_version": 2,
                        "status": "running",
                        "path": str(attempt),
                        "started_at": time.time(),
                        "input_sha256": inputs(request, candidate, stage),
                    }
                    candidate["stages"][stage] = entry
                    save()
                    event(
                        root,
                        "phase_started",
                        candidate=candidate["id"],
                        phase=stage,
                        path=str(attempt),
                    )
                    try:
                        stages = candidate["stages"]
                        proposal_dir = Path(stages["proposal"]["path"])
                        sources = proposal_dir / "sources"
                        context = (
                            f"User request: {request['prompt']}\n"
                            "That request selects sources. The deliverable is a Harbor WRITING TASK for a downstream writer, not a paper-recommendation report. Evaluate sufficiency for the declared writing brief. Original manuscripts and private reference prose remain private; accurate bibliographic metadata for citations and license attribution is allowed.\n"
                            f"The controller handles a batch target of {request['count']} admitted tasks. This phase concerns ONLY ONE paper for {candidate['id']}. Do not require additional papers in this per-candidate proposal; the controller replenishes and delivers the other tasks.\n"
                            f"User-supplied scientific sources, if any: {root / 'imported'}. "
                            "You may select their relative filenames as local_path; URLs still record "
                            "original public provenance and license evidence. Never execute imported code.\n"
                            f"Repair feedback: {candidate['feedback']}\n"
                        )
                        if stage == "proposal":
                            recovery = next(
                                (
                                    h
                                    for h in reversed(candidate["history"])
                                    if h["phase"] == "proposal"
                                    and h["status"] == "passed"
                                    and h.get("output_sha256") == digest(Path(h["path"]))
                                ),
                                None,
                            )
                            recovered = None
                            if recovery:
                                recovered = contained(root, Path(recovery["path"]))
                                receipt = read(recovered / "receipt.json")
                                if (
                                    receipt.get("model") != request["model"]
                                    or receipt.get("role") != "proposal builder"
                                    or receipt.get("returncode") != 0
                                    or len(receipt.get("sessions", [])) != 1
                                ):
                                    raise ValueError(
                                        "recovery input lacks a real successful proposal receipt"
                                    )
                                Proposal.model_validate(read(recovered / "response.json"))
                                entry["recovery_input"] = {
                                    "path": str(recovered),
                                    "sha256": recovery["output_sha256"],
                                }
                                entry["input_sha256"] = inputs(request, candidate, stage)
                                save()
                                event(
                                    root,
                                    "proposal_input_recovered",
                                    candidate=candidate["id"],
                                    path=str(recovered),
                                    sha256=recovery["output_sha256"],
                                    acceptance="reprocess_and_review_required",
                                )
                            excluded = set()
                            for other in state["candidates"]:
                                if other is candidate or "proposal" not in other["stages"]:
                                    continue
                                prior = Path(other["stages"]["proposal"]["path"]) / "sources"
                                if (prior / "provenance.json").is_file():
                                    excluded.update(canonical_identity(prior)["aliases"])
                            local = (root / "imported").is_dir()
                            # Public discovery never sees private artifacts or raw repair feedback.
                            proposal_context = (
                                context
                                if local
                                else (
                                    f"Public paper-selection request: {request['prompt']}\n"
                                    "This is public discovery only. No workspace files are available. "
                                    "If retrying, provide a schema-correct proposal with accessible, exact metadata and license evidence.\n"
                                )
                            )
                            if recovered:
                                proposal_context = (
                                    context + f"Recovery input: {recovered / 'response.json'}. "
                                )
                                proposal_context += "Re-express this SAME completed scientific candidate in the current schema. Do not rediscover another paper merely because old mechanical hash/quote/locator checks failed. No identity/license quotes or hashes are requested. The controller will re-extract and verify fetched publisher metadata and license links. This is a new proposal session, not inherited approval.\n"
                                proposal_context += f"Read the actual source snapshots and source-support catalog in {recovered / 'sources'}, not only the previous model's claims. Use .txt/.json/.pdf previews and catalog excerpts rather than opaque .bin files. Correct title, date, stated license name and writing scope against the source and repair feedback. A historical PLOS Open-Access License must not be relabeled CC BY without evidence; an article URL carrying its actual license statement can be the license_url.\n"
                            result, _receipt = call(
                                root,
                                attempt,
                                request["model"],
                                "proposal builder",
                                proposal_context
                                + "Discover ONE real scientific paper matching the request. Any topic is "
                                "allowed; no domain package required. Use web search/fetch to verify real sources. "
                                "Choose legally usable accessible sources with explicit license evidence and pinned "
                                "versions. Code is only required when scientifically necessary to support the writing "
                                "task; justify not_applicable, never waive source licenses. A genuine publisher/repository PDF is MANDATORY, even when selecting HTML for extraction. Search for original TeX and dependency archives and supply original_source_urls if obtainable; never recreate original source. Prefer accessible HTML, "
                                "PDF, text, figures, CSV or JSON, not opaque archives. Supply all necessary material "
                                "URLs plus an authoritative publisher/repository metadata_url. Do NOT supply exact identity/license quotes, hashes or line counts; the controller extracts those from actual publisher metadata. A generic Creative Commons legal page alone does not "
                                "bind a license to a paper. Remote version strings are claims, not immutable proof: the "
                                "controller retrieves canonical metadata/headers and pins actual source snapshots by SHA256. "
                                "URLs and license pages. Do not propose these identities again: "
                                + json.dumps(
                                    sorted(a for a in excluded if a.startswith(("doi:", "arxiv:")))
                                ),
                                Proposal,
                                read_paths=(recovered / "response.json", recovered / "sources")
                                if recovered
                                else (root / "imported",)
                                if local
                                else (),
                                network=not (local or recovered),
                            )
                            cache = recovered / "sources" if recovered else None
                            if cache is None and (root / "source-cache/index.json").is_file():
                                urls = {s.url for s in result.sources if s.role == "paper"}
                                for record in read(root / "source-cache/index.json"):
                                    cached = contained(root / "source-cache", root / "source-cache" / record["candidate"])
                                    if digest(cached) != record["sources_sha256"]:
                                        raise ValueError("imported source cache hash mismatch")
                                    if any(r["role"] == "paper" and urls.intersection({r["url"], r["resolved_url"]})
                                           for r in read(cached / "manifest.json")):
                                        cache = cached
                                        break
                            reused = fetch_sources(
                                result,
                                sources,
                                root / "imported",
                                cache,
                            )
                            for snapshot in reused:
                                event(
                                    root,
                                    "source_snapshot_reused",
                                    candidate=candidate["id"],
                                    **snapshot,
                                )
                            identity = canonical_identity(sources)
                            if recovered and not set(
                                canonical_identity(recovered / "sources")["aliases"]
                            ).intersection(identity["aliases"]):
                                raise ValueError(
                                    "mechanical recovery must retain the original paper identity; source-access failures are not a reason to invent a replacement"
                                )
                            if excluded.intersection(identity["aliases"]):
                                raise ValueError(
                                    "duplicate paper from canonical metadata/source; discover a new paper"
                                )
                            candidate["identity"] = identity["identity"]
                        elif stage == "materials":
                            result, _receipt = call(
                                root,
                                attempt,
                                request["model"],
                                "materials builder",
                                context
                                + f"Read proposal {proposal_dir / 'response.json'} and ALL original sources "
                                f"and extracted text in {sources}. Produce faithful pre-writing materials, not a "
                                "finished manuscript, rewritten paper sections or an oracle. Preserve facts, methods, "
                                "numerical results, tables, figure meaning, references and context with exact support "
                                "evidence. Select source-support.json evidence IDs, or provide a unique actual source quote whose location the controller will resolve. Never calculate line counts or hashes. Include actual raw/structured data and figure assets when necessary. "
                                "Judge sufficiency for WRITING, not full experiment reproduction. For each requirement "
                                "name public support files. Explain coverage/non-applicability of methods, results, "
                                "figures, tables, references, context. Original paper and full reference prose stay "
                                "private. Supply accurate bibliographic metadata for the focal source, with a usable BibTeX entry or declared citation-key mapping; do not invent bibliographic details or expose the full source manuscript/private reference prose. Inspect publisher figure/table assets and cite their S catalog IDs for visual support; preserve and explain source inconsistencies instead of silently correcting numbers. A blank article template is sufficient, no domain-specific template "
                                "required. No fake evidence. copy_source can only copy a data or figure source id.",
                                Materials,
                                read_paths=(proposal_dir / "response.json", sources),
                            )
                            check_materials(result, sources)
                        elif stage == "convert":
                            materials = Materials.model_validate(
                                read(Path(stages["materials"]["path"]) / "response.json")
                            )
                            convert(materials, sources, attempt / "task")
                            convert(materials, sources, attempt / "determinism")
                            oracle_attempt = attempt / "oracle"
                            oracle_attempt.mkdir()
                            oracle, _receipt = call(
                                root, oracle_attempt, request["model"], "oracle builder",
                                "Author a scientifically meaningful, complete new reference manuscript satisfying EVERY requirement in "
                                + str(attempt / "task/instruction.md")
                                + ". Read ONLY the audited public materials in "
                                + str(attempt / "task/environment/materials")
                                + ". This is a SYNTHETIC ORACLE, never original ground truth. Write coherent scientific argument, methods, numerical results, interpretation and limitations as appropriate to the actual brief, not a dump of notes or filler to meet word thresholds. No fabricated experiments, claims or bibliographic details. Include required tables and figures with faithful captions. Use exact required headings in order. Plain text fields only, no TeX/Markdown commands; the controller renders TeX and citations. Supply accurate bibliography entries using the public citation keys. Explain coverage of each requirement separately, in declared order. Use ASCII spellings or standard pdflatex-supported Unicode. "
                                + "Do not read private sources, original paper or prior review feedback. "
                                + "Mechanical retry category: "
                                + ("conversion_retry" if previous else "initial_conversion")
                                + ". Recheck the public submission contract. No private error text or review feedback is provided.",
                                Oracle,
                                read_paths=(attempt / "task/instruction.md", attempt / "task/environment/materials"),
                            )
                            for name in ("task", "determinism"):
                                render_oracle(oracle, materials, attempt / name, attempt / name / "solution")
                            if digest(attempt / "task") != digest(attempt / "determinism"):
                                raise ValueError("fixed-material conversion is not deterministic")
                            compile_oracle(attempt / "task/solution", attempt / "oracle-build")
                            for name in ("preview.pdf", "preview.txt", "validation.json"):
                                shutil.copyfile(attempt / "task/solution" / name,
                                                attempt / "determinism/solution" / name)
                            atomic_json(
                                attempt / "checks.json",
                                {"deterministic": True, "task_sha256": digest(attempt / "task"),
                                 "scope": "fixed materials and fixed synthetic oracle response render identical task sources; compiled preview reused byte-for-byte",
                                 "oracle_response_sha256": digest(oracle_attempt / "response.json"),
                                 "oracle_receipt_sha256": digest(oracle_attempt / "receipt.json"),
                                 "ground_truth_sha256": digest(sources / "ground_truth")},
                            )
                        elif stage in GATES:
                            review_paths = [proposal_dir / "response.json", sources]
                            if stage in {"gate2", "gate3"}:
                                review_paths.append(
                                    Path(stages["materials"]["path"]) / "response.json"
                                )
                            if stage == "gate3":
                                conversion = Path(stages["convert"]["path"])
                                review_paths.extend(
                                    conversion / p for p in ("task", "determinism", "checks.json")
                                )
                            evidence = [str(path) for path in review_paths]
                            catalog = evidence_catalog(root, stages, stage, ORDER)
                            catalog_path = attempt / "evidence-catalog.json"
                            atomic_json(catalog_path, catalog)
                            review_paths.append(catalog_path)
                            index = {}
                            for eid, anchor in catalog.items():
                                index.setdefault(anchor["path"], []).append(eid)
                            bindings = {
                                eid: anchor
                                for eid, anchor in catalog.items()
                                if anchor.get("binding")
                            }
                            gate_schema = Review.model_json_schema()
                            checked_type = gate_schema["properties"]["checked"][
                                "additionalProperties"
                            ]
                            gate_schema["properties"]["checked"] = {
                                "type": "object",
                                "properties": {d: checked_type for d in GATES[stage]},
                                "required": list(GATES[stage]),
                                "additionalProperties": False,
                            }
                            mandatory = (
                                {
                                    dimension: [
                                        eid
                                        for eid, anchor in catalog.items()
                                        if anchor["path"].endswith("/" + suffix)
                                    ]
                                    for dimension, suffix in CONVERSION_EVIDENCE.items()
                                }
                                if stage == "gate3"
                                else {}
                            )
                            dimension = {"gate1": "original_availability", "gate2": "ground_truth_comparison",
                                         "gate3": "ground_truth_packaging"}[stage]
                            mandatory[dimension + "_original_files"] = {
                                name: [eid for eid, anchor in catalog.items()
                                       if anchor["path"] == (sources / "ground_truth" / name).relative_to(root).as_posix()]
                                for name in ("paper.pdf", "paper.txt", "manifest.json")
                            }
                            if stage == "gate3":
                                mandatory["oracle_artifacts"] = {
                                    name: [eid for eid, anchor in catalog.items() if anchor["path"].endswith("/task/solution/" + name)]
                                    for name in ("manuscript/main.tex", "preview.pdf", "validation.json")
                                }
                            result, _receipt = call(
                                root,
                                attempt,
                                request["review_model"],
                                f"independent {stage} reviewer",
                                context
                                + "Independently inspect actual evidence at these paths: "
                                + json.dumps(evidence)
                                + f". Read the controller evidence catalog {catalog_path}. Each record contains id/path/hash/actual locator/excerpt. Return ONLY selected evidence_ids and substantive assessments, never hashes or coordinates. File-to-ID index: "
                                + json.dumps(index)
                                + ". Mandatory conversion-evidence IDs by dimension (select at least one for each listed dimension): "
                                + json.dumps(mandatory)
                                + ". Publisher binding anchors (select identity_binding IDs for sources, license_binding IDs for licenses; also cite a provenance.json ID for licenses): "
                                + json.dumps(bindings)
                                + ". Every checked dimension requires relevant selected IDs. No placeholder acceptances. Accepting any gate requires completed direct read tool calls for the proposal sources/ground_truth/paper.pdf AND paper.txt, not just their catalog entries. Gate3 also requires a completed direct read of task/solution/preview.pdf. "
                                "For gate1 inspect EVERY source's identity/license bindings; the controller parsed real publisher tags, not a model-authored quote. These extractions are not approvals. Compare "
                                "bindings against the actual publisher/repository metadata. Judge authority, applicable "
                                "rights and exclusions, not just the existence of a license string. "
                                + ". Do not trust builder claims or prior reviews. Read the original source text and "
                                "license evidence; compare all relevant public materials with source facts. Inspect "
                                "binary figures visually when relevant, reject if unavailable. Scope is sufficient "
                                "pre-writing materials, NOT full experiment reproduction. Code can be scientifically "
                                 "not applicable, licenses cannot be waived. Gate1 original_availability MUST inspect ground_truth/paper.pdf, its extracted paper.txt, manifest identity/page/readability checks and original_tex search evidence. Explicitly assess actual original TeX/dependency completeness and bundle-specific rights when retrieved, otherwise its evidenced unavailability; never infer third-party bundle rights from the article license or call recreated text original source. Gate2 ground_truth_comparison MUST compare the actual private original PDF/text against the generated materials, not reference notes as authority. No writer trial or reward=1 prerequisite. "
                                 "Gate3 inspects actual Harbor directory, private/public separation, generated verifier "
                                 "and exact tests/private/ground_truth bytes against proposal ground_truth. Inspect solution/manuscript, solution/preview.pdf and solution/provenance.json: independently assess scientific meaning, every explicit writing requirement, accurate grounded bibliography and local assets against the actual private original and public materials. The synthetic oracle must be a legitimate new manuscript, not copied original prose, a notes dump, dummy padding, original PDF submission or reward/verifier manipulation. Report blocking conversion/fidelity findings for any failure. "
                                "and deterministic conversion evidence. A structural verifier is not a science judge. "
                                "Return accept only with no blocking findings. Supply concrete evidence and repair "
                                "actions otherwise; reject means this candidate cannot be used and needs replacement. "
                                "Every checked dimension needs a substantive evidence-grounded explanation: "
                                + json.dumps(GATES[stage]),
                                Review,
                                read_paths=tuple(review_paths),
                                output_schema=gate_schema,
                            )
                            resolved = check_review(root, stages, stage, result, GATES, ORDER)
                            atomic_json(attempt / "review-bindings.json", resolved)
                            entry["decision"] = result.decision
                            if result.decision != "accept":
                                entry["status"] = "rejected"
                                entry["output_sha256"] = digest(attempt)
                                candidate["feedback"] = result.model_dump_json()
                                if result.decision == "reject":
                                    candidate["excluded"] = result.model_dump()
                                else:
                                    repair = (
                                        "proposal"
                                        if stage == "gate1"
                                        or any(
                                            f.classification in {"source", "license"}
                                            for f in result.findings
                                        )
                                        else "materials"
                                    )
                                    candidate["stages"][repair]["status"] = "repair"
                                save()
                                event(
                                    root,
                                    "review_rejected",
                                    phase=stage,
                                    candidate=candidate["id"],
                                    decision=result.decision,
                                )
                                break
                        else:
                            delivered = attempt / candidate["id"]
                            shutil.copytree(Path(stages["convert"]["path"]) / "task", delivered)
                            atomic_json(
                                attempt / "delivery.json",
                                {
                                    "task": str(delivered),
                                    "reviews": {g: stages[g] for g in GATES},
                                    "identity": canonical_identity(sources)["identity"],
                                    "publication": "not_requested",
                                     "writer_trial": "not_requested",
                                     "harbor_oracle_nop_acceptance": "pending_trusted_host_execution",
                                },
                            )
                        entry.update(
                            status="passed", output_sha256=digest(attempt), finished_at=time.time()
                        )
                        candidate.setdefault("mechanical_failures", {}).pop(stage, None)
                        save()
                        event(root, "phase_passed", candidate=candidate["id"], phase=stage)
                    except ValueError as error:
                        # Malformed/unsupported model artifacts receive targeted automatic repairs.
                        detail = (
                            json.dumps(
                                [
                                    {k: e[k] for k in ("loc", "type", "msg")}
                                    for e in error.errors(include_input=False, include_url=False)
                                ]
                            )
                            if isinstance(error, ValidationError)
                            else str(error)
                        )
                        tally = candidate.setdefault("mechanical_failures", {}).get(stage, {})
                        count = (
                            tally.get("count", 0) + 1
                            if tally.get("invocation") == invocation
                            else 1
                        )
                        candidate["mechanical_failures"][stage] = {
                            "invocation": invocation,
                            "count": count,
                            "error_signature": fingerprint(detail),
                        }
                        entry.update(
                            status="failed",
                            finished_at=time.time(),
                            error=detail,
                            output_sha256=digest(attempt),
                        )
                        candidate["feedback"] = detail
                        save()
                        event(
                            root,
                            "artifact_repair",
                            candidate=candidate["id"],
                            phase=stage,
                            error=detail,
                            consecutive_mechanical_failures=count,
                        )
                        if count >= 3:
                            state["blocked_reason"] = {
                                "phase": stage,
                                "classification": "repeated_mechanical_validation",
                                "attempts": count,
                                "error": detail,
                                "path": str(attempt),
                                "remedy": "Fix schema/controller or source access before explicitly resuming; this is not scientific rejection.",
                            }
                            save()
                            raise RuntimeError("repeated mechanical validation failure") from error
                        break
            state["status"] = "task_ready"
            save()
        except BaseException as error:
            state["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "blocked"
            for current in state["candidates"]:
                for phase, record in current["stages"].items():
                    if record["status"] == "running":
                        state.setdefault(
                            "blocked_reason",
                            {
                                "phase": phase,
                                "classification": state["status"],
                                "error": type(error).__name__,
                                "path": record["path"],
                                "remedy": "Inspect this attempt's receipt and source access; fix infrastructure/controller before resuming.",
                            },
                        )
                        record.update(
                            status=state["status"],
                            finished_at=time.time(),
                            error=type(error).__name__,
                            output_sha256=digest(Path(record["path"])),
                        )
            # Raw provider/network exceptions can include URLs or credentials: retain only class.
            state["error"] = type(error).__name__
            save()
            event(
                root,
                "run_stopped",
                status=state["status"],
                error=type(error).__name__,
                blocked_reason=state.get("blocked_reason"),
            )
            raise
        finally:
            signal.signal(signal.SIGTERM, old)
    return validate(root)
