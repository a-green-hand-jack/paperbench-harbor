#!/usr/bin/env python3
"""Independently verify a screened benchmark candidate without a model call.

This program checks the pinned GitHub source revision and repository license,
then downloads the exact public sample manifest the candidate named. It does
not promote code or edit a layout spec. A human must approve both the candidate
and a separately proposed layout with SHA-256-bound JSON before implementation
can land.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.onboarding.candidate import (
    BenchmarkCandidate,
    OnboardingError,
    parse_candidate,
    read_layout_approval,
)

USER_AGENT = "paperbench-harbor-benchmark-verify/1.0"
HTTP_TIMEOUT_SECONDS = 30


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.read()


def _github_slug(repository: str) -> str:
    parsed = urllib.parse.urlparse(repository)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise OnboardingError(
            "source_repository must be an HTTPS GitHub repository so the generic "
            "verifier can independently resolve its immutable revision and license"
        )
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise OnboardingError("source_repository must name exactly one GitHub owner/repository")
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


def _json_document(payload: bytes, *, source: str) -> object:
    try:
        return json.loads(payload)
    except json.JSONDecodeError as error:
        raise OnboardingError(f"{source} returned invalid JSON: {error}") from error


def _manifest_sample_count(payload: bytes, *, source: str) -> int:
    document = _json_document(payload, source=source)
    if isinstance(document, list):
        samples = document
    elif isinstance(document, dict):
        samples = document.get("samples", document.get("tasks"))
    else:
        samples = None
    if not isinstance(samples, list):
        raise OnboardingError(
            f"{source} must be a JSON sample list or an object with a samples/tasks list"
        )
    return len(samples)


def _license_spellings(record: object, *, source: str) -> set[str]:
    if not isinstance(record, dict):
        raise OnboardingError(f"{source} is not a JSON object")
    if record.get("private") is True:
        raise OnboardingError(f"{source} identifies a private source repository")
    license_record = record.get("license")
    if not isinstance(license_record, dict):
        raise OnboardingError(f"{source} has no declared repository license")
    return {
        str(license_record[key]).strip()
        for key in ("spdx_id", "name", "key")
        if isinstance(license_record.get(key), str) and license_record[key].strip()
    }


def verify(candidate: BenchmarkCandidate) -> dict[str, object]:
    """Re-derive source facts from public bytes, independent of the proposal."""

    slug = _github_slug(candidate.source_repository)
    try:
        repo = _json_document(
            _http_get(f"https://api.github.com/repos/{slug}"), source="GitHub repository API"
        )
        revisions = _json_document(
            _http_get(f"https://api.github.com/repos/{slug}/commits/{candidate.source_revision}"),
            source="GitHub commit API",
        )
        manifest_bytes = _http_get(candidate.dataset_manifest_url)
    except urllib.error.HTTPError as error:
        raise OnboardingError(f"public verification request failed: HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise OnboardingError(f"public verification request failed: {error.reason}") from error

    if candidate.source_license not in _license_spellings(repo, source="GitHub repository API"):
        raise OnboardingError(
            f"source_license claims {candidate.source_license!r}, which disagrees with GitHub"
        )
    if not isinstance(revisions, dict) or revisions.get("sha") != candidate.source_revision:
        raise OnboardingError("GitHub did not resolve source_revision to the exact pinned commit")
    actual_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_digest != candidate.dataset_manifest_sha256:
        raise OnboardingError(
            "dataset manifest bytes do not match dataset_manifest_sha256 "
            f"(got {actual_digest})"
        )
    actual_count = _manifest_sample_count(manifest_bytes, source=candidate.dataset_manifest_url)
    if actual_count != candidate.sample_count:
        raise OnboardingError(
            f"sample_count claims {candidate.sample_count}, manifest contains {actual_count}"
        )
    return {
        "benchmark_id": candidate.benchmark_id,
        "source_repository": candidate.source_repository,
        "source_revision": candidate.source_revision,
        "source_license": candidate.source_license,
        "dataset_manifest_sha256": actual_digest,
        "sample_count": actual_count,
        "evaluator": candidate.evaluator,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--layout-spec", type=Path, default=None)
    parser.add_argument("--human-approval", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if (args.layout_spec is None) != (args.human_approval is None):
        parser.error("--layout-spec and --human-approval must be supplied together")

    try:
        candidate = parse_candidate(args.candidate)
        report = verify(candidate)
        if args.layout_spec is not None:
            approval = read_layout_approval(
                args.human_approval,
                candidate_path=args.candidate,
                layout_spec_path=args.layout_spec,
            )
            report["layout_approval"] = {
                "reviewer": approval.reviewer,
                "candidate_sha256": approval.candidate_sha256,
                "layout_spec_sha256": approval.layout_spec_sha256,
            }
    except OnboardingError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.layout_spec is None:
        print("Candidate is independently verified but still awaits human layout approval.")
    else:
        print("Candidate and exact layout proposal are independently verified and human-approved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
