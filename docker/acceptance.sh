#!/bin/sh
# Trusted HOST control only. Never mount the Docker socket in PaperSmith.
set -eu
if [ "$#" -ne 2 ]; then
    printf '%s\n' 'Usage: HARBOR_BIN=/installed/harbor sh docker/acceptance.sh EXPORTED_TASKS NEW_JOBS_DIR' >&2
    exit 2
fi
harbor=${HARBOR_BIN:-harbor}
[ "$("$harbor" --version)" = 0.22.0 ] || {
    printf '%s\n' 'Harbor 0.22.0 is required; select its installed executable with HARBOR_BIN.' >&2
    exit 2
}
tasks=$(realpath -e -- "$1")
jobs=$(realpath -m -- "$2")
[ ! -e "$jobs" ] || { printf '%s\n' 'Refusing to overwrite or mix existing acceptance jobs.' >&2; exit 2; }
[ -d "$(dirname -- "$jobs")" ] || { printf '%s\n' 'Jobs parent directory must already exist.' >&2; exit 2; }
count=0
for task in "$tasks"/candidate-*; do
    [ -d "$task" ] || continue
    for file in task.toml solution/solve.sh solution/manuscript/main.tex solution/manuscript/references.bib tests/private/ground_truth/paper.pdf; do
        [ -f "$task/$file" ] || { printf 'Missing %s/%s\n' "$task" "$file" >&2; exit 2; }
    done
    count=$((count + 1))
done
[ "$count" -eq 5 ] || { printf 'Expected exactly 5 exported tasks, found %s\n' "$count" >&2; exit 2; }
docker info >/dev/null
mkdir "$jobs"
failed=0
for task in "$tasks"/candidate-*; do
    [ -d "$task" ] || continue
    for agent in oracle nop; do
        "$harbor" run --path "$task" --agent "$agent" --env docker \
            --n-attempts 1 --n-concurrent 1 --max-retries 0 \
            --jobs-dir "$jobs" --job-name "$(basename -- "$task")-$agent" --yes || failed=1
    done
done
python3 - "$tasks" "$jobs" "$failed" <<'PY'
import json
import sys
from pathlib import Path

tasks, jobs = map(Path, sys.argv[1:3])
cli_failed = sys.argv[3] != "0"
summary = []
for task in sorted(tasks.glob("candidate-*")):
    if not task.is_dir():
        continue
    for agent, expected in (("oracle", 1), ("nop", 0)):
        job = jobs / f"{task.name}-{agent}"
        results = list(job.glob("*/result.json"))
        errors = []
        reward = None
        if len(results) != 1:
            errors.append("expected exactly one completed trial")
        else:
            result = json.loads(results[0].read_text())
            trial = results[0].parent
            reward = (result.get("verifier_result") or {}).get("rewards", {}).get("reward")
            if result.get("exception_info") or not result.get("finished_at"):
                errors.append("trial exception or incomplete execution")
            if result.get("task_name") != task.name or result.get("agent_info", {}).get("name") != agent:
                errors.append("trial identity mismatch")
            if reward != expected:
                errors.append(f"expected reward {expected}, observed {reward}")
            exit_code = trial / "agent/exit-code.txt"
            if exit_code.is_file() and exit_code.read_text().strip() != "0":
                errors.append("oracle solve command failed")
            ctrf = trial / "verifier/ctrf.json"
            if not ctrf.is_file():
                errors.append("missing evidence that the generated verifier executed")
            else:
                tests = json.loads(ctrf.read_text()).get("results", {}).get("tests", [])
                if not tests or (agent == "oracle" and any(t.get("status") != "passed" for t in tests)):
                    errors.append("missing or unsuccessful oracle verifier tests")
                if agent == "nop" and not any(t.get("status") == "failed" for t in tests):
                    errors.append("nop did not fail the submission contract")
        summary.append({"task": task.name, "agent": agent, "reward": reward, "errors": errors})
report = {"accepted": not cli_failed and len(summary) == 10 and not any(r["errors"] for r in summary), "cli_failed": cli_failed, "trials": summary}
(jobs / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
sys.exit(0 if report["accepted"] else 1)
PY
[ "$failed" -eq 0 ]
