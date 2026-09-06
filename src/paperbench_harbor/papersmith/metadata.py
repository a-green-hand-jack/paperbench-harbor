"""Extract observed publisher identity/license fields, never approve their meaning."""

import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

from .integrity import artifact_hash


class SourceMetadata(HTMLParser):
    def __init__(self, url):
        super().__init__()
        self.url, self.records, self.licenses = url, [], []
        self.assets = {}
        self._paragraph = None
        self._paragraph_line = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        asset_url = urljoin(self.url, attrs.get("src", attrs.get("href", "")))
        parsed_asset = urlsplit(asset_url)
        query = parse_qs(parsed_asset.query)
        doi = query.get("id", [""])[0]
        article = parse_qs(urlsplit(self.url).query).get("id", [""])[0]
        if (
            parsed_asset.hostname == urlsplit(self.url).hostname
            and parsed_asset.path.endswith("/article/figure/image")
            and re.fullmatch(r"10\.[0-9]{4,9}/[^\s]+\.[gt][0-9]{3}", doi)
            and doi.rsplit(".", 1)[0] == article
        ):
            size = query.get("size", [""])[0]
            rank = {"inline": 1, "medium": 2, "original": 3, "large": 4}.get(size, 0)
            if rank > self.assets.get(doi, {}).get("rank", -1):
                self.assets[doi] = {
                    "url": asset_url,
                    "doi": doi,
                    "rank": rank,
                    "kind": "table" if doi.rsplit(".", 1)[1].startswith("t") else "figure",
                    "raw_tag": self.get_starttag_text(),
                    "raw_line": self.getpos()[0],
                }
        if tag == "p":
            self._paragraph = []
            self._paragraph_line = self.getpos()[0]
        name = attrs.get("name", attrs.get("property", "")).lower()
        if (
            tag == "meta"
            and attrs.get("content")
            and name.startswith(("citation_", "dc.", "dc:", "dcterms.", "prism:", "og:"))
        ):
            self.records.append({"name": name, "value": attrs["content"]})
        rel = set(attrs.get("rel", "").split())
        if tag in {"a", "link"} and attrs.get("href"):
            url = urljoin(self.url, attrs["href"])
            if "canonical" in rel:
                self.records.append({"rel": "canonical", "url": url})
            parsed = urlsplit(url)
            recognized = parsed.hostname in {
                "creativecommons.org",
                "www.creativecommons.org",
            } and parsed.path.startswith(("/licenses/", "/publicdomain/"))
            if "license" in rel or recognized:
                self.licenses.append(
                    {
                        "url": url.replace("http://", "https://", 1),
                        "raw_tag": self.get_starttag_text(),
                        "raw_line": self.getpos()[0],
                    }
                )
                self.records.append({"rel": "license", "url": url})

    def handle_data(self, data):
        if self._paragraph is not None:
            self._paragraph.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self._paragraph is not None:
            statement = " ".join("".join(self._paragraph).split())
            lower = statement.casefold()
            name = (
                "Creative Commons Attribution"
                if "creative commons attribution" in lower
                else "Public Library of Science Open-Access License"
                if "public library of science open-access license" in lower
                else None
            )
            if (
                lower.startswith(("copyright:", "copyright ", "\u00a9"))
                and name
                and "unrestricted use" in lower
            ):
                self.licenses.append(
                    {
                        "name": name,
                        "version": "not_stated",
                        "publisher_statement": statement,
                        "raw_line_start": self._paragraph_line,
                        "raw_line_end": self.getpos()[0],
                    }
                )
            self._paragraph = None

    def structured(self, payload):
        self.records.append({"json": payload})
        primary = payload
        for key in ("message", "data", "attributes"):
            if isinstance(primary, dict) and isinstance(primary.get(key), dict):
                primary = primary[key]
        if not isinstance(primary, dict):
            return
        for key in ("DOI", "doi", "title", "name", "identifier", "url", "URL"):
            if key in primary:
                self.records.append(
                    {
                        "name": "citation_doi"
                        if key.lower() == "doi"
                        else "citation_title"
                        if key in {"title", "name"}
                        else key,
                        "value": primary[key],
                    }
                )
        licenses = primary.get("license", primary.get("licenses", []))
        for value in licenses if isinstance(licenses, list) else [licenses]:
            url = value.get("URL", value.get("url")) if isinstance(value, dict) else value
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                self.licenses.append(
                    {"url": url.replace("http://", "https://", 1), "json_license": value}
                )

    def bindings(self, destination, source_id, raw_path):
        path = destination / f"{source_id}-publisher.txt"
        identities = [
            r
            for r in self.records
            if r.get("name")
            in {
                "citation_title",
                "citation_doi",
                "dc.title",
                "dc:identifier",
                "dc.identifier",
                "citation_arxiv_id",
            }
            or r.get("rel") == "canonical"
        ]
        identity_line = "Observed publisher identity: " + json.dumps(identities, ensure_ascii=True)
        license_line = "Observed publisher license links: " + json.dumps(
            self.licenses, ensure_ascii=True
        )
        lines = [
            f"Publisher metadata URL: {self.url}",
            f"Original metadata SHA256: {artifact_hash(raw_path)}",
            identity_line,
            license_line,
            "Extraction is evidence, not approval. Reviewer must verify authority, license applicability and exclusions against the original source.",
        ]
        path.write_text("\n".join(lines) + "\n")

        def anchor(line, quote):
            return {
                "path": path.name,
                "sha256": artifact_hash(path),
                "locator": {"kind": "lines", "start": line, "end": line},
                "quote": quote,
            }

        return anchor(3, identity_line), anchor(4, license_line)
