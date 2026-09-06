"""Public installed CLI; JSON stdout is separate from structured stderr events."""

import argparse
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from paperbench_harbor.construction.core.state import atomic_json

from . import acceptance
from .generation import configure_generation_schema
from .identity import selection_identifier
from .operations import run as run_process
from .product import (
    GATES,
    MODEL,
    ORDER,
    REVIEW_MODEL,
    import_source_cache,
    import_sources,
    run,
    status,
    validate,
)
from .schema import ScientificContract


def doctor(model, review_model):
    executable = shutil.which("opencode")
    harbor_available = importlib.util.find_spec("harbor") is not None
    models = set()
    discovery = "missing_executable"
    if executable:
        try:
            result = run_process(
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
    acceptance_status = "available"
    try:
        acceptance.check_service()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
        acceptance_status = "unavailable; local requires host Docker/Harbor, spool requires the e2e supervisor"
    dependencies = [
        {"dependency": name, "required_for": phase,
         "state": "available" if available else "missing", "remedy": "none" if available else remedy}
        for name, phase, available, remedy in [
            ("opencode", "construction and all reviews", bool(executable), "Install OpenCode and configure the selected provider externally"),
            ("harbor", "conversion and gate3", harbor_available, "Use the product installer with Harbor 0.22.0"),
            *[(n, "source inspection" if n in {"pdfinfo", "pdftotext"} else "template and oracle compilation", bool(shutil.which(n)), "Install Poppler or TeX Live through the product installer") for n in ("pdfinfo", "pdftotext", "pdflatex", "bibtex")],
        ]
    ]
    idle = acceptance.backend() == "spool" and not Path("/acceptance-receipts/heartbeat.json").is_file()
    dependencies.append({"dependency": "acceptance worker", "required_for": "active gate3 execution",
                         "state": "idle" if idle else acceptance_status,
                         "remedy": "Launch run/resume through the matching supervisor" if idle else "none" if acceptance_status == "available" else "Restore the matching supervisor package and Docker/Harbor service"})
    dependencies.extend({"dependency": name, "required_for": "construction or scientific review",
                         "state": "discovered" if available else discovery,
                         "remedy": "Authentication remains unverified" if available else "Configure this exact OpenCode model/provider externally"}
                        for name, available in sorted(configured.items()))
    return {
        "ok": bool(executable)
        and all(configured.values())
        and all(shutil.which(name) for name in ("pdftotext", "pdfinfo", "pdflatex", "bibtex"))
        and harbor_available and (acceptance_status == "available" or idle),
        "dependencies": dependencies,
        "acceptance_backend": acceptance.backend(),
        "runtime_acceptance": acceptance_status,
        "required": {
            "python": sys.version.split()[0],
            "opencode": bool(executable),
            "pdftotext": bool(shutil.which("pdftotext")),
            "pdfinfo": bool(shutil.which("pdfinfo")),
            "pdflatex": bool(shutil.which("pdflatex")),
            "bibtex": bool(shutil.which("bibtex")),
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


class UsageParser(argparse.ArgumentParser):
    def error(self, message):
        if "--json" in sys.argv:
            print(json.dumps({"ok": False, "classification": "usage", "detail": message,
                              "remedy": "papersmith --help"}))
            raise SystemExit(2)
        super().error(message)


def main():
    parser = UsageParser(
        prog="papersmith", description="Create reviewed Harbor scientific writing tasks."
    )
    parser.add_argument("--version", action="version", version="PaperSmith 0.2.0")
    commands = parser.add_subparsers(dest="command", required=True)
    worker = commands.add_parser("acceptance-worker", help="Trusted host supervisor for Docker E2E")
    worker.add_argument("--container", required=True)
    worker.add_argument("--state", type=Path, required=True)
    worker.add_argument("--invocation", type=Path, required=True)
    worker.add_argument("--detach", action="store_true", help="Launch a nohup host supervisor; return PID/log/state immediately")
    worker.add_argument("controller", nargs=argparse.REMAINDER)
    identity_command = commands.add_parser("identity", help="Stable installed content identity and separate acceptance protocol")
    identity_command.add_argument("--json", action="store_true")
    worker_status = commands.add_parser("acceptance-status", help="Quick supervisor/request lifecycle snapshot without artifact hashing")
    worker_status.add_argument("--state", type=Path, required=True)
    worker_status.add_argument("--json", action="store_true")
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
            sub.add_argument("--task-kind", choices=("full_manuscript", "summary"), default="full_manuscript")
            sub.add_argument("--identifiers", choices=("identified", "anonymized"), default="identified")
            sub.add_argument("--selection", choices=("discovery", "fixed"), default="discovery")
            sub.add_argument("--paper", action="append", default=[], help="Exact DOI/arXiv/canonical URL; repeat for fixed selection")
            sub.add_argument(
                "--source-cache", type=Path,
                help="Prior PaperSmith workspace; copy hash-verified downloaded inputs, never approvals, into this new run",
            )
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
                "--describe-request", "--describe",
                action="store_true",
                help="Print resolved request, no calls or workspace writes",
            )
        elif command != "doctor":
            sub.add_argument("workspace", type=Path)
            if command == "resume":
                sub.add_argument("--count", type=int, help="Explicitly extend the admitted task target; preserve prior scope and successes")
    args = parser.parse_args()
    code = 0
    workspace = getattr(args, "output", getattr(args, "workspace", None))
    try:
        if args.command == "identity":
            print(json.dumps({"installation_identity": acceptance.installation_identity(),
                              "acceptance_protocol": acceptance.protocol(), "version": "0.2.0"}))
            return 0
        if args.command == "acceptance-status":
            state_path = args.state.expanduser().resolve()
            heartbeat = state_path / "heartbeat.json"
            current = state_path / "current-request.json"
            print(json.dumps({"state": str(state_path), "verification": "snapshot_only",
                              "heartbeat": json.loads(heartbeat.read_text()) if heartbeat.is_file() else None,
                              "request": json.loads(current.read_text()) if current.is_file() else None}))
            return 0
        if args.command == "acceptance-worker":
            command = args.controller
            if command[:1] == ["--"]:
                command = command[1:]
            if args.detach:
                print(json.dumps(acceptance.launch(args.container, args.state, args.invocation, command)))
                return 0
            return acceptance.worker(args.container, args.state, args.invocation, command)
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
            papers = [selection_identifier(p) for p in args.paper]
            if any(not p for p in papers):
                raise ValueError("each --paper must be a canonical DOI/arXiv/HTTPS identity")
            contract = ScientificContract(
                task_kind=args.task_kind, identifiers=args.identifiers, selection=args.selection,
                papers=papers, replacement="block" if args.selection == "fixed" else "discover",
                objective=("Write a deliberately selected scientific summary, retaining accurate evidence and limitations."
                           if args.task_kind == "summary" else ScientificContract().objective),
            )
            if contract.selection == "fixed" and args.count > len(papers):
                raise ValueError("count cannot exceed the fixed canonical allowlist; use --count 1 then resume --count N")
            request = {
                "contract": contract.model_dump(),
                "prompt": args.prompt,
                "count": args.count,
                "model": args.model,
                "review_model": args.review_model,
                "phase_timeout_seconds": None,
                "source": str(args.source.expanduser().resolve()) if args.source else None,
                "source_cache": str(args.source_cache.expanduser().resolve()) if args.source_cache else None,
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
                    "acceptance_backend": acceptance.backend(),
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
                if args.source_cache:
                    import_source_cache(args.source_cache.expanduser().resolve(), root / "source-cache")
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
                result = run(root, args.count)
            else:
                result = status(root) if args.command == "status" else validate(root)
                if args.command == "validate" and not result["task_ready"]:
                    code = 1
    except KeyboardInterrupt:
        result, code = (
            {"ok": False, "status": "interrupted", "classification": "interrupted", "remedy": "papersmith resume " + shlex.quote(str(workspace))},
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
                "classification": getattr(error, "classification", "content" if isinstance(error, ValueError) else "deps"),
                "remedy": "papersmith resume " + shlex.quote(str(workspace)) if workspace else "papersmith doctor",
            },
            1,
        )
        if isinstance(error, ValueError):
            result["detail"] = str(error)
    if getattr(args, "json", False):
        print(json.dumps(result, sort_keys=True))
    elif args.command == "doctor":
        print("Dependency | Required For | State | Remedy")
        for row in result.get("dependencies", []):
            print(" | ".join(str(row[k]) for k in ("dependency", "required_for", "state", "remedy")))
        print("Authentication: unverified without a model call")
    elif "request" in result:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"PaperSmith: {result.get('status', 'ready' if result.get('task_ready') else 'blocked')}")
        if "target_count" in result:
            print(f"Tasks: {result.get('task_ready_count', 0)}/{result['target_count']} ({result.get('verification', 'authoritative validation')})")
        for key in ("detail", "blocked_reason", "checkpoint", "remedy"):
            if result.get(key):
                print(f"{key}: {result[key]}")
    return code


if __name__ == "__main__":
    sys.exit(main())
