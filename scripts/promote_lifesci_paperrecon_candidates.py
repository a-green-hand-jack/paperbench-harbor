#!/usr/bin/env python3
"""Promote screened candidates, after re-deriving every claim from live sources.

    promote_lifesci_paperrecon_candidates.py --candidates <dir>/candidates.json
    promote_lifesci_paperrecon_candidates.py --candidates ... --promote --limit 10

Stage 1 writes `candidates.json` using an agent that was *told* to verify each
field against the live arXiv page and the GitHub API. This script assumes it did
not. For every candidate it fetches those same facts itself — there is no model
call anywhere in this file — and rejects any candidate whose claim disagrees with
what the live source returns.

That is deliberately stricter than "policy-compliant". A candidate can be
perfectly admissible under policy and still be wrong about itself, and the
failure mode this exists to catch is the one already observed twice in real
screening output: a primary category reported from the model's prior instead of
read off the API. Caught here it costs one HTTP request; missed here it costs a
full construction run, which fails late as a `provenance-mismatch`.

Promotion never edits `papers.py`. After independent verification, an explicit
human approval record binds selected candidate ids to the exact proposal bytes
before anything can be appended to
`approved_scaleup.jsonl` as `PaperSpec`-shaped records, one per line, deduplicated
on `arxiv_id`. Keeping the hand-curated tuple in `papers.py` a hand-edited Python
artifact, and this file data, is what stops an automated stage from redefining
what the construction gate treats as authoritative — see
`docs/papersmith-architecture.md` ("One-command entry point").

Requires unauthenticated network reads against arXiv and GitHub. No `opencode`,
no LLM, no API key; `$GITHUB_TOKEN` is used if set, only to raise GitHub's 60
requests/hour anonymous rate limit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from paperbench_harbor.construction.core.screen import (
    Candidate,
    ScreeningError,
    ScreeningPolicy,
    parse_candidates,
)
from paperbench_harbor.construction.core.spec import PaperSpec
from paperbench_harbor.construction.lifesci_paperrecon.papers import (
    APPROVED_PAPERS,
    APPROVED_SCALEUP_PATH,
)
from paperbench_harbor.construction.lifesci_paperrecon.screening import (
    LIFESCI_EXCLUDE_IDS,
    LIFESCI_SCREENING_POLICY,
)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_ABS_URL = "https://arxiv.org/abs"
GITHUB_API_URL = "https://api.github.com/repos"

#: arXiv rejects unidentified bulk clients, and being identifiable is the polite
#: side of the same bargain that gets us unauthenticated access at all.
USER_AGENT = "paperbench-harbor-promote/1.0 (+https://github.com/Jack-Jieke-Wu)"

HTTP_TIMEOUT_SECONDS = 30

ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"

#: The license lives in this block on the abstract *page*. It is not in the Atom
#: API at all (verified against the live API, 2026-08-31: an `id_list` response
#: carries `arxiv:primary_category` and the version, and the string "license"
#: appears nowhere in it), which is why this script reads two arXiv endpoints
#: rather than one.
ABS_LICENSE_PATTERN = re.compile(
    r'<div class="abs-license">.*?<a[^>]+href="([^"]+)"', re.DOTALL | re.IGNORECASE
)

#: `code_license` is recorded verbatim from GitHub's `license` object, but which
#: of its several spellings a screening agent copied is not a fact about the
#: paper. Treating `"MIT"`, `"MIT License"` and `"mit"` as disagreement would
#: reject candidates for being cosmetically inconsistent, which is the opposite
#: of the error this script is for.
NO_CODE_LICENSE = "none declared"


class PromotionError(RuntimeError):
    """The inputs cannot be read, so there is nothing to promote."""


@dataclass(frozen=True)
class LiveFacts:
    """What the live sources say, independently of what the candidate claimed."""

    primary_category: str
    license_name: str
    version: str
    code_license: str


@dataclass(frozen=True)
class Mismatch:
    """One claimed field the live source contradicts."""

    field: str
    claimed: str
    actual: str

    def describe(self) -> str:
        return f"{self.field}: claimed {self.claimed!r}, live source says {self.actual!r}"


@dataclass(frozen=True)
class Outcome:
    """One candidate's verdict. `status` is the only thing callers branch on."""

    candidate: Candidate
    status: str
    mismatches: tuple[Mismatch, ...] = ()
    live: LiveFacts | None = None
    reason: str = ""

    @property
    def eligible(self) -> bool:
        return self.status == "eligible"

    def describe(self) -> str:
        if self.mismatches:
            return "; ".join(mismatch.describe() for mismatch in self.mismatches)
        return self.reason


@dataclass(frozen=True)
class HumanApproval:
    """A reviewer attestation bound to one immutable candidate proposal."""

    candidate_sha256: str
    approved_arxiv_ids: frozenset[str]
    reviewer: str


def _candidate_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _default_human_approval_path(candidates: Path) -> Path:
    return candidates.with_name(f"{candidates.name}.human-approval.json")


def read_human_approval(
    path: Path, *, candidates_path: Path, candidates: list[Candidate]
) -> HumanApproval:
    """Read a human review record and bind it to the exact candidate file.

    The agent that screens and verifies candidates has no write permission, so
    this separate file is deliberately supplied by a human after reviewing the
    deterministic verification report.  A byte digest prevents approval of one
    proposal from being replayed against a later, edited proposal.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PromotionError(
            f"human approval is required for --promote: {path} does not exist"
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise PromotionError(f"cannot read human approval {path}: {error}") from error
    if not isinstance(payload, dict):
        raise PromotionError(f"human approval {path} must be a JSON object")
    if payload.get("schema_version") != 1:
        raise PromotionError(f"human approval {path} must set schema_version to 1")
    digest = payload.get("candidate_sha256")
    if not isinstance(digest, str) or digest != _candidate_sha256(candidates_path):
        raise PromotionError(
            f"human approval {path} does not match the exact candidate proposal"
        )
    reviewer = payload.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise PromotionError(f"human approval {path} must name a non-empty reviewer")
    approved = payload.get("approved_arxiv_ids")
    if not isinstance(approved, list) or any(
        not isinstance(arxiv_id, str) or not arxiv_id.strip() for arxiv_id in approved
    ):
        raise PromotionError(
            f"human approval {path} must contain approved_arxiv_ids as a string list"
        )
    approved_ids = frozenset(arxiv_id.strip() for arxiv_id in approved)
    candidate_ids = {candidate.arxiv_id for candidate in candidates}
    unknown_ids = sorted(approved_ids - candidate_ids)
    if unknown_ids:
        raise PromotionError(
            f"human approval {path} names candidate ids absent from the proposal: "
            + ", ".join(unknown_ids)
        )
    return HumanApproval(
        candidate_sha256=digest,
        approved_arxiv_ids=approved_ids,
        reviewer=reviewer.strip(),
    )


def _log(message: str) -> None:
    print(message, flush=True)


def _http_get(url: str, *, headers: dict[str, str] | None = None) -> str:
    """The single network seam in this script, so tests replace exactly one thing."""

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8", errors="replace")


def license_name_from_url(url: str) -> str:
    """Canonical license name from the URL the abstract page links to.

    Derived structurally rather than through a lookup table: arXiv links the
    canonical Creative Commons URL, whose path already encodes the code and the
    version (`/licenses/by-sa/4.0/` → `CC BY-SA 4.0`), so this spells every CC
    variant — including the 3.0-era ones on older submissions — the same way
    :data:`~...core.spec.ACCEPTED_LICENSES` does, with no table to keep in sync.
    """

    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]

    if "creativecommons.org" in host:
        if len(parts) >= 3 and parts[0] == "publicdomain" and parts[1] == "zero":
            return f"CC0 {parts[2]}"
        if len(parts) >= 3 and parts[0] == "licenses":
            return f"CC {parts[1].upper()} {parts[2]}"
    if "arxiv.org" in host:
        # The default terms. Permits arXiv to distribute, not us to redistribute
        # derived material, so it is never on the accepted list.
        return "arXiv perpetual non-exclusive license"
    return url


def _parse_arxiv_atom(payload: str, arxiv_id: str) -> tuple[str, str]:
    """`(primary_category, version)` from an `id_list` Atom response."""

    try:
        feed = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise PromotionError(
            f"{arxiv_id}: the arXiv API returned unparseable XML: {error}"
        ) from error

    entry = feed.find(f"{ATOM_NS}entry")
    if entry is None:
        raise PromotionError(f"{arxiv_id}: the arXiv API returned no entry for this id")

    primary = entry.find(f"{ARXIV_NS}primary_category")
    category = (primary.get("term") or "").strip() if primary is not None else ""
    if not category:
        raise PromotionError(f"{arxiv_id}: the arXiv API entry has no primary category")

    identifier = entry.find(f"{ATOM_NS}id")
    text = (identifier.text or "") if identifier is not None else ""
    match = re.search(r"(v\d+)\s*$", text.strip())
    version = match.group(1) if match else ""

    return category, version


def _parse_abs_license(payload: str, arxiv_id: str) -> str:
    match = ABS_LICENSE_PATTERN.search(payload)
    if not match:
        raise PromotionError(
            f"{arxiv_id}: no license block on the abstract page — "
            "the page layout may have changed, so nothing here is verified"
        )
    return license_name_from_url(match.group(1).strip())


def _repo_slug(code_repo: str, arxiv_id: str) -> str:
    parsed = urllib.parse.urlparse(code_repo.strip())
    if "github.com" not in parsed.netloc.lower():
        raise PromotionError(
            f"{arxiv_id}: {code_repo!r} is not a GitHub URL, so its license "
            "cannot be checked against the GitHub API"
        )
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise PromotionError(f"{arxiv_id}: {code_repo!r} names no owner/repo")
    owner, repo = parts[0], parts[1]
    return f"{owner}/{repo.removesuffix('.git')}"


def _parse_github_license(payload: str, arxiv_id: str) -> tuple[str, ...]:
    """Every acceptable spelling of the repo's license, or `("none declared",)`."""

    try:
        record = json.loads(payload)
    except json.JSONDecodeError as error:
        raise PromotionError(
            f"{arxiv_id}: the GitHub API returned unparseable JSON: {error}"
        ) from error
    if not isinstance(record, dict):
        raise PromotionError(f"{arxiv_id}: the GitHub API response is not a JSON object")

    license_record = record.get("license")
    if license_record is None:
        return (NO_CODE_LICENSE,)
    if not isinstance(license_record, dict):
        raise PromotionError(f"{arxiv_id}: the GitHub API 'license' field is not an object")

    spellings = tuple(
        str(license_record[key]).strip()
        for key in ("spdx_id", "name", "key")
        if isinstance(license_record.get(key), str) and license_record[key].strip()
    )
    if not spellings:
        raise PromotionError(f"{arxiv_id}: the GitHub API 'license' object names no license")
    return spellings


def fetch_live_facts(candidate: Candidate) -> tuple[LiveFacts, tuple[str, ...]]:
    """Everything this script checks a candidate against. Three requests, no model.

    Returns the facts plus the accepted spellings of the code license, which is
    the one field where several spellings are the same answer.
    """

    query = urllib.parse.urlencode({"id_list": candidate.arxiv_id, "max_results": 1})
    category, version = _parse_arxiv_atom(
        _http_get(f"{ARXIV_API_URL}?{query}"), candidate.arxiv_id
    )
    license_name = _parse_abs_license(
        _http_get(f"{ARXIV_ABS_URL}/{candidate.arxiv_id}"), candidate.arxiv_id
    )

    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    code_licenses = _parse_github_license(
        _http_get(
            f"{GITHUB_API_URL}/{_repo_slug(candidate.code_repo, candidate.arxiv_id)}",
            headers=headers,
        ),
        candidate.arxiv_id,
    )

    facts = LiveFacts(
        primary_category=category,
        license_name=license_name,
        version=version,
        code_license=code_licenses[0],
    )
    return facts, code_licenses


def verify_candidate(candidate: Candidate) -> Outcome:
    """Check one candidate's claims against the live sources.

    A candidate whose facts cannot be fetched is rejected rather than passed
    through: "unverified" and "verified" must not reach promotion looking alike,
    which is the whole reason this stage exists.
    """

    try:
        facts, code_licenses = fetch_live_facts(candidate)
    except PromotionError as error:
        return Outcome(candidate=candidate, status="unverifiable", reason=str(error))
    except urllib.error.HTTPError as error:
        return Outcome(
            candidate=candidate,
            status="unverifiable",
            reason=f"{candidate.arxiv_id}: live lookup returned HTTP {error.code}",
        )
    except (urllib.error.URLError, OSError, ValueError) as error:
        return Outcome(
            candidate=candidate,
            status="unverifiable",
            reason=f"{candidate.arxiv_id}: live lookup failed: {error}",
        )

    mismatches: list[Mismatch] = []
    if candidate.expected_license.strip() != facts.license_name:
        mismatches.append(
            Mismatch("expected_license", candidate.expected_license, facts.license_name)
        )
    if candidate.expected_category.strip().lower() != facts.primary_category.lower():
        mismatches.append(
            Mismatch("expected_category", candidate.expected_category, facts.primary_category)
        )
    claimed_code_license = candidate.code_license.strip().lower()
    if claimed_code_license not in {spelling.lower() for spelling in code_licenses}:
        mismatches.append(Mismatch("code_license", candidate.code_license, facts.code_license))

    if mismatches:
        return Outcome(
            candidate=candidate,
            status="rejected",
            mismatches=tuple(mismatches),
            live=facts,
        )
    return Outcome(candidate=candidate, status="eligible", live=facts)


def read_promoted(path: Path) -> list[dict]:
    """Existing promotions, as raw records. A missing file is an empty list."""

    if not path.is_file():
        return []
    records: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise PromotionError(f"{path.name}:{number} is not valid JSON: {error}") from error
        if not isinstance(record, dict):
            raise PromotionError(f"{path.name}:{number} is not a JSON object")
        records.append(record)
    return records


def next_paper_index(promoted: list[dict]) -> int:
    """One past the highest `paper_N` in the hand-curated tuple and the JSONL.

    Both sources are consulted because they number from one sequence: `papers.py`
    holds `paper_1..paper_3` today, and a second promotion run must not reissue
    an id the first one already used.
    """

    highest = 0
    known = [spec.paper_id for spec in APPROVED_PAPERS]
    known += [str(record.get("paper_id", "")) for record in promoted]
    for paper_id in known:
        match = re.fullmatch(r"paper_(\d+)", paper_id.strip())
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def spec_from_candidate(candidate: Candidate, paper_id: str) -> PaperSpec:
    """A `PaperSpec` carrying exactly the candidate's verified claims."""

    return PaperSpec(
        paper_id=paper_id,
        arxiv_id=candidate.arxiv_id,
        paper_type=candidate.paper_type,
        code_repo=candidate.code_repo,
        expected_license=candidate.expected_license,
        expected_version=candidate.expected_version,
        expected_category=candidate.expected_category,
        note=candidate.note,
    )


def summarize(
    outcomes: list[Outcome],
    *,
    promoted: list[PaperSpec],
    dry_run: bool,
    human_reviewer: str | None,
) -> dict:
    """The run, as one JSON-able record. Shaped like `fidelity.audit.summarize`."""

    by_status: dict[str, int] = {}
    for outcome in outcomes:
        by_status[outcome.status] = by_status.get(outcome.status, 0) + 1
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "total_candidates": len(outcomes),
        "eligible": by_status.get("eligible", 0),
        "rejected": by_status.get("rejected", 0),
        "unverifiable": by_status.get("unverifiable", 0),
        "awaiting_human_approval": by_status.get("awaiting-human-approval", 0),
        "already_promoted": by_status.get("already-promoted", 0),
        "human_approval": human_reviewer is not None,
        "human_reviewer": human_reviewer,
        "promoted_now": len(promoted),
        "promoted_paper_ids": [spec.paper_id for spec in promoted],
        "rejected_detail": [
            {
                "arxiv_id": outcome.candidate.arxiv_id,
                "status": outcome.status,
                "reason": outcome.describe(),
            }
            for outcome in outcomes
            if outcome.status in {"rejected", "unverifiable"}
        ],
    }


def _report(outcomes: list[Outcome], summary: dict, *, dry_run: bool) -> None:
    _log("")
    for outcome in outcomes:
        line = f"{outcome.candidate.arxiv_id}: {outcome.status}"
        detail = outcome.describe()
        _log(f"{line} — {detail}" if detail else line)

    _log("")
    if dry_run:
        _log("dry run — nothing was written. Re-run with --promote to write.")
    _log(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "total_candidates",
                    "eligible",
                    "rejected",
                    "unverifiable",
                    "already_promoted",
                    "promoted_now",
                )
            }
        )
    )


def promote(
    candidates: list[Candidate],
    *,
    approved_file: Path,
    promote_now: bool,
    limit: int | None,
    approved_arxiv_ids: frozenset[str] | None = None,
    human_reviewer: str | None = None,
) -> tuple[list[Outcome], list[PaperSpec], dict]:
    """Verify every candidate, then write the accepted ones if asked to.

    Idempotency is keyed on `arxiv_id`, never `paper_id`: the id is assigned at
    promotion time and would differ between two runs over the same candidate, so
    comparing ids would duplicate every entry on the second run.
    """

    promoted_records = read_promoted(approved_file)
    seen_arxiv_ids = {str(record.get("arxiv_id", "")).strip() for record in promoted_records}
    seen_arxiv_ids |= {spec.arxiv_id for spec in APPROVED_PAPERS}

    outcomes: list[Outcome] = []
    accepted: list[PaperSpec] = []
    next_index = next_paper_index(promoted_records)

    for candidate in candidates:
        if candidate.arxiv_id in seen_arxiv_ids:
            outcomes.append(
                Outcome(
                    candidate=candidate,
                    status="already-promoted",
                    reason="already on the approved list; nothing to do",
                )
            )
            continue

        outcome = verify_candidate(candidate)
        outcomes.append(outcome)
        if not outcome.eligible:
            continue
        if promote_now and (
            approved_arxiv_ids is None or candidate.arxiv_id not in approved_arxiv_ids
        ):
            outcomes[-1] = Outcome(
                candidate=candidate,
                status="awaiting-human-approval",
                live=outcome.live,
                reason="eligible but not selected in the human approval record",
            )
            continue
        if limit is not None and len(accepted) >= limit:
            continue

        accepted.append(spec_from_candidate(candidate, f"paper_{next_index}"))
        next_index += 1
        seen_arxiv_ids.add(candidate.arxiv_id)

    written: list[PaperSpec] = []
    if promote_now and accepted:
        approved_file.parent.mkdir(parents=True, exist_ok=True)
        lines = "".join(
            json.dumps(
                {
                    "paper_id": spec.paper_id,
                    "arxiv_id": spec.arxiv_id,
                    "paper_type": spec.paper_type,
                    "code_repo": spec.code_repo,
                    "expected_license": spec.expected_license,
                    "expected_version": spec.expected_version,
                    "expected_category": spec.expected_category,
                    "note": spec.note,
                },
                sort_keys=True,
            )
            + "\n"
            for spec in accepted
        )
        with approved_file.open("a", encoding="utf-8") as handle:
            handle.write(lines)
        written = accepted

    summary = summarize(
        outcomes,
        promoted=written,
        dry_run=not promote_now,
        human_reviewer=human_reviewer,
    )
    return outcomes, written, summary


def read_candidates(
    path: Path, *, policy: ScreeningPolicy, exclude_ids: tuple[str, ...]
) -> list[Candidate]:
    """Read a proposal file, accepting either shape screening can produce.

    `core.screen.run_screening()` writes and reads back a bare JSON array — that
    contract is validated by `tests/test_construction_core_screen.py` and must
    not change. But `scripts/screen_lifesci_paperrecon_candidates.py --output`
    writes a human-readable *report* around the same candidates: an object with
    `generated_at`, `summary`, and a `candidates` array among its keys. A human
    (or the one-command agent) naturally hands this script whichever file
    screening actually wrote, and both are the real, current output of a real
    screening path — so this reads the file once, and if it is an object with a
    `candidates` list, re-serializes just that list to a temp file before
    handing it to `parse_candidates`, rather than asking `parse_candidates`
    itself to accept two shapes and weakening what it guarantees for its other
    caller.
    """

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ScreeningError(f"{path.name} is not valid JSON: {error}") from error
    except OSError as error:
        raise ScreeningError(f"cannot read {path}: {error}") from error

    if isinstance(raw, list):
        return parse_candidates(path, policy=policy, exclude_ids=exclude_ids)

    if isinstance(raw, dict) and isinstance(raw.get("candidates"), list):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(raw["candidates"], handle)
            temp_path = Path(handle.name)
        try:
            return parse_candidates(temp_path, policy=policy, exclude_ids=exclude_ids)
        finally:
            temp_path.unlink(missing_ok=True)

    raise ScreeningError(
        f"{path.name} is neither a JSON array of candidates nor an object with a "
        "'candidates' array"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        required=True,
        help="candidates.json from a screening run.",
    )
    parser.add_argument(
        "--approved-file",
        type=Path,
        default=APPROVED_SCALEUP_PATH,
        help=(
            "Where accepted candidates are appended, one JSON object per line "
            f"(default: {APPROVED_SCALEUP_PATH})."
        ),
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help=(
            "Actually write the accepted candidates. Without it this is a report "
            "and touches nothing."
        ),
    )
    parser.add_argument(
        "--human-approval",
        type=Path,
        default=None,
        help=(
            "Human-created JSON approval bound to the candidate file. Required with "
            "--promote; defaults to <candidates>.human-approval.json."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Promote at most this many eligible candidates, in file order.",
    )
    parser.add_argument("--report", type=Path, default=None, help="Write the summary here as JSON.")
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")

    try:
        candidates = read_candidates(
            args.candidates,
            policy=LIFESCI_SCREENING_POLICY,
            exclude_ids=LIFESCI_EXCLUDE_IDS,
        )
    except ScreeningError as error:
        _log(f"cannot read the proposal: {error}")
        return 1

    _log(f"{len(candidates)} candidate(s) in {args.candidates}")
    _log("verifying every claim against arXiv and GitHub — no model call")

    approval: HumanApproval | None = None
    if args.promote:
        approval_path = args.human_approval or _default_human_approval_path(args.candidates)
        try:
            approval = read_human_approval(
                approval_path,
                candidates_path=args.candidates,
                candidates=candidates,
            )
        except PromotionError as error:
            _log(f"cannot promote: {error}")
            return 1

    try:
        outcomes, written, summary = promote(
            candidates,
            approved_file=args.approved_file.resolve(),
            promote_now=args.promote,
            limit=args.limit,
            approved_arxiv_ids=approval.approved_arxiv_ids if approval else None,
            human_reviewer=approval.reviewer if approval else None,
        )
    except PromotionError as error:
        _log(f"cannot promote: {error}")
        return 1

    _report(outcomes, summary, dry_run=not args.promote)

    if written:
        _log(
            f"appended {len(written)} human-approved record(s) -> {args.approved_file} "
            f"(reviewer: {approval.reviewer})"
        )
        if args.approved_file.resolve() == APPROVED_SCALEUP_PATH.resolve():
            _log(
                "papers.py's loader reads this file automatically — "
                "APPROVED_PAPERS now includes these records."
            )
        else:
            _log(
                "note: this is not the default approved-scaleup path, so "
                "papers.py's loader will not pick it up automatically."
            )

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        _log(f"report -> {args.report}")

    blocked = summary["rejected"] + summary["unverifiable"]
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
