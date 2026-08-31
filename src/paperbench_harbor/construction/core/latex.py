"""Recompilation under exactly the constraints the Harbor verifier imposes.

The verifier (`common/templates/test_state.py.j2`) recompiles the submission in
a clean copy with `pdflatex -interaction=nonstopmode -halt-on-error
-no-shell-escape` (twice, then `bibtex`, then twice more), with no network.
This module reproduces that sequence locally so a paper is rejected at
construction time rather than shipping a task the oracle cannot solve.

`bibtex` is best-effort here for the same reason it is in the verifier: real
`references.bib` files are occasionally malformed and unresolved citations are
not a compile error. Citation coverage is checked separately, and exactly, by
:mod:`.validate`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Style/bibliography-style files this repository bundles into every task's
#: `texmf/`. Mirrors `adapters.paperwrite_bench.converter._copy_styles` and
#: `_copy_bibliography_styles`, so a local compile sees what the task will.
STYLES_DIR = Path(__file__).resolve().parents[4] / "packaging" / "conference-styles"
CONFERENCE_TEMPLATES_DIR = (
    Path(__file__).resolve().parents[4] / "packaging" / "conference-templates"
)

_PDFLATEX = ("pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape")

_USEPACKAGE_RE = re.compile(r"\\usepackage(?:\[[^]]*\])?\{([^}]+)\}")
_BIBSTYLE_RE = re.compile(r"\\bibliographystyle\{([^}]+)\}")
_TEX_ERROR_RE = re.compile(r"^(?:! .*|l\.\d+ .*)$", re.MULTILINE)


@dataclass(frozen=True)
class CompileResult:
    """Outcome of one restricted recompilation."""

    ok: bool
    tex_name: str
    failed_command: tuple[str, ...] | None = None
    log_excerpt: str = ""

    def summary(self) -> str:
        if self.ok:
            return f"{self.tex_name}: compiled"
        command = " ".join(self.failed_command or ())
        return f"{self.tex_name}: FAILED ({command})\n{self.log_excerpt}"


def _style_search_dirs() -> list[Path]:
    dirs = [STYLES_DIR]
    if CONFERENCE_TEMPLATES_DIR.is_dir():
        dirs.extend(sorted(path for path in CONFERENCE_TEMPLATES_DIR.iterdir() if path.is_dir()))
    return dirs


def stage_bundled_styles(tex_files: list[Path], texmf: Path) -> list[str]:
    """Copy every bundled `.sty`/`.bst` the given sources reference into `texmf`.

    Returns the names copied, so a caller can report which of a paper's
    dependencies are satisfied by this repository's bundle rather than by the
    paper's own source tree.
    """

    texmf.mkdir(parents=True, exist_ok=True)
    search_dirs = _style_search_dirs()
    copied: list[str] = []
    wanted: list[tuple[str, str]] = []
    for tex_file in tex_files:
        if not tex_file.is_file():
            continue
        text = tex_file.read_text(encoding="utf-8", errors="replace")
        for match in _USEPACKAGE_RE.finditer(text):
            wanted.extend((name.strip(), "sty") for name in match.group(1).split(","))
        wanted.extend((match.group(1).strip(), "bst") for match in _BIBSTYLE_RE.finditer(text))

    seen: set[tuple[str, str]] = set()
    for name, suffix in wanted:
        if not name or (name, suffix) in seen:
            continue
        seen.add((name, suffix))
        for directory in search_dirs:
            bundled = directory / f"{name}.{suffix}"
            if bundled.is_file():
                shutil.copy2(bundled, texmf / bundled.name)
                copied.append(bundled.name)
                break
    return copied


def compile_restricted(
    source_root: Path,
    tex_name: str,
    build_dir: Path,
    *,
    timeout: int = 600,
) -> CompileResult:
    """Copy `source_root` into `build_dir` and recompile `tex_name` there.

    The copy matters: it is how the verifier runs, and it catches sources that
    only compile because of stray artefacts (`.aux`, a pre-built `.bbl`, an
    absolute `\\input` path) left in the author's own directory.
    """

    if build_dir.exists():
        shutil.rmtree(build_dir)
    # `symlinks=True`: a checked-out `resources/code/` third-party repo can
    # contain symlinks pointing outside itself (e.g. to the original author's
    # own machine), which are never dereferenced at LaTeX-compile time and
    # would otherwise crash a dead-target copy with `shutil.Error` — copy the
    # link itself, not its target.
    shutil.copytree(
        source_root, build_dir, symlinks=True, ignore=shutil.ignore_patterns(".git")
    )

    texmf = build_dir / "texmf"
    stage_bundled_styles([build_dir / tex_name], texmf)

    env = dict(os.environ)
    env["TEXINPUTS"] = f"{texmf}//:"
    env["BSTINPUTS"] = f"{texmf}//:"
    env["BIBINPUTS"] = f"{texmf}//:"
    # `openout_any=p` is TeX Live's default; make the no-write-outside-tree and
    # no-shell-escape posture explicit rather than inherited from the host.
    env["openout_any"] = "p"
    env["openin_any"] = "a"
    env["max_print_line"] = "1000"

    stem = Path(tex_name).stem
    commands: list[tuple[str, ...]] = [
        (*_PDFLATEX, tex_name),
        (*_PDFLATEX, tex_name),
        ("bibtex", stem),
        (*_PDFLATEX, tex_name),
        (*_PDFLATEX, tex_name),
    ]
    for command in commands:
        try:
            result = subprocess.run(
                command,
                cwd=build_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            return CompileResult(
                ok=False,
                tex_name=tex_name,
                failed_command=command,
                log_excerpt=f"{command[0]} is not installed on this machine",
            )
        except subprocess.TimeoutExpired:
            return CompileResult(
                ok=False,
                tex_name=tex_name,
                failed_command=command,
                log_excerpt=f"timed out after {timeout}s",
            )
        if command[0] == "bibtex":
            continue
        if result.returncode != 0:
            return CompileResult(
                ok=False,
                tex_name=tex_name,
                failed_command=command,
                log_excerpt=_error_excerpt(build_dir / f"{stem}.log", result.stdout),
            )

    pdf = build_dir / f"{stem}.pdf"
    if not pdf.is_file() or pdf.stat().st_size == 0:
        return CompileResult(
            ok=False,
            tex_name=tex_name,
            failed_command=commands[-1],
            log_excerpt=f"{stem}.pdf missing or empty after a successful compile",
        )
    return CompileResult(ok=True, tex_name=tex_name)


def _error_excerpt(log_path: Path, stdout: str, limit: int = 2500) -> str:
    """Pull the TeX error lines out of a log, falling back to raw stdout.

    The whole point of feeding this back to the construction agent is that it
    can act on it, so prefer the `! ...` / `l.NN ...` lines over 40KB of
    package chatter.
    """

    text = ""
    if log_path.is_file():
        text = log_path.read_text(encoding="utf-8", errors="replace")
    errors = _TEX_ERROR_RE.findall(text)
    if errors:
        return "\n".join(errors)[-limit:]
    return (text or stdout)[-limit:]
