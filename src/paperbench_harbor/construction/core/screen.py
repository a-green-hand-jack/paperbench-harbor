"""Stage 1: proposing which papers should become samples at all.

Construction and review both start from a paper someone already chose. This is
where the choosing happens, and it is an agent rather than a script for the same
reason construction is: the criteria are checkable but not enumerable. "Has
LaTeX source" is a fact about an e-print bundle you have to fetch and look
inside; "the linked repository is the one this paper is about" is a judgment;
"this is a review article, not an experimental study" is a reading. A fixed
script over the arXiv API can filter on category and date and nothing else that
matters.

Two boundaries keep an agent-driven selector from becoming an unaccountable one.

**The output is a proposal, not a decision.** :func:`run_screening` writes
`candidates.json` and stops. Nothing here appends to a domain's approved-papers
module. That invariant is load-bearing rather than procedural: the construction
gate's `provenance-mismatch` check works by comparing what the construction
agent found against what a human approved, and it stops meaning anything the
moment the approved list is itself machine-generated. A screening agent that
could promote its own candidates would close that loop and quietly remove the
only check on a silently substituted paper.

**Every fact is fetched, not recalled.** The prompt tells the agent to read the
live arXiv page and `GET /repos/{owner}/{repo}` for each candidate, including
the ones handed to it as seeds. A model asked about a paper it may have seen in
training will produce a confident license string; the point of giving it network
access and bash is that it never has to.

The code-repository *license* is recorded but does not filter (owner decision,
2026-08-31): an unlicensed repository no longer disqualifies a paper, but the
finding has to survive into the dataset card, so it is a required field on every
proposed candidate rather than an optional note.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from paperbench_harbor.construction.core.opencode_agent import (
    DEFAULT_MODEL,
    AgentRun,
    run_agent_session,
    tail_log,
)
from paperbench_harbor.construction.core.spec import ACCEPTED_LICENSES

#: Screening is proposing candidates, not grading generated content, so the
#: same-model bias that forces :mod:`.review` onto a different vendor does not
#: apply — the constructor's model is a fine default here.
DEFAULT_SCREENING_MODEL = DEFAULT_MODEL

#: Fetching and checking a few dozen candidates is a long job, but it is network
#: waiting rather than compile iteration.
DEFAULT_SCREENING_TIMEOUT_SECONDS = 5400

CANDIDATES_FILENAME = "candidates.json"

#: Every proposed candidate carries exactly the fields a :class:`~.spec.PaperSpec`
#: needs, plus the two a human needs to decide with (`code_license`, which is
#: recorded but never filters, and `rationale`). Shape is validated, not trusted.
REQUIRED_CANDIDATE_FIELDS: tuple[str, ...] = (
    "arxiv_id",
    "expected_version",
    "code_repo",
    "expected_license",
    "code_license",
    "expected_category",
    "paper_type",
    "note",
    "rationale",
)


class ScreeningError(RuntimeError):
    """The screening agent did not produce a candidate list this code will read."""


@dataclass(frozen=True)
class ScreeningPolicy:
    """What a domain considers a findable, usable paper.

    Deliberately **not** part of :class:`~.plugin.DomainPlugin`. Screening and
    construction are different jobs with different failure modes, and almost
    nothing a `DomainPlugin` carries — overview skeletons, caption idiom,
    significance headings — has any bearing on where to look for a paper. The
    one thing they must agree on is :attr:`paper_types`, because a candidate's
    proposed type has to be a type the domain's construction gate will accept;
    a domain builds its policy from its plugin's tuple rather than restating it.
    """

    #: Short machine name, matching the domain's plugin (`"lifesci"`).
    name: str

    #: Where to look, as a prompt fragment: arXiv categories, listing pages,
    #: any domain-specific corner of the literature worth searching.
    search_scope: str

    #: What qualifies, as a prompt fragment: source availability, license
    #: policy, recency, code-repository expectations, bibliography availability.
    #: The core appends the invariants no domain may weaken.
    selection_criteria: str

    #: The domain's construction paper-type taxonomy, so a proposed candidate
    #: carries a type the construction gate will accept. Must equal the
    #: domain plugin's `paper_types`.
    paper_types: tuple[str, ...]

    #: What a previous screening pass actually learned — dead-end categories,
    #: which filter turned out to bind hardest, anything that would otherwise be
    #: rediscovered at full cost. Free text, may be empty.
    prior_findings: str = ""


@dataclass(frozen=True)
class SeedCandidate:
    """A paper a previous pass identified, to be re-verified rather than trusted.

    Carries only what a human wrote down. Everything else about it — the current
    license, whether the repository still exists, whether the e-print still has
    LaTeX source — is what the screening run is for.
    """

    arxiv_id: str
    title: str = ""
    note: str = ""


@dataclass(frozen=True)
class Candidate:
    """One proposed paper. Spec-shaped, but not yet a :class:`~.spec.PaperSpec`.

    The gap between this and a `PaperSpec` is exactly one human decision, and
    the type difference is there to make sure that gap cannot be crossed by
    accident.
    """

    arxiv_id: str
    expected_version: str
    code_repo: str
    expected_license: str
    code_license: str
    expected_category: str
    paper_type: str
    note: str
    rationale: str

    def as_dict(self) -> dict:
        return asdict(self)


def build_screening_prompt(
    policy: ScreeningPolicy,
    *,
    seed_candidates: tuple[SeedCandidate, ...] = (),
    target_count: int,
    exclude_ids: tuple[str, ...] = (),
    extra_guidance: str = "",
    output_path: Path,
) -> str:
    """The screening task for one domain.

    `seed_candidates` are re-verified first and searching only fills whatever
    gap remains against `target_count`, so a domain that has screened before
    pays for confirmation rather than for a fresh survey. An empty seed list is
    a normal case, not an error: it means nothing machine-readable survived from
    the previous pass, and the agent should search from scratch.

    `extra_guidance` carries one caller's topical steering for one run (e.g. "prefer
    genomics/protein work") — it is not part of the domain's own
    :class:`ScreeningPolicy`, which describes what the domain finds acceptable at
    all, not what one particular request happened to ask for. Appended to the
    same fragment as `policy.prior_findings` rather than woven into the
    invariants: it can narrow which qualifying papers get proposed, never
    relax what qualifies.
    """

    licenses = "\n".join(f"   - `{name}`" for name in ACCEPTED_LICENSES)
    types = ", ".join(f"`{name}`" for name in policy.paper_types)

    if seed_candidates:
        seed_rows = "\n".join(
            f"{index}. `{seed.arxiv_id}`"
            + (f" — {seed.title}" if seed.title else "")
            + (f" ({seed.note})" if seed.note else "")
            for index, seed in enumerate(seed_candidates, start=1)
        )
        seed_block = f"""\
## Step 1 — re-verify these {len(seed_candidates)} known candidates

A previous screening pass identified these. **Treat every one as unverified.**
Its license may have changed, its repository may be gone, its latest version may
differ. Check each against the live sources and keep only the ones that still
qualify today.

{seed_rows}

## Step 2 — search for the rest

Only if step 1 leaves you short of {target_count} qualifying candidates, search
for more."""
    else:
        seed_block = f"""\
## Step 1 — search

No machine-readable candidate list survived from any previous screening pass,
so there is nothing to re-verify and you are searching from scratch. Find
{target_count} qualifying candidates."""

    exclude_block = (
        "\n".join(f"   - `{arxiv_id}`" for arxiv_id in exclude_ids)
        if exclude_ids
        else "   (nothing — no samples have been built yet)"
    )

    prior = (
        f"\n## What the last pass learned\n\n{policy.prior_findings}\n"
        if policy.prior_findings
        else ""
    )

    guidance = (
        f"\n## This run's topical steering\n\n"
        f"{extra_guidance}\n\n"
        f"This narrows which *qualifying* papers to prefer. It never relaxes any "
        f"invariant above — a paper that fails one of them is still excluded, no "
        f"matter how well it matches this steering.\n"
        if extra_guidance
        else ""
    )

    return f"""\
You are screening candidate papers for a paper-reconstruction benchmark. Your
output is a **proposal** that a human will review. You are not building
anything, and you are not adding anything to any approved list.

Propose {target_count} papers that satisfy every criterion below. Verify each one
against live sources — the arXiv abstract page, the e-print bundle, and the
GitHub API. Do not answer from memory about any paper; a license or a repository
you recall may have changed, and a plausible-looking wrong answer here costs a
whole failed construction run to discover.

# Where to look

{policy.search_scope}

# What qualifies

{policy.selection_criteria}

## Invariants — these are not the domain's to relax

1. **The paper's own license must be one of:**
{licenses}
   This benchmark redistributes material derived from the paper. Read the
   license off the live arXiv abstract page; do not infer it from the journal,
   the year, or the other papers by the same authors. This filter is the one
   that rejects the most papers, so check it first and stop early on failures.
2. **The submission must have real LaTeX source.** Fetch the e-print bundle and
   look inside. A PDF-only submission is disqualified — there is nothing to
   build from.
3. **A bibliography must be recoverable** from the bundle: a `.bib`, a `.bbl`,
   or inline `\\bibitem`s. Any of the three is fine.
4. **A public code repository must exist and be checkable out.** Its *license*
   is **not** a filter — an unlicensed repository is acceptable — but you must
   record what you actually find. Call `GET /repos/{{owner}}/{{repo}}` and read
   the `license` field rather than guessing from the presence of a file:
   `license: null` means you record `"none declared"`, which is a valid and
   expected answer.
5. **`expected_category` must be the submission's *primary* category**, the one
   arXiv cites it as (the `[cs.LG]` in the "Cite as:" line), read off the live
   abstract page or the API's `<arxiv:primary_category>` element. A cross-list
   is not the primary category. This matters because the construction gate
   compares your recorded category against the approved spec for exact
   equality, so a cross-list recorded here does not merely look untidy — it
   stops that paper's build outright, after the fetch and the compile have
   already been paid for. Where the domain's criteria accept a cross-listed
   paper, record the true primary here and name the qualifying cross-list in
   `rationale`; never substitute the cross-list for the primary to make a paper
   look more in-scope than it is actually filed.
6. **Exclude these arXiv IDs.** Samples have already been built from them:
{exclude_block}
{prior}{guidance}
{seed_block}

# Output

Write `{output_path}`: a JSON array, one object per proposed candidate, with
exactly these keys and string values (except where noted):

```json
[
  {{
    "arxiv_id": "<the arXiv id, no version suffix>",
    "expected_version": "<the version you verified, e.g. v2>",
    "code_repo": "https://github.com/owner/repo",
    "expected_license": "CC BY 4.0",
    "code_license": "MIT",
    "expected_category": "<the arXiv category you verified>",
    "paper_type": "<one of the types below>",
    "note": "One line on what the paper is about.",
    "rationale": "Why this one qualifies, and anything a human deciding should know."
  }}
]
```

- `expected_license` — the paper's license, verbatim from the arXiv page, and
  one of the accepted list above. A paper whose license is not on that list does
  not go in the file at all.
- `code_license` — verbatim from the GitHub API's `license` field, or
  `"none declared"`. Never blank, never guessed.
- `expected_category` — the submission's primary category, verbatim, per
  invariant 5. Not a cross-list.
- `paper_type` — one of {types}. This is a guess a human will confirm; say in
  `rationale` if you were unsure.
- `expected_version` — the version you actually verified, e.g. `v1`.
- Every key must be present on every entry, and no entry may repeat an
  `arxiv_id` or use an excluded one.

Write nothing but that file. If you cannot reach {target_count} qualifying
candidates, write the ones you found and say so in your final message — a short
honest list is worth more than a padded one, and every entry you cannot fully
verify costs a human the same check again.
"""


def parse_candidates(
    path: Path,
    *,
    policy: ScreeningPolicy | None = None,
    exclude_ids: tuple[str, ...] = (),
) -> list[Candidate]:
    """Read `candidates.json` and validate its shape. Raises, never guesses.

    Applies the filters the prompt asked for rather than assuming they were
    honoured: a candidate whose license is outside :data:`ACCEPTED_LICENSES`, or
    whose `arxiv_id` was on the exclusion list, means the agent did not follow
    the criteria, and a file that quietly contains one cannot be told apart from
    a file that was screened properly.
    """

    if not path.is_file():
        raise ScreeningError(f"the screening agent wrote no {path.name}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ScreeningError(f"{path.name} is not valid JSON: {error}") from error
    if not isinstance(record, list):
        raise ScreeningError(f"{path.name} is not a JSON array")

    excluded = {arxiv_id.strip() for arxiv_id in exclude_ids}
    candidates: list[Candidate] = []
    seen: set[str] = set()

    for index, entry in enumerate(record):
        where = f"{path.name}[{index}]"
        if not isinstance(entry, dict):
            raise ScreeningError(f"{where} is not a JSON object")
        values: dict[str, str] = {}
        for field_name in REQUIRED_CANDIDATE_FIELDS:
            if field_name not in entry:
                raise ScreeningError(f"{where} is missing the {field_name!r} key")
            value = entry[field_name]
            if not isinstance(value, str):
                raise ScreeningError(
                    f"{where} {field_name!r} is {type(value).__name__}, expected str"
                )
            values[field_name] = value.strip()

        # `note` may be empty; nothing else may. An empty `code_license` is the
        # exact failure the record-don't-block policy exists to prevent.
        for field_name in REQUIRED_CANDIDATE_FIELDS:
            if field_name != "note" and not values[field_name]:
                raise ScreeningError(f"{where} {field_name!r} is empty")

        arxiv_id = values["arxiv_id"]
        if arxiv_id in seen:
            raise ScreeningError(f"{where} repeats arxiv_id {arxiv_id!r}")
        if arxiv_id in excluded:
            raise ScreeningError(
                f"{where} proposes {arxiv_id!r}, which was on the exclusion list"
            )
        seen.add(arxiv_id)

        if values["expected_license"] not in ACCEPTED_LICENSES:
            raise ScreeningError(
                f"{where} license {values['expected_license']!r} is not "
                f"redistribution-permissive (accepted: {', '.join(ACCEPTED_LICENSES)})"
            )
        if policy is not None and values["paper_type"] not in policy.paper_types:
            raise ScreeningError(
                f"{where} paper_type {values['paper_type']!r} is not one of "
                f"{policy.paper_types}"
            )

        candidates.append(Candidate(**values))

    return candidates


def run_screening(
    policy: ScreeningPolicy,
    *,
    build_root: Path,
    seed_candidates: tuple[SeedCandidate, ...] = (),
    target_count: int,
    exclude_ids: tuple[str, ...] = (),
    extra_guidance: str = "",
    model: str = DEFAULT_SCREENING_MODEL,
    log_dir: Path,
    timeout: int = DEFAULT_SCREENING_TIMEOUT_SECONDS,
    dry_run: bool = False,
) -> list[Candidate]:
    """Run one screening pass and return the validated proposal.

    The agent works in its own scratch directory under `build_root`, like every
    other `--auto` session in this package: it has network access and bash
    because it needs to fetch and inspect, and it has nothing else in reach.

    `extra_guidance` is one caller's topical steering for this run only (see
    :func:`build_screening_prompt`); it is not persisted anywhere and does not
    change what the domain's `ScreeningPolicy` considers acceptable.

    Unlike :func:`~.review.run_review`, failures raise. A review failure is a
    verdict about a paper and the loop knows what to do with it; a screening
    failure means there is no proposal, and there is nobody downstream to hand
    that to but the caller.
    """

    screening_dir = (build_root / f"screening-{policy.name}").resolve()
    screening_dir.mkdir(parents=True, exist_ok=True)
    output_path = screening_dir / CANDIDATES_FILENAME
    if output_path.exists():
        # A stale proposal read back as a fresh one is the worst outcome here:
        # it looks like a successful run and is a previous pass's answer.
        output_path.unlink()

    prompt = build_screening_prompt(
        policy,
        seed_candidates=seed_candidates,
        target_count=target_count,
        exclude_ids=exclude_ids,
        extra_guidance=extra_guidance,
        output_path=output_path,
    )

    if dry_run:
        return []

    run: AgentRun = run_agent_session(
        paper_id=f"screening-{policy.name}",
        prompt=prompt,
        workspace=screening_dir,
        log_dir=log_dir,
        model=model,
        turn=1,
        continue_session=False,
        timeout=timeout,
        dry_run=False,
    )

    try:
        return parse_candidates(output_path, policy=policy, exclude_ids=exclude_ids)
    except ScreeningError as error:
        if not run.ok:
            raise ScreeningError(
                f"the screening agent exited {run.returncode} "
                f"(timed_out={run.timed_out}) and produced no usable proposal: "
                f"{error}. Log tail:\n{tail_log(run, 20)}"
            ) from error
        raise
