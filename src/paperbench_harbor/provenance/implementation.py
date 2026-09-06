"""Identify local implementation bytes without hashing credentials or run artifacts."""

import hashlib
import json
import re
import subprocess
from pathlib import Path


def implementation_provenance(root: Path | None = None) -> dict:
    root = root or Path.cwd()

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    base = git("rev-parse", "HEAD")
    scope = ("src", "install.sh", "packaging", "docker", "pyproject.toml", "uv.lock", "Makefile")
    tracked = set(git("ls-files", "-z", "--", *scope).split("\0"))
    # Only new executable source is eligible from untracked files, never auth JSON.
    untracked = {name for name in git("ls-files", "-z", "--others", "--exclude-standard", "--", *scope).split("\0")
                 if Path(name).suffix in (".py", ".sh", ".j2")}
    entries = {}
    for name in sorted(tracked | untracked):
        path = Path(name)
        if not name or any(part.startswith(".") or part.lower() in ("logs", "runs", "jobs", "node_modules", "__pycache__") for part in path.parts):
            continue
        if re.search(r"(?:auth|credential|secret|token|api[-_]?key)", path.name, re.IGNORECASE):
            continue
        if path.suffix not in (".py", ".sh", ".j2", ".md", ".json", ".yaml", ".yml", ".toml", ".lock", ".tex", ".sty", ".bst", ".cls", ".bib", ".txt", ".pdf", ".png", ".eps") and path.name not in ("Dockerfile", "Makefile"):
            continue
        absolute = root / path
        if any(p.is_symlink() for p in (absolute, *absolute.parents)):
            raise ValueError(f"linked implementation input: {name}")
        entries[name] = hashlib.sha256(absolute.read_bytes()).hexdigest() if absolute.is_file() else "deleted"
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    dirty = bool(git("status", "--porcelain", "--untracked-files=normal"))
    return {"base_commit": base, "implementation_sha256": digest, "dirty": dirty,
            "scope": "papersmith-implementation-v1",
            "revision": f"local:{base}:{digest}" if dirty else base}


def require_clean_implementation(value: object) -> dict:
    if (not isinstance(value, dict) or value.get("dirty") is not False
        or value.get("scope") != "papersmith-implementation-v1"
        or not re.fullmatch(r"[0-9a-f]{40}", str(value.get("base_commit", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("implementation_sha256", "")))
        or value.get("revision") != value["base_commit"]):
        raise ValueError("release requires recorded clean, pinned implementation provenance; dirty or unrecorded local output is not releasable")
    return value
