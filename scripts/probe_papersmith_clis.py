"""Bounded real CLI request; emit only allowlisted evidence, never raw diagnostics."""

import argparse
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cli", choices=("opencode", "codex"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = "PAPERSMITH_CONTAINER_OK"
    prompt = f"Do not use tools or read files. Reply with exactly {expected} and nothing else."
    if args.cli == "opencode":
        command = ["opencode", "run", "--format", "json", "--model", args.model,
                   "--variant", "medium", prompt]
    else:
        command = ["codex", "exec", "--ephemeral", "--skip-git-repo-check",
                   "--sandbox", "read-only", "--json", "--model", args.model,
                   "-c", 'model_reasoning_effort="medium"', prompt]
    texts = []
    categories = []
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout, check=False)
        code = result.returncode
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "text":
                texts.append(event.get("part", {}).get("text", ""))
            if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message":
                texts.append(event["item"].get("text", ""))
        raw = (result.stdout + result.stderr).lower()
        for label, markers in {
            "auth": ("unauthorized", "authentication", "refresh token", "401"),
            "quota": ("usage limit", "rate limit", "429"),
            "readonly": ("read-only file system", "erofs"),
            "missing_path": ("enoent", "no such file", "cannot find module"),
            "config": ("configinvalid", "error loading config", "failed to load configuration"),
            "network": ("connection refused", "fetch failed", "unable to connect"),
        }.items():
            if any(marker in raw for marker in markers):
                categories.append(label)
    except subprocess.TimeoutExpired:
        code, categories = 124, ["timeout"]
    ok = code == 0 and "".join(texts).strip() == expected
    evidence = {"cli": args.cli, "model": args.model, "exit_code": code,
                "exact_response": ok, "diagnostic_categories": categories}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
