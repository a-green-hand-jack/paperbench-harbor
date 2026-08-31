"""Stage 3: does the overview actually let someone rebuild the paper?

:mod:`.validate` is ~28 deterministic checks and every one of them is
structural — headings present, lengths in range, no literal leakage, the oracle
compiles. None of them can tell whether the overview is *true about this paper*,
or whether it says enough to reconstruct it. A generated overview can satisfy
the entire gate while being a fluent description of nothing in particular, and
the only thing that has ever caught that is a human reading the overview against
the paper. That does not scale to 30-50 samples.

So a second model reads `original/main.tex` beside the generated overviews and
returns a verdict. Three properties of how it is wired matter more than the
prompt:

* **It is a different model family from the constructor.** Same-model
  self-grading is a known failure mode of generator-plus-judge loops: a model
  reviewing its own output tends to ratify its own misreadings, because the
  misreading and the review come from the same prior. The default reviewer is
  ``apex-claude/claude-sonnet-5`` against a ``openai/gpt-5.6-terra``
  constructor — a deliberately different vendor and architecture.

* **It cannot touch what it is grading.** The reviewer runs under the same
  ``opencode run --auto`` mode as construction, which is unsupervised
  filesystem write access to whatever ``--dir`` points at. A reviewer that can
  edit the sample it is reviewing is not a reviewer. :func:`run_review` copies
  the three files it needs into a throwaway scratch directory and points the
  agent at *that*; the live workspace is never reachable from the review
  session.

* **Its verdict is not trusted, only parsed.** ``verdict.json`` is checked for
  shape the same way `provenance.json` is in :mod:`.validate` — malformed JSON,
  a missing key or a wrong type is itself a failure, not a shrug. A reviewer
  that cannot produce a well-formed verdict has not reviewed anything.

The verdict rejoins the existing machinery rather than starting a parallel one:
:func:`~.pipeline.build_paper` turns a failing verdict into a
:class:`~.validate.ValidationIssue` on the same
:class:`~.validate.ValidationReport`, so ``report.ok`` recomputes to ``False``
and the next construction turn receives the reviewer's concerns through
``report.agent_feedback()`` exactly like a compile failure.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from paperbench_harbor.adapters.paperwrite_bench.converter import OVERVIEW_FILENAMES
from paperbench_harbor.construction.core.opencode_agent import (
    AgentRun,
    run_agent_session,
    tail_log,
)
from paperbench_harbor.construction.core.plugin import DomainPlugin
from paperbench_harbor.construction.core.spec import PaperSpec

#: A different vendor and architecture from :data:`.opencode_agent.DEFAULT_MODEL`,
#: on purpose — see this module's docstring. Confirmed present on the build
#: host's opencode install (`opencode models`, 2026-08-31). Capable enough for a
#: faithfulness judgment without being the most expensive tier available, which
#: matters for a check that runs on every paper of every turn.
DEFAULT_REVIEWER_MODEL = "apex-claude/claude-sonnet-5"

#: Reading two overviews and a paper is a much smaller job than building a
#: sample, so review does not inherit construction's 90-minute budget.
DEFAULT_REVIEW_TIMEOUT_SECONDS = 1800

#: The verdict's required keys and their required types. Shape is validated
#: rather than assumed, for the same reason `provenance.json`'s is.
_VERDICT_SCHEMA: tuple[tuple[str, type | tuple[type, ...]], ...] = (
    ("ok", bool),
    ("reasoning", str),
    ("concerns", list),
)

VERDICT_FILENAME = "verdict.json"

#: What the reviewer is allowed to see, as ``(source path, name in the scratch
#: dir)``. Exactly the ground truth and the two generated overviews: not
#: `provenance.json` (which would tell it what the constructor claims), not
#: `template.tex`, not the figures. The question is whether the overview
#: describes the paper, and anything else is a chance to answer a different one.
REVIEW_INPUTS: tuple[tuple[str, str], ...] = (
    ("original/main.tex", "main.tex"),
    (f"resources/{OVERVIEW_FILENAMES['short']}", OVERVIEW_FILENAMES["short"]),
    (f"resources/{OVERVIEW_FILENAMES['long']}", OVERVIEW_FILENAMES["long"]),
)


class ReviewError(RuntimeError):
    """The reviewer did not produce a verdict this code is willing to read."""


@dataclass(frozen=True)
class ReviewVerdict:
    """One reviewer's answer about one sample.

    `concerns` is separate from `reasoning` because the two have different
    readers: `reasoning` is the judgment a human auditing the corpus wants, and
    `concerns` is the actionable list the next construction turn is asked to
    fix. A verdict that fails with no concerns is a verdict the constructor
    cannot act on.
    """

    ok: bool
    reasoning: str
    concerns: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "reasoning": self.reasoning, "concerns": list(self.concerns)}

    def remedy(self) -> str:
        """The retry instruction attached to a failing verdict."""

        base = (
            "Revise the overview so it is faithful and sufficient without leaking "
            "prose/citations"
        )
        if not self.concerns:
            return base + "."
        return base + "; specific concerns: " + "; ".join(self.concerns)


def default_reviewer_model() -> str:
    """The reviewer model, resolved.

    Precedence is CLI flag (the caller passes it in), then the ``REVIEWER_MODEL``
    environment variable, then :data:`DEFAULT_REVIEWER_MODEL` — mirroring the
    ``JUDGE_MODEL`` convention the rest of the project already uses for
    model choices that a deployment may want to override without editing code.
    """

    return os.environ.get("REVIEWER_MODEL", "").strip() or DEFAULT_REVIEWER_MODEL


def build_review_prompt(spec: PaperSpec, plugin: DomainPlugin, review_dir: Path) -> str:
    """The reconstructability question, as the reviewer receives it.

    Written to make disagreement cheap. The prompt says explicitly that passing
    is not the default answer and that a specific, quotable objection is worth
    more than a verdict — because a reviewer that hedges toward `ok: true` costs
    nothing to run and catches nothing, which is the failure mode that makes
    automated review worthless.
    """

    short = OVERVIEW_FILENAMES["short"]
    long = OVERVIEW_FILENAMES["long"]
    skeleton_headings = ", ".join(plugin.overview_skeleton_headings)

    return f"""\
You are reviewing one sample of a paper-reconstruction benchmark before it is
admitted to the corpus. You are not building anything and you are not fixing
anything. You answer one question and write one file.

# The question

A writing agent will be given **only** the research overview (plus the paper's
figures, tables and bibliography, which you do not need to see) and asked to
reconstruct the paper. Judge whether that is possible from what is written
here, and whether what is written here is true.

# The files, all in `{review_dir}`

- `main.tex` — the ground-truth paper, an arXiv {plugin.domain_label} paper
  (`{spec.arxiv_id}{spec.expected_version}`, category `{spec.expected_category}`).
- `{short}` — the short overview variant, generated from that paper.
- `{long}` — the long overview variant, generated from that paper.

Read all three in full before judging. The overviews follow a fixed skeleton
({skeleton_headings}); the skeleton itself is already checked by other code, so
do not spend the review on formatting.

# The three tests

1. **Faithful.** Every specific claim in the overviews is supported by the
   paper: the quantities, dataset and organism identifiers, model parameters,
   effect sizes, and the direction of every result. A number that disagrees with
   the paper, a result stated more strongly than the paper states it, or a
   method the paper does not use is a failure. So is a confident claim the paper
   does not make at all — invented specificity is worse than vagueness, because
   the writing agent will reproduce it.

   One asymmetry to hold onto here: **you are not shown the paper's figures, and
   the overviews' author was.** It was explicitly instructed to read values off
   the plots. So a quantity that is not in `main.tex`'s prose is not, on its
   own, invented — it may have been read from a figure you cannot see. Treat a
   value as unfaithful only when it *contradicts* something the text states, is
   impossible given the text, or describes something the paper has no figure or
   table for. Where the text states a bound, a point value that violates that
   bound is a contradiction no matter which figure it came from; where the text
   is merely silent, a plausible plotted value is not.

2. **Sufficient.** Someone who has read only the overview could write a paper
   with this paper's scientific content: the same question, the same approach in
   enough operational detail to describe it, the same findings with their actual
   values, and the same significance. Ask concretely what a writer would have to
   invent, and name it. The long variant must carry strictly more real detail
   than the short one, not the same content restated at greater length.

3. **No literal leakage.** The overview must describe the study, not reproduce
   the paper. Sentences or clauses lifted verbatim from `main.tex`, the paper's
   own section headings used as overview structure, citation keys, `\\cite`
   commands or LaTeX markup all mean the answer has been handed over rather
   than described. Paraphrase is expected and fine; shared technical terms,
   named methods, gene/species/dataset names and numeric values are not leakage
   — those are the content. Judge whether prose was copied, not whether
   vocabulary overlaps.

# How to judge

Passing is not the default. Read the paper first and form your own account of
what it did, then check the overviews against that account rather than reading
the overviews and looking for something to object to.

But do not manufacture objections either. A concern is worth writing down only
if you can point at the specific sentence, number or omission that causes it,
and only if it would actually damage a reconstruction attempt. Stylistic
preferences, "could be more detailed" in the abstract, and disagreements about
emphasis are not concerns. If the overviews are faithful and sufficient, say so
and pass.

# What to write

Write `{review_dir}/{VERDICT_FILENAME}`, a single JSON object, exactly this
shape and nothing else:

```json
{{
  "ok": true,
  "reasoning": "...",
  "concerns": []
}}
```

- `ok` — a JSON boolean, not a string. `true` only if all three tests pass.
- `reasoning` — a few sentences of your actual judgment, citing specific
  content from the paper and the overviews. "The overview is faithful and
  sufficient" on its own is not an acceptable answer; name what you checked.
- `concerns` — a list of strings, each one a specific, actionable problem. If
  `ok` is `false` this must not be empty: the list is fed verbatim to the agent
  that will revise the overview, so each entry must say what is wrong and be
  specific enough to fix. If `ok` is `true` it should normally be `[]`; a minor
  observation that did not change your verdict may go here.

Do not modify `main.tex` or either overview file — they are copies, but editing
them defeats the point of the review. Write `{VERDICT_FILENAME}` and stop.
"""


def parse_verdict(path: Path) -> ReviewVerdict:
    """Read `verdict.json` and validate its shape. Raises, never guesses.

    The reviewer is an LLM and its output file is untrusted input, exactly like
    the construction agent's `provenance.json`. Coercing a malformed verdict
    into something usable would mean the one thing that must never happen here:
    a paper admitted on a verdict nobody actually read.
    """

    if not path.is_file():
        raise ReviewError(f"the reviewer wrote no {path.name}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ReviewError(f"{path.name} is not valid JSON: {error}") from error
    if not isinstance(record, dict):
        raise ReviewError(f"{path.name} is not a JSON object")

    for key, expected_type in _VERDICT_SCHEMA:
        if key not in record:
            raise ReviewError(f"{path.name} is missing the {key!r} key")
        # `bool` is a subclass of `int`, so an `ok: 1` would pass a naive
        # isinstance check against `int`; checking the other direction is what
        # keeps `"ok": "true"` and `"ok": 1` out.
        if not isinstance(record[key], expected_type):
            raise ReviewError(
                f"{path.name} {key!r} is {type(record[key]).__name__}, expected "
                f"{expected_type.__name__}"  # type: ignore[union-attr]
            )

    concerns = record["concerns"]
    if not all(isinstance(entry, str) for entry in concerns):
        raise ReviewError(f"{path.name} 'concerns' must be a list of strings")

    reasoning = record["reasoning"].strip()
    if not reasoning:
        raise ReviewError(f"{path.name} 'reasoning' is empty")

    verdict = ReviewVerdict(
        ok=record["ok"],
        reasoning=reasoning,
        concerns=[entry.strip() for entry in concerns if entry.strip()],
    )
    if not verdict.ok and not verdict.concerns:
        raise ReviewError(
            f"{path.name} rejects the sample but lists no concerns; the retry turn "
            "would have nothing to act on"
        )
    return verdict


def prepare_review_dir(paper_dir: Path, review_dir: Path) -> Path:
    """Stage a throwaway copy of just the three files the reviewer may see.

    Fresh every call. A stale review directory would let a reviewer grade last
    turn's overview and pass a sample that no longer contains it.
    """

    if review_dir.exists():
        shutil.rmtree(review_dir)
    review_dir.mkdir(parents=True)

    missing: list[str] = []
    for relative, name in REVIEW_INPUTS:
        source = paper_dir / relative
        if not source.is_file():
            missing.append(relative)
            continue
        shutil.copy2(source, review_dir / name)
    if missing:
        raise ReviewError(
            "cannot review a sample that is missing " + ", ".join(missing)
        )
    return review_dir


def run_review(
    spec: PaperSpec,
    plugin: DomainPlugin,
    paper_dir: Path,
    *,
    build_root: Path,
    model: str | None = None,
    log_dir: Path,
    timeout: int = DEFAULT_REVIEW_TIMEOUT_SECONDS,
    dry_run: bool = False,
) -> ReviewVerdict:
    """Run the reconstructability review for one built sample.

    `paper_dir` is read, never handed to the agent: the three reviewable files
    are copied into ``<build_root>/<paper_id>/review/`` and the agent's
    ``--dir`` points there.

    Every failure mode returns a failing :class:`ReviewVerdict` rather than
    raising, because the caller's response to "the reviewer crashed" and to "the
    reviewer said no" is the same one: do not admit this paper yet, and tell the
    construction agent why. The one exception is
    :class:`~.opencode_agent.ScratchLocationError`, which means the scratch
    location itself is unsafe and is a bug in the caller, not a verdict.
    """

    review_dir = (build_root / spec.paper_id / "review").resolve()
    try:
        prepare_review_dir(paper_dir, review_dir)
    except ReviewError as error:
        return ReviewVerdict(ok=False, reasoning=str(error), concerns=[str(error)])

    if dry_run:
        # A dry run proves the plumbing, not the paper. Returning a failing
        # verdict here would make `--dry-run` look like a rejection.
        return ReviewVerdict(
            ok=True,
            reasoning="dry run: the reviewer was not invoked.",
            concerns=[],
        )

    run: AgentRun = run_agent_session(
        paper_id=f"{spec.paper_id}.review",
        prompt=build_review_prompt(spec, plugin, review_dir),
        workspace=review_dir,
        log_dir=log_dir,
        model=model or default_reviewer_model(),
        turn=1,
        continue_session=False,
        timeout=timeout,
        dry_run=False,
    )

    verdict_path = review_dir / VERDICT_FILENAME
    try:
        verdict = parse_verdict(verdict_path)
    except ReviewError as error:
        # An agent that exited badly usually also wrote no verdict; report the
        # run failure, since it is the cause and the verdict error is the
        # symptom.
        if not run.ok:
            reason = (
                f"the reviewer exited {run.returncode} "
                f"(timed_out={run.timed_out}) and produced no usable verdict: "
                f"{error}. Log tail:\n{tail_log(run, 20)}"
            )
        else:
            reason = f"the reviewer produced an unusable verdict: {error}"
        return ReviewVerdict(ok=False, reasoning=reason, concerns=[str(error)])

    return verdict


def write_review_record(paper_dir: Path, verdict: ReviewVerdict) -> Path:
    """Record the verdict beside `provenance.json`, as verifier-only ground truth.

    Under `original/`, never `resources/`: `resources/` is copied verbatim into
    the writing agent's environment, and a reviewer's account of what the
    overview does and does not contain is a description of the answer.
    """

    destination = paper_dir / "original" / "reconstructability_review.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(verdict.as_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination
