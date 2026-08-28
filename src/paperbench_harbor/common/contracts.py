from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SubmissionContract:
    """Canonical file contract shared by both Harbor benchmark families."""

    root: Path = Path("/workspace/submission")
    main_tex: str = "main.tex"
    bibliography: str = "references.bib"
    figures_dir: str = "figures"
    final_pdf: str = "final.pdf"

    @property
    def required_relative_paths(self) -> tuple[str, ...]:
        return (self.main_tex, self.bibliography)
