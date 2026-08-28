#!/usr/bin/env bash
set -euo pipefail

SUBMISSION="${1:-/workspace/submission}"
TEST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "$TEST_ROOT/smoke_grader.py" "$SUBMISSION"
