#!/usr/bin/env python3
"""Run the PaperOrchestra Semantic Scholar enrichment sidecar."""

from __future__ import annotations

import argparse

from paperbench_harbor.sidecar.server import serve


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
