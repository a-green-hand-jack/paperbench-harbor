"""Public installed CLI; JSON stdout is separate from structured stderr events."""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from paperbench_harbor.construction.core.state import atomic_json

from .generation import configure_generation_schema
from .product import GATES, MODEL, ORDER, REVIEW_MODEL, import_sources, run, validate


def doctor(model, review_model):
    executable = shutil.which("opencode")
    harbor_available = importlib.util.find_spec("harbor") is not None
    models = set()
    discovery = "missing_executable"
    if executable:
        try:
            result = subprocess.run(
                [executable, "models"], capture_output=True, text=True, timeout=120, check=False
            )
            if result.returncode == 0:
                models = set(result.stdout.split())
                discovery = "available"
            else:
                discovery = "configuration_or_provider_unavailable"
        except subprocess.TimeoutExpired:
            discovery = "dependency_probe_timeout"
    configured = {m: m in models for m in {model, review_model}}
    return {
        "ok": bool(executable)
        and all(configured.values())
        and bool(shutil.which("pdftotext"))
        and harbor_available,
        "required": {
            "python": sys.version.split()[0],
            "opencode": bool(executable),
            "pdftotext": bool(shutil.which("pdftotext")),
            "harbor": harbor_available,
        },
        "models": configured,
        "provider_discovery": discovery,
        "authentication": "unverified_without_model_call",
        "authentication_note": "Model discovery is not proof of authentication. Configure OpenCode provider credentials externally; create reports real-call failures without printing provider diagnostics.",
        "optional": {name: bool(shutil.which(name)) for name in ("docker", "git", "hf")},
        "installed_package": str(Path(__file__).resolve().parent),
        "model_calls": 0,
    }


def main():
    parser = argparse.ArgumentParser(
        prog="papersmith", description="Create reviewed Harbor scientific writing tasks."
    )
    parser.add_argument("--version", action="version", version="PaperSmith 0.2.0")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("create", "status", "resume", "validate", "doctor"):
        sub = commands.add_parser(command)
        sub.add_argument("--json", action="store_true", help="Machine-readable result on stdout")
        sub.add_argument(
            "--headless", action="store_true", help="Noninteractive operation (also the default)"
        )
        if command in {"doctor", "create"}:
            sub.add_argument("--model", default=MODEL)
            sub.add_argument(
                "--review-model", default=REVIEW_MODEL, help="All three independent review gates"
            )
        if command == "create":
            sub.add_argument(
                "--source",
                type=Path,
                help="Scoped local scientific source file/directory to import privately",
            )
            sub.add_argument(
                "prompt", help="Any scientific topic, paper URL/DOI, or selection request"
            )
            sub.add_argument("--output", "-o", type=Path, required=True)
            sub.add_argument(
                "--count",
                type=int,
                default=1,
                help="Admitted delivered task count, not candidate count",
            )
            sub.add_argument(
                "--describe-request",
                action="store_true",
                help="Print resolved request, no calls or workspace writes",
            )
        elif command != "doctor":
            sub.add_argument("workspace", type=Path)
    args = parser.parse_args()
    code = 0
    try:
        workspace = getattr(args, "output", getattr(args, "workspace", None))
        configure_generation_schema(workspace.expanduser().resolve() if workspace else None)
        if args.command == "doctor":
            result = doctor(args.model, args.review_model)
            code = 0 if result["ok"] else 1
        elif args.command == "create":
            if args.count < 1 or not args.prompt.strip():
                raise ValueError("count must be positive and request nonempty")
            for model in (args.model, args.review_model):
                if "/" not in model or any(c.isspace() for c in model):
                    raise ValueError("models must be provider/model identifiers")
            root = args.output.expanduser().resolve()
            request = {
                "prompt": args.prompt,
                "count": args.count,
                "model": args.model,
                "review_model": args.review_model,
                "phase_timeout_seconds": None,
                "source": str(args.source.expanduser().resolve()) if args.source else None,
                "imported": str(root / "imported"),
            }
            if args.describe_request:
                result = {
                    "request": request,
                    "workspace": str(root),
                    "phases": ORDER,
                    "review_dimensions": GATES,
                    "model_calls": 0,
                    "task_ready": False,
                }
            else:
                if root.exists() and any(root.iterdir()):
                    raise ValueError("output is nonempty; use resume for existing workspaces")
                if any((p / ".git").exists() for p in (root, *root.parents)):
                    raise ValueError(
                        "create requires a dedicated workspace outside a source checkout"
                    )
                root.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(root, 0o700)
                if args.source:
                    import_sources(args.source, root / "imported")
                atomic_json(
                    root / "run.json",
                    {
                        "schema_version": 1,
                        "request": request,
                        "status": "created",
                        "candidates": [],
                    },
                )
                result = run(root)
        else:
            root = args.workspace.expanduser().resolve()
            if args.command == "resume":
                result = run(root)
            else:
                result = validate(root)
                if args.command == "validate" and not result["task_ready"]:
                    code = 1
    except KeyboardInterrupt:
        result, code = (
            {"ok": False, "status": "interrupted", "remedy": "papersmith resume <workspace>"},
            130,
        )
    except (
        ValueError,
        OSError,
        RuntimeError,
        KeyError,
        TypeError,
        IndexError,
        subprocess.SubprocessError,
    ) as error:
        # Never forward arbitrary provider/network messages or configuration contents.
        result, code = (
            {
                "ok": False,
                "error": type(error).__name__,
                "remedy": "Check workspace/checkpoints and papersmith doctor; then resume.",
            },
            1,
        )
        if isinstance(error, ValueError):
            result["detail"] = str(error)
    print(json.dumps(result, indent=None if args.json else 2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
