"""Evidence locations and persisted checkpoint boundaries, without model claims."""

import hashlib
import json
import re
from bisect import bisect_right
from pathlib import Path

from paperbench_harbor.construction.core.state import fingerprint

from .schema import Locator

MODEL_ROLES = {
    "proposal": "proposal builder",
    "materials": "materials builder",
    "oracle": "oracle builder",
    **{gate: f"independent {gate} reviewer" for gate in ("gate1", "gate2", "gate3")},
}

CONVERSION_EVIDENCE = {
    "template_compilation": "template-proof/validation.json",
    "instruction": "instruction.md",
    "environment": "environment/Dockerfile",
    "verifier": "tests/test_state.py",
    "submission": "instruction.md",
    "layout": "harbor-validation.json",
    "determinism": "checks.json",
    "ground_truth_packaging": "tests/private/ground_truth/manifest.json",
    "oracle": "solution/provenance.json",
}


def artifact_hash(path):
    if path.is_symlink():
        raise ValueError("symlinks are not valid evidence")
    if not path.exists():
        return "missing"
    if path.is_file():
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    return fingerprint(
        {
            p.relative_to(path).as_posix(): artifact_hash(p)
            for p in sorted(path.rglob("*"))
            if p.is_file() or p.is_symlink()
        }
    )


def model_receipt(root, request, phase, entry):
    attempt = contained(root, Path(entry["path"]))
    if entry.get("output_sha256") != artifact_hash(attempt):
        raise ValueError("terminal attempt artifact hash is missing or mismatched")
    receipt = json.loads(contained(root, attempt / "receipt.json").read_text())
    if entry.get("contract_sha256"):
        contract = request["contract"]
        if phase == "oracle":
            contract = {k: v for k, v in contract.items() if k not in {"selection", "papers", "replacement"}}
        if receipt.get("request_scope_sha256") != fingerprint({"contract": contract, "count": entry["scope_count"]}):
            raise ValueError("model receipt does not bind locked contract and original candidate count")
    if receipt.get("schema_version") != 2:
        raise ValueError("legacy receipt cannot establish current acceptance; rerun this node")
    expected_model = request["review_model" if phase.startswith("gate") else "model"]
    if receipt.get("model") != expected_model or receipt.get("role") != MODEL_ROLES[phase]:
        raise ValueError("receipt model/role does not match the phase")
    sessions = receipt.get("sessions")
    if (
        not isinstance(sessions, list)
        or len(sessions) > 1
        or any(not isinstance(s, str) or not re.fullmatch(r"ses_[A-Za-z0-9]+", s) for s in sessions)
    ):
        raise ValueError("receipt has invalid session identity")
    if receipt.get("request_sha256") != artifact_hash(contained(root, attempt / "request.txt")):
        raise ValueError("receipt request hash mismatch")
    response = contained(root, attempt / "response.json")
    expected_hash = artifact_hash(response) if response.exists() else None
    if receipt.get("response_sha256") != expected_hash:
        raise ValueError("receipt response artifact hash mismatch")
    status, code = receipt.get("status"), receipt.get("returncode")
    if status not in {"completed", "failed", "interrupted"} or (
        code is not None and type(code) is not int
    ):
        raise ValueError("invalid receipt terminal status/exit code")
    if type(receipt.get("provider_error")) is not bool or not re.fullmatch(
        r"[0-9a-f]{64}", receipt.get("stream_text_sha256", "")
    ):
        raise ValueError("receipt lacks typed provider outcome/stream fingerprint")
    if status != "completed" and not isinstance(receipt.get("error"), str):
        raise ValueError("failed/interrupted receipt lacks an error classification")
    if status == "completed" and (
        code != 0
        or receipt.get("provider_error") is not False
        or len(sessions) != 1
        or expected_hash is None
    ):
        raise ValueError("completed receipt lacks successful real-session evidence")
    if entry["status"] in {"passed", "rejected", "repair"} and status != "completed":
        raise ValueError("phase decision requires a completed model receipt")
    policy = receipt.get("access_policy", {})
    if receipt.get("read_scope_sha256"):
        scope_path = contained(root, attempt / "read-scope.json")
        if receipt["read_scope_sha256"] != artifact_hash(scope_path):
            raise ValueError("receipt exact read-scope hash mismatch")
        scope = json.loads(scope_path.read_text())
        if scope != {"role": MODEL_ROLES[phase], "policy": policy}:
            raise ValueError("receipt read scope differs from controller phase grant")
    elif entry.get("contract_sha256"):
        raise ValueError("current contract requires exact phase read-scope binding")
    if not isinstance(policy.get("read_paths"), list):
        raise TypeError("receipt lacks explicit read scope")
    for raw_path in policy["read_paths"]:
        path = contained(root, Path(raw_path))
        relative = path.relative_to(root).parts
        candidate_id = attempt.relative_to(root).parts[1]
        if relative and relative[0] == "attempts" and relative[1] != candidate_id:
            raise ValueError("phase read scope crosses candidate boundary")
        if phase == "oracle" and not (
            path == attempt.parent / "task/instruction.md"
            or path == attempt.parent / "task/environment/materials"
        ):
            raise ValueError("oracle may read only its own public task contract and materials")
        if phase == "materials" and not (
            len(relative) == 4 and relative[2].startswith("proposal-")
            and relative[3] in {"sources", "response.json"}
        ):
            raise ValueError("materials phase may read only its candidate proposal and sources")
        if not relative or (
            relative[0] != "imported"
            and (
                len(relative) < 4
                or relative[0] != "attempts"
                or not re.fullmatch(r"candidate-[0-9]{4,}", relative[1])
            )
        ):
            raise ValueError("receipt grants overbroad workspace reads")
    if policy.get("network_tools") is not False and (
        phase != "proposal"
        or policy.get("network_tools") is not True
        or policy.get("read_paths") != []
    ):
        raise ValueError("receipt violates private-material network policy")
    return receipt


def terminal_integrity(root, state):
    failures, legacy = [], []
    session_owners = {}
    for candidate in state["candidates"]:
        entries = list(candidate["stages"].items()) + [
            (e["phase"], e) for e in candidate.get("history", [])
        ]
        for phase, entry in entries:
            if entry["status"] == "running":
                continue
            label = {"candidate": candidate["id"], "phase": phase, "path": entry["path"]}
            try:
                if entry.get("output_sha256") and entry["output_sha256"] != artifact_hash(
                    Path(entry["path"])
                ):
                    raise ValueError("terminal output hash mismatch")
                receipt_path = contained(root, Path(entry["path"]) / "receipt.json")
                receipt_version = (
                    json.loads(receipt_path.read_text()).get("schema_version")
                    if receipt_path.is_file()
                    else None
                )
                if entry.get("evidence_version") != 2 and receipt_version != 2:
                    legacy.append(
                        {
                            **label,
                            "reason": "legacy evidence retained; never upgraded to acceptance",
                        }
                    )
                    continue
                if entry.get("output_sha256") != artifact_hash(Path(entry["path"])):
                    raise ValueError("terminal output hash missing or mismatched")
                if phase in MODEL_ROLES:
                    attempt = Path(entry["path"])
                    if (
                        entry["status"] in {"blocked", "interrupted", "failed"}
                        and not receipt_path.exists()
                        and not (attempt / "request.txt").exists()
                        and not (attempt / "response.json").exists()
                    ):
                        # Preparation can fail before call() creates any model artifacts.
                        # This preserves failed evidence for retry, never a gate decision.
                        continue
                    receipt = model_receipt(root, state["request"], phase, entry)
                    for session in receipt["sessions"]:
                        if session in session_owners and session_owners[session] != entry["path"]:
                            raise ValueError("independent attempts reused an OpenCode session")
                        session_owners[session] = entry["path"]
                if phase == "convert":
                    receipt = oracle_receipt(root, state["request"], entry)
                    for session in receipt.get("sessions", []):
                        owner = entry.get("oracle_reuse", str(Path(entry["path"]) / "oracle"))
                        if session in session_owners and session_owners[session] != owner:
                            raise ValueError("oracle reused another model/review session")
                        session_owners[session] = owner
            except (ValueError, OSError, KeyError, TypeError) as error:
                failures.append({**label, "reason": str(error)})
    return failures, legacy


def oracle_receipt(root, request, entry):
    attempt = contained(root, Path(entry.get("oracle_reuse", str(Path(entry["path"]) / "oracle"))))
    if entry.get("oracle_reuse") and (attempt.name != "oracle" or attempt.parent.parent != Path(entry["path"]).parent):
        raise ValueError("oracle reuse must reference the same candidate's preserved conversion")
    if not (attempt / "receipt.json").is_file():
        if entry["status"] == "passed" and (Path(entry["path"]) / "task/tests/private/ground_truth/manifest.json").is_file():
            raise ValueError("synthetic oracle has no model receipt")
        return {}
    if entry.get("contract_sha256") and entry["status"] == "passed":
        conversion = Path(entry["path"])
        binding = json.loads((attempt / "input.json").read_text())
        checks = json.loads((conversion / "checks.json").read_text())
        if (binding.get("instruction_sha256") != artifact_hash(conversion / "task/instruction.md")
                or binding.get("public_materials_sha256") != artifact_hash(conversion / "task/environment/materials")
                or binding.get("model") != request["model"]
                or checks.get("oracle_response_sha256") != artifact_hash(attempt / "response.json")
                or checks.get("oracle_receipt_sha256") != artifact_hash(attempt / "receipt.json")):
            raise ValueError("oracle response/receipt is not bound to this conversion's public inputs")
    return model_receipt(root, request, "oracle", {
        **entry, "path": str(attempt), "output_sha256": artifact_hash(attempt),
    })


def contained(root: Path, path: Path) -> Path:
    root, path = root.absolute(), path.absolute()
    if not path.is_relative_to(root) or ".." in path.parts:
        raise ValueError("evidence path escapes workspace")
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError("symlink in evidence path")
    return path


def located_quote(path, locator, quote):
    locator = Locator.model_validate(locator)
    if locator.kind == "asset":
        with path.open("rb") as stream:
            magic = stream.read(12)
        if not (
            magic.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8", b"GIF8", b"%PDF-"))
            or (magic.startswith(b"RIFF") and magic[8:12] == b"WEBP")
        ):
            raise ValueError("asset anchor does not reference a supported real image/PDF")
        return
    text = path.read_text(encoding="utf-8")
    if locator.kind == "page":
        pdf = path.with_suffix(".pdf")
        if path.suffix != ".txt" or not pdf.is_file() or pdf.is_symlink() or "\f" not in text:
            raise ValueError("page locator requires PDF-extracted text with page boundaries")
        with pdf.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise ValueError("page locator has no corresponding original PDF")
        units = text.split("\f")
        if not units[-1].strip():
            units.pop()
    else:
        units = text.split("\n")
    end = locator.end or locator.start
    if end > len(units):
        raise ValueError("evidence locator is out of bounds")
    selected = "\n".join(units[locator.start - 1 : end])
    if not quote.strip() or " ".join(quote.split()) not in " ".join(selected.split()):
        raise ValueError("evidence quote does not occur at its declared locator")


def bind_quote(path, quote):
    text = path.read_text(encoding="utf-8")
    words = list(re.finditer(r"\S+", text))
    normalized = " ".join(word.group() for word in words)
    excerpt = " ".join(quote.split())
    start = normalized.find(excerpt)
    if start < 0:
        raise ValueError("source metadata does not contain the claimed binding excerpt")
    if normalized.find(excerpt, start + 1) >= 0:
        raise ValueError(
            "ambiguous source excerpt; select a catalog ID or provide a longer unique quote"
        )
    offset, first, last = 0, None, None
    for word in words:
        if offset + len(word.group()) > start and first is None:
            first = word.start()
        if offset < start + len(excerpt):
            last = word.end()
        offset += len(word.group()) + 1
    locator = Locator(
        kind="lines", start=text.count("\n", 0, first) + 1, end=text.count("\n", 0, last) + 1
    )
    located_quote(path, locator, quote)
    return {
        "path": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "locator": locator.model_dump(),
        "quote": quote,
    }


def load_state(root, order):
    contained(root, root / "events.jsonl")
    contained(root, root / ".lock")
    path = contained(root, root / "run.json")
    state = json.loads(path.read_text())
    if state.get("schema_version") != 1 or not isinstance(state.get("candidates"), list):
        raise ValueError("unknown checkpoint schema")
    request = state["request"]
    if type(request.get("count")) is not int or request["count"] < 1:
        raise ValueError("invalid checkpoint target count")
    scope_counts = {request["count"]}
    previous_count = None
    for extension in state.get("scope_history", []):
        before, after = extension["previous_count"], extension["count"]
        if (type(before) is not int or type(after) is not int or before < 1 or after <= before
                or (previous_count is not None and before != previous_count)
                or extension.get("authority") != "explicit resume --count"):
            raise ValueError("invalid target scope extension history")
        scope_counts.update((before, after))
        previous_count = after
    if previous_count is not None and previous_count != request["count"]:
        raise ValueError("target does not match explicit scope history")
    if request.get("imported") != str(root / "imported"):
        raise ValueError("checkpoint imported path does not match workspace")
    contained(root, root / "imported")
    ids = set()
    for candidate in state["candidates"]:
        scope_count = candidate.get("scope_count", request["count"])
        if type(scope_count) is not int or scope_count not in scope_counts:
            raise ValueError("candidate scope does not match the recorded targets")
        cid = candidate["id"]
        if not re.fullmatch(r"candidate-[0-9]{4,}", cid) or cid in ids:
            raise ValueError("invalid or duplicate checkpoint candidate id")
        ids.add(cid)
        entries = list(candidate["stages"].items())
        entries += [(item["phase"], item) for item in candidate.get("history", [])]
        for phase, entry in entries:
            if entry.get("contract_sha256") and (entry.get("scope_count") != scope_count or entry.get("selected_paper") != candidate.get("selected_paper")):
                raise ValueError("phase scope differs from locked candidate count/selection")
            if phase not in order or entry.get("status") not in {
                "running",
                "passed",
                "failed",
                "blocked",
                "interrupted",
                "repair",
                "rejected",
            }:
                raise ValueError("invalid checkpoint phase/status")
            attempt = contained(root, Path(entry["path"]))
            if attempt.parent != root / "attempts" / cid or not re.fullmatch(
                re.escape(phase) + r"-[0-9a-f]{32}", attempt.name
            ):
                raise ValueError("checkpoint path does not match expected attempt layout")
            for key in ("input_sha256", "output_sha256"):
                if key in entry and not re.fullmatch(r"[0-9a-f]{64}", entry[key]):
                    raise ValueError("invalid checkpoint fingerprint")
            if entry["status"] == "passed" and "output_sha256" not in entry:
                raise ValueError("passed checkpoint lacks output fingerprint")
            if recovery := entry.get("recovery_input"):
                recovered = contained(root, Path(recovery["path"]))
                if recovered.parent != root / "attempts" / cid or not re.fullmatch(
                    r"proposal-[0-9a-f]{32}", recovered.name
                ):
                    raise ValueError("recovery input is not a proposal in this candidate's history")
                if not any(
                    h["path"] == str(recovered)
                    and h.get("output_sha256") == recovery["sha256"]
                    and h["status"] == "passed"
                    for h in candidate.get("history", [])
                ):
                    raise ValueError("recovery input does not match preserved passed evidence")
    return state


def catalog_paths(root, paths, prefix="E"):
    catalog = {}
    seen = set()
    for base in paths:
        base = contained(root, base)
        for path in sorted(base.rglob("*")) if base.is_dir() else [base]:
            contained(root, path)
            if (
                path in seen
                or not path.is_file()
                or path.name
                in {
                    "request.txt",
                    "receipt.json",
                    "evidence-catalog.json",
                    "source-support.json",
                    "review-bindings.json",
                }
            ):
                continue
            seen.add(path)
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}:
                locator = {"kind": "asset", "start": 1, "end": 1}
                located_quote(path, locator, "")
                eid = f"{prefix}{len(catalog) + 1:05d}"
                catalog[eid] = {
                    "id": eid,
                    "path": path.relative_to(root).as_posix(),
                    "sha256": artifact_hash(path),
                    "locator": locator,
                    "quote": "",
                    "inspection": "Original visual asset; no inferred text transcription",
                }
                continue
            if (
                path.suffix not in {".txt", ".json", ".md", ".toml", ".py", ".sh", ".tex", ".bib"}
                and path.name != "Dockerfile"
            ):
                continue
            text = path.read_text(encoding="utf-8")
            words = list(re.finditer(r"\S+", text))
            newlines = [m.start() for m in re.finditer("\n", text)]
            sha = artifact_hash(path)
            # Exact windows, including long publisher HTML-text lines. Coordinates are controller-owned.
            for index in range(0, len(words), 100):
                start = words[index].start()
                end = words[min(index + 119, len(words) - 1)].end()
                quote = text[start:end]
                if len(quote) < 12:
                    continue
                locator = {
                    "kind": "lines",
                    "start": bisect_right(newlines, start) + 1,
                    "end": bisect_right(newlines, end - 1) + 1,
                }
                located_quote(path, locator, quote)
                eid = f"{prefix}{len(catalog) + 1:05d}"
                catalog[eid] = {
                    "id": eid,
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha,
                    "locator": locator,
                    "quote": quote,
                }
            if path.name == "provenance.json":
                records = json.loads(text)
                # Synthetic oracle provenance is an object, not publisher-binding records.
                if (
                    isinstance(records, dict)
                    and records.get("kind") == "synthetic_oracle_not_original_ground_truth"
                ):
                    continue
                for record in records:
                    for field in ("identity_binding", "license_binding"):
                        binding = record[field]
                        target = contained(root, path.parent / binding["path"])
                        if artifact_hash(target) != binding["sha256"]:
                            raise ValueError("publisher binding hash mismatch")
                        located_quote(target, binding["locator"], binding["quote"])
                        eid = f"{prefix}{len(catalog) + 1:05d}"
                        catalog[eid] = {
                            **binding,
                            "id": eid,
                            "path": target.relative_to(root).as_posix(),
                            "binding": field,
                            "source_id": record["source_id"],
                        }
    return catalog


def evidence_catalog(root, stages, phase, order):
    paths = [Path(stages[phase]["path"]) / "locked-contract.json"]
    for previous in order[: order.index(phase)]:
        if previous.startswith("gate"):
            continue
        attempt = Path(stages[previous]["path"])
        if previous == "convert":
            paths.extend(attempt / name for name in ("task", "determinism", "checks.json", "template-proof"))
        else:
            paths.append(attempt)
    return catalog_paths(root, paths)


def check_review(root, stages, phase, result, gates, order):
    if set(result.checked) != set(gates[phase]):
        raise ValueError("review must address exactly the required dimensions")
    catalog = evidence_catalog(root, stages, phase, order)
    saved = json.loads((Path(stages[phase]["path"]) / "evidence-catalog.json").read_text())
    if saved != catalog:
        raise ValueError("controller evidence catalog no longer matches phase inputs")
    resolved = {}
    for dimension, checked in result.checked.items():
        if checked.assessment.casefold().strip(". ") in {
            "accepted",
            "passed",
            "no issues",
            "not applicable",
        }:
            raise ValueError("placeholder review assessment")
        resolved[dimension] = []
        for eid in checked.evidence_ids:
            if eid not in catalog:
                raise ValueError(
                    f"unknown evidence ID {eid}; choose an ID from evidence-catalog.json"
                )
            evidence = catalog[eid]
            path = contained(root, root / evidence["path"])
            if artifact_hash(path) != evidence["sha256"]:
                raise ValueError("review evidence hash mismatch")
            located_quote(path, evidence["locator"], evidence["quote"])
            resolved[dimension].append(evidence)
        if (
            phase == "gate1"
            and dimension == "licenses"
            and not any(e["path"].endswith("/provenance.json") for e in resolved[dimension])
        ):
            raise ValueError("license review must cite source-bound provenance")
        required = CONVERSION_EVIDENCE
        if dimension == "locked_objective" and not any(
            e["path"] == (Path(stages[phase]["path"]) / "locked-contract.json").relative_to(root).as_posix()
            for e in resolved[dimension]
        ):
            raise ValueError("review must cite its actual locked contract, not a builder-narrowed objective")
        if (
            phase == "gate3"
            and dimension in required
            and not any(e["path"].endswith("/" + required[dimension]) for e in resolved[dimension])
        ):
            ids = [
                eid
                for eid, anchor in catalog.items()
                if anchor["path"].endswith("/" + required[dimension])
            ]
            raise ValueError(
                f"conversion review {dimension} must cite {required[dimension]}; select one of {ids}"
            )
    if phase == "gate1":
        sources = Path(stages["proposal"]["path"]) / "sources"
        for record in json.loads((sources / "provenance.json").read_text()):
            if result.decision == "accept" and not record.get("publisher_license_identified"):
                raise ValueError(
                    "license evidence missing: reviewer must reject or request source repair, not accept"
                )
            for dimension, field in (
                ("sources", "identity_binding"),
                ("licenses", "license_binding"),
            ):
                binding = record[field]
                relative = (sources / binding["path"]).relative_to(root).as_posix()
                if not any(
                    e["path"] == relative
                    and " ".join(binding["quote"].split()) in " ".join(e["quote"].split())
                    for e in resolved[dimension]
                ):
                    raise ValueError(f"gate1 must cite each actual source's {field}")
    ground_dimension = {"gate1": "original_availability", "gate2": "ground_truth_comparison",
                        "gate3": "ground_truth_packaging"}[phase]
    original = Path(stages["proposal"]["path"]) / "sources/ground_truth"
    from .ground_truth import validate as validate_ground_truth

    validate_ground_truth(original)
    for name in ("paper.pdf", "paper.txt", "manifest.json"):
        expected = (original / name).relative_to(root).as_posix()
        if not any(e["path"] == expected for e in resolved[ground_dimension]):
            raise ValueError(f"{ground_dimension} must cite actual original {expected}")
    if phase == "gate3":
        for suffix in ("solution/manuscript/main.tex", "solution/preview.pdf", "solution/validation.json"):
            if not any(e["path"].endswith("/task/" + suffix) for e in resolved["oracle"]):
                raise ValueError("oracle review must cite " + suffix)
    if result.decision == "accept":
        receipt = json.loads((Path(stages[phase]["path"]) / "receipt.json").read_text())
        completed_reads = {r["path"] for r in receipt.get("artifact_reads", []) if r.get("status") == "completed"}
        required_reads = [original / "paper.pdf", original / "paper.txt", Path(stages[phase]["path"]) / "locked-contract.json"]
        if phase == "gate3":
            required_reads.append(Path(stages["convert"]["path"]) / "task/solution/preview.pdf")
        if any(str(path) not in completed_reads for path in required_reads):
            raise ValueError("acceptance requires completed direct reads of original PDF/text and gate3 oracle preview, not catalog-only judgments")
    bindings_path = Path(stages[phase]["path"]) / "review-bindings.json"
    if bindings_path.is_file() and json.loads(bindings_path.read_text()) != resolved:
        raise ValueError("stored review bindings differ from controller resolution")
    return resolved
