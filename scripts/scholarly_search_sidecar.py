#!/usr/bin/env python3
"""Serve a reproducible JSONL scholarly-search index."""

from __future__ import annotations

import argparse
from pathlib import Path

from paperbench_harbor.common.scholarly_search import serve


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.index, args.host, args.port)


if __name__ == "__main__":
    main()
