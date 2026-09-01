#!/usr/bin/env python3
"""Compatibility entry point for the sanitized trial exporter."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from paperbench_harbor.trials.export import TrialExportConfig, TrialExportError, export_trial, main

__all__ = ["TrialExportConfig", "TrialExportError", "export_trial"]


if __name__ == "__main__":
    main()
