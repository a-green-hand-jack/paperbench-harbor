#!/usr/bin/env bash
set -euo pipefail

REPO_NAME="paperbench-harbor"
OWNER="${GITHUB_OWNER:-a-green-hand-jack}"
VISIBILITY="${1:-private}"
DESCRIPTION="Harbor adapters and evaluation infrastructure for PaperWritingBench and PaperWrite-Bench"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) is required: https://cli.github.com/" >&2
  exit 1
fi

gh auth status >/dev/null

case "$VISIBILITY" in
  private|public|internal) ;;
  *)
    echo "Usage: $0 [private|public|internal]" >&2
    exit 2
    ;;
esac

if gh repo view "$OWNER/$REPO_NAME" >/dev/null 2>&1; then
  echo "Repository $OWNER/$REPO_NAME already exists; pushing the current main branch."
  if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "https://github.com/$OWNER/$REPO_NAME.git"
  fi
  git push -u origin main
else
  gh repo create "$OWNER/$REPO_NAME" \
    "--$VISIBILITY" \
    --description "$DESCRIPTION" \
    --source . \
    --remote origin \
    --push
fi
