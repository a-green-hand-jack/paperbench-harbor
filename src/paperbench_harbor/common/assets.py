"""Bundled assets in wheels, with the existing editable-checkout layout retained."""

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
PACKAGING = PACKAGE / "packaging"
if not PACKAGING.is_dir():
    checkout = PACKAGE.parent.parent
    if (checkout / "pyproject.toml").is_file():
        PACKAGING = checkout / "packaging"
