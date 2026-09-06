"""Paper-level identity from captured primary metadata, not proposal labels."""

import json
import re
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit


def identifier(value):
    value = value.strip().lower()
    parsed = urlsplit(value)
    if parsed.hostname in {
        "doi.org",
        "dx.doi.org",
        "arxiv.org",
        "www.arxiv.org",
        "export.arxiv.org",
    }:
        value = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    value = unquote(value)
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)
    if value.startswith("10.48550/arxiv."):
        value = "arxiv:" + value[len("10.48550/arxiv.") :]
    if re.fullmatch(r"10\.[0-9]{4,9}/[^\s?#]+", value):
        return "doi:" + value
    value = re.sub(r"^(?:https?://(?:www\.|export\.)?arxiv\.org/(?:abs|pdf)/|arxiv:\s*)", "", value)
    value = re.sub(r"\.pdf$", "", value)
    if re.fullmatch(
        r"(?:[0-9]{4}\.[0-9]{4,5}|[a-z-]+(?:\.[a-z-]+)?/[0-9]{7})(?:v[1-9][0-9]*)?", value
    ):
        return "arxiv:" + re.sub(r"v[0-9]+$", "", value)
    return None


def selection_identifier(value):
    stable = identifier(value)
    if stable:
        return stable
    parsed = urlsplit(value.removeprefix("canonical-url:"))
    if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
        return "canonical-url:" + urlunsplit(("https", parsed.netloc.lower(), parsed.path.rstrip("/") or "/", parsed.query, ""))
    raise ValueError("fixed papers require DOI, arXiv or credential-free canonical HTTPS URLs")


def canonical_identity(sources):
    aliases, observed, versions = set(), [], []
    records = json.loads((sources / "provenance.json").read_text())
    for record in records:
        if record["source"]["role"] != "paper":
            continue
        source, metadata = record["source"], record["metadata"]
        aliases.add("source-sha256:" + source["sha256"])
        versions.append(
            {
                "source_sha256": source["sha256"],
                "metadata_sha256": metadata["sha256"],
                "resolved_url": source["resolved_url"],
            }
        )
        values = [(source["resolved_url"], False), (metadata["resolved_url"], False)]
        # Only captured primary metadata, not a proposal URL or an arbitrary fetched page,
        # establishes landing-page aliases. A separate source must have a matching identity
        # or an observed primary-PDF acquisition relationship before its URLs become aliases.
        primary_fields = {"citation_doi", "citation_arxiv_id", "dc.identifier", "dc:identifier",
                          "dcterms.identifier", "prism:doi"}
        primary_ids = {identifier(item["value"]) for item in metadata["canonical_metadata"]
                       if item.get("name") in primary_fields and isinstance(item.get("value"), str)} - {None}
        has_title = any(item.get("name") in {"citation_title", "dc.title"} and item.get("value")
                        for item in metadata["canonical_metadata"])
        if has_title and record.get("identity_binding") and metadata.get("acquisition", "https") == "https":
            landing_urls = {metadata["url"], metadata["resolved_url"]}
            values.extend((url, True) for url in landing_urls)
            pdf_urls = {urljoin(metadata["resolved_url"], item["value"])
                        for item in metadata["canonical_metadata"]
                        if item.get("name") == "citation_pdf_url" and isinstance(item.get("value"), str)}
            source_ids = {identifier(item["value"]) for item in source.get("canonical_metadata", [])
                          if item.get("name") in primary_fields and isinstance(item.get("value"), str)} - {None}
            if source.get("acquisition") == "https" and (source["sha256"] == metadata["sha256"]
                    or source["resolved_url"] in landing_urls | pdf_urls
                    or primary_ids.intersection(source_ids)):
                values.extend((source[key], True) for key in ("url", "resolved_url"))
        for item in metadata["canonical_metadata"]:
            if item.get("name") in {
                "citation_doi",
                "dc.identifier",
                "dc:identifier",
                "dcterms.identifier",
                "prism:doi",
                "citation_arxiv_id",
                "citation_pdf_url",
                "og:url",
            }:
                values.append(
                    (
                        item["value"],
                        item["name"]
                        in {
                            "og:url",
                            "dc.identifier",
                            "dc:identifier",
                            "dcterms.identifier",
                            "citation_pdf_url",
                        },
                    )
                )
            if "canonical" in item.get("rel", "").split():
                values.append((item["url"], True))
            if isinstance(item.get("json"), dict):
                primary = item["json"]
                # Unwrap known primary API envelopes, never reference lists/related works.
                for key in ("message", "data", "attributes"):
                    if isinstance(primary.get(key), dict):
                        primary = primary[key]
                for key in ("DOI", "doi", "arxiv_id", "identifier", "id", "@id", "url", "URL"):
                    if isinstance(primary.get(key), str):
                        values.append((primary[key], key in {"url", "URL", "@id"}))
        for value, canonical in values:
            stable = identifier(value)
            if stable:
                aliases.add(stable)
                observed.append(value)
            if canonical:
                parsed = urlsplit(value)
                if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
                    normalized = urlunsplit(
                        (
                            "https",
                            parsed.netloc.lower(),
                            parsed.path.rstrip("/") or "/",
                            parsed.query,
                            "",
                        )
                    )
                    aliases.add("canonical-url:" + normalized)
                    observed.append(value)
    primary = sorted(a for a in aliases if a.startswith(("doi:", "arxiv:")))
    canonical = sorted(a for a in aliases if a.startswith("canonical-url:"))
    if not primary and not canonical:
        raise ValueError(
            "retrieved primary metadata lacks a DOI, arXiv identity or canonical source URL"
        )
    return {
        "schema_version": 1,
        "identity": primary[0] if primary else canonical[0] + "@" + versions[0]["source_sha256"],
        "aliases": sorted(aliases),
        "observed_identifiers": sorted(set(observed)),
        "snapshots": versions,
    }
