"""Acquire original artifacts, never manufacture ground truth from model prose."""

import gzip
import io
import json
import re
import shutil
import tarfile
import time
import unicodedata
import zipfile
from email.message import Message
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlsplit

from paperbench_harbor.construction.core.state import atomic_json

from .identity import identifier
from .integrity import artifact_hash, contained
from .network import retrieve
from .operations import run


def acquire(sources, proposal, cache=None):
    root = sources / "ground_truth"
    root.mkdir()
    provenance = json.loads((sources / "provenance.json").read_text())
    identity = json.loads((sources / "identity.json").read_text())
    papers = [r for r in provenance if r["source"]["role"] == "paper"]
    if len(papers) != 1:
        raise ValueError("one focal original paper is required per task")
    paper = papers[0]
    metadata = paper["metadata"]
    records = metadata["canonical_metadata"]
    title = next(
        (r["value"] for r in records if r.get("name") in {"citation_title", "dc.title"}), None
    )
    if isinstance(title, list):
        title = " ".join(title)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("original PDF requires an observed publisher title")
    old = cache / "ground_truth" if cache else None
    old_manifest = (
        json.loads((old / "manifest.json").read_text())
        if old and (old / "manifest.json").is_file()
        else {}
    )
    acquisitions = []
    reused = []

    def download(url, name, authoritative_pdf=False):
        cached = next((r for r in old_manifest.get("acquisitions", []) if r["url"] == url), None)
        if cached and authoritative_pdf:
            binding = old_manifest.get("pdf", {}).get("authority", {})
            if (
                binding.get("url") != url
                or binding.get("sha256") != cached["sha256"]
                or binding.get("metadata_sha256") != metadata["sha256"]
                or binding.get("relationship") not in {"citation_pdf_url", "arxiv_abs_to_pdf"}
            ):
                cached = None
        if cached:
            path = contained(old, old / cached["path"])
            if artifact_hash(path) != cached["sha256"]:
                raise ValueError("original artifact cache hash mismatch")
            data = path.read_bytes()
            reused.append({"path": str(path), "sha256": cached["sha256"]})
            record = {**cached, "path": name}
        else:
            data, media, final, headers = retrieve(url)
            record = {
                "url": url,
                "resolved_url": final,
                "media_type": media,
                "response_headers": headers,
                "retrieved_at": time.time(),
                "path": name,
            }
        (root / name).write_bytes(data)
        record["sha256"] = artifact_hash(root / name)
        acquisitions[:] = [r for r in acquisitions if r["path"] != name]
        acquisitions.append(record)
        return data

    # Acquisition authority comes from observed metadata, never a proposed PDF's title/DOI.
    urls = [
        urljoin(metadata["resolved_url"], r["value"])
        for r in records
        if r.get("name") == "citation_pdf_url" and isinstance(r.get("value"), str)
    ]
    source = paper["source"]
    relationship = "citation_pdf_url"
    if not urls:
        observed = urlsplit(metadata["resolved_url"])
        if (
            observed.hostname in {"arxiv.org", "www.arxiv.org"}
            and observed.path.startswith("/abs/")
            and identifier(metadata["resolved_url"]) in identity["aliases"]
        ):
            urls = ["https://arxiv.org/pdf/" + observed.path[len("/abs/") :]]
            relationship = "arxiv_abs_to_pdf"
    if not urls:
        raise ValueError(
            "mandatory PDF lacks an observed publisher/repository PDF relationship; a supplied PDF plus title/DOI is not authority"
        )
    failures = []
    for url in dict.fromkeys(urls):
        try:
            data = download(url, "paper.pdf", authoritative_pdf=True)
            if not data.startswith(b"%PDF-"):
                raise ValueError("authoritative PDF endpoint did not return PDF bytes")
            authority = {
                "relationship": relationship,
                "url": url,
                "metadata_url": metadata["resolved_url"],
                "metadata_sha256": metadata["sha256"],
                "sha256": artifact_hash(root / "paper.pdf"),
            }
            break
        except ValueError as error:
            failures.append({"url": url, "error": str(error)})
    else:
        raise ValueError("mandatory publisher paper.pdf unavailable: " + json.dumps(failures))
    pdf = root / "paper.pdf"
    info = run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=False)
    pages = re.search(r"^Pages:\s+(\d+)", info.stdout, re.MULTILINE)
    if info.returncode or not pages or int(pages[1]) < 1:
        raise ValueError("publisher PDF is invalid or has no pages")
    extracted = run(
        ["pdftotext", "-layout", str(pdf), str(root / "paper.txt")],
        capture_output=True,
        check=False,
    )
    if extracted.returncode:
        raise ValueError("publisher PDF text extraction failed")
    text = (root / "paper.txt").read_text()
    normalized = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    normalized = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", normalized)
    words = re.findall(r"\w+", normalized.casefold())
    title_words = re.findall(r"\w+", unicodedata.normalize("NFKC", title).casefold())
    first = re.findall(r"\w+", normalized.split("\f")[0].casefold())
    title_match = " ".join(title_words) in " ".join(first)
    stable_ids = [
        a.split(":", 1)[1] for a in identity["aliases"] if a.startswith(("doi:", "arxiv:"))
    ]
    id_match = any(value in re.sub(r"\s+", "", text[:20000].casefold()) for value in stable_ids)
    if len(words) < 200 or not title_match or (stable_ids and not id_match):
        raise ValueError("original PDF is unreadable or fails focal title/DOI identity check")
    # Preserve the actual publisher snapshot in addition to its extracted evidence.
    if "html" in metadata["media_type"]:
        shutil.copyfile(sources / (metadata["id"] + ".bin"), root / "paper.html")
    search = [
        {
            "url": metadata["resolved_url"],
            "sha256": metadata["sha256"],
            "method": "publisher original-source link extraction",
            "links": paper.get("original_source_links", []),
            "candidates": paper.get("original_source_candidates", []),
            "scope": "Marked links in this fetched metadata snapshot only; no crawl or exhaustive absence claim",
        }
    ]
    requested = next(s for s in proposal.sources if s.id == source["id"])
    source_urls = list(
        dict.fromkeys([*paper.get("original_source_links", []), *requested.original_source_urls])
    )
    for alias in identity["aliases"]:
        if alias.startswith("arxiv:"):
            source_urls.append("https://arxiv.org/e-print/" + alias.split(":", 1)[1])
    available = []
    for index, url in enumerate(dict.fromkeys(source_urls)):
        entry = {
            "url": url,
            "method": "retrieve original TeX and bundled dependencies",
            "status": "unavailable",
        }
        search.append(entry)
        try:
            data = download(url, f"original-source-{index}.bin")
            response = acquisitions[-1]
            disposition = Message()
            disposition["Content-Disposition"] = response.get("response_headers", {}).get(
                "Content-Disposition", ""
            )
            entry.update(
                response={
                    **{
                        key: response.get(key)
                        for key in ("media_type", "response_headers", "resolved_url", "sha256")
                    },
                    "declared_filename": disposition.get_filename(),
                },
            )
            if (
                response["media_type"] in {"text/html", "application/xhtml+xml", "application/pdf"}
                or response["media_type"].startswith("image/")
                or data.lstrip().lower().startswith((b"<!doctype html", b"<html", b"%pdf-"))
            ):
                entry["status"] = "not_original_tex"
                raise ValueError(
                    "marked source endpoint returned HTML/PDF/image rather than original TeX/archive; not followed"
                )
            if data.startswith(b"\x1f\x8b"):
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                    data = compressed.read(256 * 1024 * 1024 + 1)
                if len(data) > 256 * 1024 * 1024:
                    raise ValueError("original gzip exceeds extraction budget")
            files = {}
            stream = io.BytesIO(data)
            if zipfile.is_zipfile(stream):
                with zipfile.ZipFile(stream) as archive:
                    for member in archive.infolist():
                        if member.is_dir():
                            continue
                        if (member.external_attr >> 16) & 0o170000 == 0o120000:
                            raise ValueError("original archive contains symlinks")
                        if (
                            len(files) >= 5000
                            or member.file_size > 64 * 1024 * 1024
                            or sum(map(len, files.values())) + member.file_size > 256 * 1024 * 1024
                        ):
                            raise ValueError("original archive exceeds extraction budget")
                        files[member.filename] = archive.read(member)
            else:
                stream.seek(0)
                try:
                    with tarfile.open(fileobj=stream, mode="r:*") as archive:
                        for member in archive:
                            if member.isdir():
                                continue
                            if not member.isfile():
                                raise ValueError("original archive contains nonregular entries")
                            if (
                                len(files) >= 5000
                                or member.size > 64 * 1024 * 1024
                                or sum(map(len, files.values())) + member.size > 256 * 1024 * 1024
                            ):
                                raise ValueError("original archive exceeds extraction budget")
                            files[member.name] = archive.extractfile(member).read()
                except tarfile.ReadError:
                    if (
                        data.lstrip().startswith((b"%", b"\\"))
                        and b"\\documentclass" in data
                        and b"\\begin{document}" in data
                    ):
                        files["main.tex"] = data
                        pending = [("main.tex", url)]
                        dependency_search = []
                        seen = set()
                        while pending:
                            name, parent_url = pending.pop()
                            content = files[name].decode("utf-8", errors="replace")
                            for command, names in re.findall(
                                r"\\(input|include|bibliography|includegraphics|documentclass|usepackage)(?:\[[^]]*\])?\{([^}]+)\}",
                                content,
                            ):
                                for dependency in names.split(","):
                                    dependency = dependency.strip()
                                    if not re.fullmatch(r"[A-Za-z0-9_./-]+", dependency):
                                        raise ValueError(
                                            "original TeX dependency is not a safe literal path"
                                        )
                                    extension = {
                                        "input": ".tex",
                                        "include": ".tex",
                                        "bibliography": ".bib",
                                        "documentclass": ".cls",
                                        "usepackage": ".sty",
                                    }.get(command)
                                    candidates = (
                                        [dependency]
                                        if PurePosixPath(dependency).suffix
                                        else [
                                            dependency + ext
                                            for ext in (
                                                [extension]
                                                if extension
                                                else [".pdf", ".png", ".jpg", ".jpeg"]
                                            )
                                        ]
                                    )
                                    for candidate in candidates:
                                        relative = (
                                            PurePosixPath(name).parent / candidate
                                        ).as_posix()
                                        contained(root, root / relative)
                                        if relative in files or relative in seen:
                                            break
                                        seen.add(relative)
                                        if len(seen) > 500:
                                            raise ValueError(
                                                "original TeX dependency search exceeds budget"
                                            )
                                        dependency_url = urljoin(parent_url, candidate)
                                        observation = {
                                            "url": dependency_url,
                                            "dependency": relative,
                                        }
                                        dependency_search.append(observation)
                                        try:
                                            payload = download(
                                                dependency_url,
                                                f"dependency-{index}-{len(seen)}.bin",
                                            )
                                            if (
                                                payload.lstrip()
                                                .lower()
                                                .startswith((b"<!doctype html", b"<html"))
                                            ):
                                                raise ValueError(
                                                    "dependency endpoint returned HTML"
                                                )
                                            if (
                                                sum(map(len, files.values())) + len(payload)
                                                > 256 * 1024 * 1024
                                            ):
                                                raise ValueError(
                                                    "original dependencies exceed extraction budget"
                                                )
                                            files[relative] = payload
                                            observation["status"] = "retrieved"
                                            if relative.endswith((".tex", ".sty", ".cls")):
                                                pending.append((relative, dependency_url))
                                            break
                                        except ValueError as error:
                                            observation.update(
                                                status="unavailable", error=str(error)
                                            )
                        entry["dependency_search"] = dependency_search
                    else:
                        entry["status"] = "not_original_tex"
                        raise ValueError("endpoint is not an original TeX file/archive") from None
            if len(files) > 5000 or not any(name.endswith(".tex") for name in files):
                if not any(name.endswith(".tex") for name in files):
                    entry["status"] = "not_original_tex"
                raise ValueError("original source archive has no TeX or too many files")
            target = root / "original_tex" / str(index)
            for name in files:
                contained(target, target / name)
            for name, payload in files.items():
                path = contained(target, target / name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            entry.update(
                status="retrieved",
                path=target.relative_to(root).as_posix(),
                sha256=artifact_hash(target),
                files=len(files),
                completeness="independent gate1 must verify original identity and dependencies",
            )
            available.append(entry["path"])
        except (ValueError, OSError, RuntimeError, EOFError, zipfile.BadZipFile) as error:
            entry["error"] = str(error)
    atomic_json(
        root / "manifest.json",
        {
            "schema_version": 1,
            "kind": "acquired_original_ground_truth",
            "identity": identity,
            "title": title,
            "version": "sha256:" + artifact_hash(pdf),
            "publisher_metadata_sha256": metadata["sha256"],
            "license_binding": paper["license_binding"],
            "license_document": paper["license_document"],
            "license_approval": "requires_independent_gate1",
            "acquisitions": acquisitions,
            "pdf_retrieval_failures": failures,
            "pdf": {
                "path": "paper.pdf",
                "sha256": artifact_hash(pdf),
                "authority": authority,
                "pages": int(pages[1]),
                "text_sha256": artifact_hash(root / "paper.txt"),
                "words": len(words),
                "title_on_first_page": title_match,
                "identifier_in_text": id_match,
                "validity": "pdfinfo_and_pdftotext",
                "readability": "extractable_text; reviewer checks visual pages",
            },
            "original_tex": {
                "status": "retrieved_requires_review"
                if available
                else "unavailable_in_inspected_candidates"
                if source_urls
                else "not_discovered",
                "paths": available,
                "search_evidence": search,
                "rights_basis": "Not inferred from article license; gate1 must establish original bundle rights and applicability from the captured publisher/repository evidence.",
                "reason": "Only retrieved originals are retained. Not discovered means no candidate was identified in the recorded search; unavailable refers only to inspected candidates, not exhaustive absence. No inferred or model-recreated TeX is original source.",
            },
            "files": {
                p.relative_to(root).as_posix(): artifact_hash(p)
                for p in sorted(root.rglob("*"))
                if p.is_file()
            },
        },
    )
    validate(root)
    return reused


def validate(root):
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("kind") != "acquired_original_ground_truth":
        raise ValueError("missing acquired original ground truth")
    if not manifest["pdf"]["pages"] or not manifest["pdf"]["title_on_first_page"]:
        raise ValueError("missing original PDF validation")
    for name, sha in manifest["files"].items():
        if artifact_hash(contained(root, root / name)) != sha:
            raise ValueError("ground truth artifact changed: " + name)
    if artifact_hash(root / "paper.pdf") != manifest["pdf"]["sha256"]:
        raise ValueError("mandatory original paper.pdf missing or changed")
    authority = manifest["pdf"].get("authority", {})
    if (
        authority.get("relationship") not in {"citation_pdf_url", "arxiv_abs_to_pdf"}
        or authority.get("metadata_sha256") != manifest["publisher_metadata_sha256"]
        or authority.get("sha256") != manifest["pdf"]["sha256"]
        or not any(
            r["path"] == "paper.pdf"
            and r["url"] == authority.get("url")
            and r["sha256"] == authority.get("sha256")
            for r in manifest["acquisitions"]
        )
    ):
        raise ValueError("original PDF lacks a hash-bound authoritative acquisition relationship")
    if not manifest["original_tex"]["search_evidence"]:
        raise ValueError("original TeX availability lacks search evidence")
    return manifest
