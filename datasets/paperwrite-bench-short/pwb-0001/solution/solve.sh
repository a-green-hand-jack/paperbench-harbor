#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUBMISSION="${1:-/workspace/submission}"
rm -rf "$SUBMISSION"
mkdir -p "$SUBMISSION"
cp "$TASK_DIR/solution/oracle/main.tex" "$SUBMISSION/main.tex"
cp "$TASK_DIR/solution/oracle/references.bib" "$SUBMISSION/references.bib"
# The verifier recompiles main.tex; this PDF is only a convenience artifact.
if command -v pdflatex >/dev/null 2>&1 && command -v bibtex >/dev/null 2>&1; then
  (
    cd "$SUBMISSION"
    pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null
    bibtex main >/dev/null
    pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null
    pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null
  )
  mv "$SUBMISSION/main.pdf" "$SUBMISSION/final.pdf"
fi
