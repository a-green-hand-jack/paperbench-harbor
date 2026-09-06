"""Trusted Harbor execution. The model has neither command tools nor receipt writes."""

import ast
import fcntl
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import threading
import time
import tomllib
from pathlib import Path
from uuid import uuid4

from paperbench_harbor.construction.core.state import atomic_json, fingerprint

from .integrity import artifact_hash as digest
from .integrity import contained

BACKEND = "harbor-0.22.0-oracle-nop-v1"


class AcceptanceBlocked(RuntimeError):
    """Runtime failure is infrastructure/acceptance evidence, not a model rejection."""


def protocol():
    templates = Path(__file__).resolve().parents[1] / "common/templates"
    sources = {p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    return fingerprint([BACKEND, sources, digest(templates)])


def backend():
    return os.environ.get("PAPERSMITH_ACCEPTANCE_BACKEND", "local")


def check_service():
    if backend() == "spool":
        heartbeat = Path("/acceptance-receipts/heartbeat.json")
        if not heartbeat.is_file() or time.time() - heartbeat.stat().st_mtime > 30:
            raise AcceptanceBlocked("trusted acceptance worker unavailable; use docker/e2e.sh")
        service = json.loads(heartbeat.read_text())
        if service.get("protocol") != protocol():
            raise AcceptanceBlocked("controller and host worker packages differ; rebuild/install together")
        return service
    elif backend() == "local":
        if not shutil.which("harbor") or not shutil.which("docker"):
            raise AcceptanceBlocked("local acceptance requires Harbor 0.22.0 and host Docker")
        if subprocess.check_output(["harbor", "--version"], text=True).strip() != "0.22.0":
            raise AcceptanceBlocked("Harbor 0.22.0 required")
        subprocess.run(["docker", "info"], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    else:
        raise AcceptanceBlocked("unknown acceptance backend")


def trial_evidence(state, record, task_name, agent, task_sha256):
    trial = contained(state, state / record["trial"])
    if digest(trial) != record["evidence_sha256"]:
        raise AcceptanceBlocked("Harbor evidence hash mismatch")
    result = json.loads((trial / "result.json").read_text())
    snapshot = contained(state, state / record["snapshot"])
    if (digest(snapshot) != task_sha256
            or result.get("task_id") != {"path": record["executed_path"]}
            or result.get("config", {}).get("task", {}).get("path") != record["executed_path"]
            or result.get("config", {}).get("environment", {}).get("type") != "docker"
            or result.get("config", {}).get("agent", {}).get("name") != agent
            or result.get("verifier_environment_mode") != "separate"):
        raise AcceptanceBlocked("Harbor trial is not bound to the executed task/environment")
    if (result.get("exception_info") or not result.get("finished_at")
            or result.get("task_name") != task_name
            or result.get("agent_info", {}).get("name") != agent):
        raise AcceptanceBlocked("Harbor exception, unfinished trial or identity mismatch")
    reward = (result.get("verifier_result") or {}).get("rewards", {}).get("reward")
    expected = 1 if agent == "oracle" else 0
    if type(reward) not in (int, float) or reward != expected:
        raise AcceptanceBlocked(f"{agent} requires reward {expected}")
    tests = json.loads((trial / "verifier/ctrf.json").read_text()).get("results", {}).get("tests", [])
    expected_tests = {
        node.name for node in ast.parse((snapshot / "tests/test_state.py").read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }
    observed_tests = [t.get("name", "").rsplit("::", 1)[-1] for t in tests]
    if (not expected_tests or set(observed_tests) != expected_tests
            or len(observed_tests) != len(expected_tests)
            or not (result.get("verifier") or {}).get("finished_at")):
        raise AcceptanceBlocked("generated verifier test collection/completion mismatch")
    if not tests or any(t.get("status") not in {"passed", "failed"} for t in tests):
        raise AcceptanceBlocked("verifier did not execute valid tests")
    if agent == "oracle":
        exit_code = trial / "agent/exit-code.txt"
        # Harbor 0.22.0 writes exit-code.txt only on a nonzero oracle exit.
        if (exit_code.is_file() and exit_code.read_text().strip() != "0") or not (
            (trial / "agent/oracle.txt").is_file()
            and (result.get("agent_execution") or {}).get("finished_at")
        ):
            raise AcceptanceBlocked("oracle solve did not complete successfully")
        if any(t["status"] != "passed" for t in tests):
            raise AcceptanceBlocked("oracle verifier tests failed")
    elif not any(t["status"] == "failed" for t in tests):
        raise AcceptanceBlocked("nop did not fail the submission contract")
    if (trial / "verifier/reward.txt").read_text().strip() != str(expected):
        raise AcceptanceBlocked("verifier reward artifact mismatch")
    if record.get("returncode") != 0:
        raise AcceptanceBlocked("Harbor CLI failed (not an expected nop test failure)")


def check_receipt(state, receipt, request):
    if receipt.get("request") != request or receipt.get("accepted") is not True:
        raise AcceptanceBlocked(f"missing, failed or mismatched acceptance receipt: {state / 'receipts' / (request['id'] + '.json')}")
    if request["protocol"] != protocol() or set(receipt.get("trials", {})) != {"oracle", "nop"}:
        raise AcceptanceBlocked("acceptance protocol or subjobs mismatch")
    for agent, record in receipt["trials"].items():
        trial_evidence(state, record, request["task_name"], agent, request["task_sha256"])
    snapshot = contained(state, state / receipt["snapshot"])
    if digest(snapshot) != request["task_sha256"]:
        raise AcceptanceBlocked("accepted snapshot changed")


def execute(state, snapshot, request, heartbeat=None):
    """Only fixed Harbor argv; task-provided paths/commands never run on the host."""
    if request["protocol"] != protocol() or not re.fullmatch(r"candidate-[0-9]{4,}", request["task_name"]):
        raise AcceptanceBlocked("invalid acceptance request")
    if digest(snapshot) != request["task_sha256"]:
        raise AcceptanceBlocked("snapshot hash mismatch")
    # Reject alternative compose/config entry points and unbounded task budgets.
    config = tomllib.loads((snapshot / "task.toml").read_text())
    expected = {
        "agent": {"timeout_sec": 3600.0, "network_mode": "no-network"},
        "verifier": {"environment_mode": "separate", "timeout_sec": 900.0,
                     "network_mode": "no-network"},
        "environment": {"build_timeout_sec": 2400.0, "cpus": 2, "memory_mb": 8192,
                        "storage_mb": 20480, "gpus": 0, "network_mode": "public"},
    }
    if any(config.get(k) != v for k, v in expected.items()) or set(config) != {
        "schema_version", "artifacts", "metadata", "agent", "verifier", "environment"
    } or config["artifacts"] != ["/workspace/submission"]:
        raise AcceptanceBlocked("task runtime configuration differs from shipped contract")
    if any((snapshot / directory / name).exists()
           for directory in ("environment", "tests")
           for name in ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml")):
        raise AcceptanceBlocked("custom compose files are not accepted")
    for p in snapshot.rglob("*"):
        if p.is_symlink() or not (p.is_file() or p.is_dir()):
            raise AcceptanceBlocked("nonregular snapshot entry")
        p.chmod(0o500 if p.is_dir() else 0o400)
    snapshot.chmod(0o500)
    cache = state / "jobs" / request["task_sha256"] / request["task_name"]
    cache.mkdir(parents=True, exist_ok=True)
    atomic_json(state / "requests" / (request["id"] + ".json"), request)
    receipt = {"request": request, "snapshot": str(snapshot.relative_to(state)),
               "accepted": False, "trials": {}}
    for agent in ("oracle", "nop"):
        saved = cache / f"{agent}.json"
        if saved.is_file():
            record = json.loads(saved.read_text())
            trial_evidence(state, record, request["task_name"], agent, request["task_sha256"])
        else:
            name = agent + "-" + uuid4().hex
            command = ["harbor", "run", "--path", str(snapshot), "--agent", agent,
                       "--env", "docker", "--n-attempts", "1", "--n-concurrent", "1",
                       "--max-retries", "0", "--jobs-dir", str(cache), "--job-name", name, "--yes"]
            with (cache / f"{name}.log").open("w") as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True)
                try:
                    while process.poll() is None:
                        if heartbeat:
                            heartbeat()
                        time.sleep(1)
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGINT)
                        try:
                            process.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGTERM)
                            try:
                                process.wait(timeout=30)
                            except subprocess.TimeoutExpired:
                                os.killpg(process.pid, signal.SIGKILL)
                                process.wait()
            results = list((cache / name).glob("*/result.json"))
            if len(results) != 1:
                raise AcceptanceBlocked(f"{agent}: expected exactly one completed trial; inspect {cache / name}")
            trial = results[0].parent
            record = {"trial": str(trial.relative_to(state)), "returncode": process.returncode,
                      "evidence_sha256": digest(trial), "executed_path": str(snapshot),
                      "snapshot": str(snapshot.relative_to(state))}
            trial_evidence(state, record, request["task_name"], agent, request["task_sha256"])
            if digest(snapshot) != request["task_sha256"]:
                raise AcceptanceBlocked("task changed during Harbor execution")
            atomic_json(saved, record)
        receipt["trials"][agent] = record
    receipt["accepted"] = True
    check_receipt(state, receipt, request)
    return receipt


def accept(root, candidate, task, attempt):
    service = check_service()
    request = {"id": uuid4().hex, "protocol": protocol(), "task_name": candidate["id"],
               "task_sha256": digest(task), "identity": candidate["identity"],
               "worker_id": service["worker_id"] if service else None}
    atomic_json(attempt / "acceptance-request.json", {"backend": backend(), "request": request})
    if backend() == "spool":
        queue, state = Path("/acceptance"), Path("/acceptance-receipts")
        exported = queue / "tasks" / request["id"] / request["task_name"]
        exported.parent.mkdir(parents=True)
        shutil.copytree(task, exported)
        if digest(exported) != request["task_sha256"]:
            raise AcceptanceBlocked("queue snapshot mismatch")
        atomic_json(queue / "request.json", request)
        receipt_path = state / "receipts" / (request["id"] + ".json")
        while not receipt_path.is_file():
            if check_service()["worker_id"] != request["worker_id"]:
                raise AcceptanceBlocked("acceptance worker restarted; resume to resubmit this snapshot")
            time.sleep(1)
        receipt = json.loads(receipt_path.read_text())
    else:
        state = root / ".acceptance"
        snapshot = state / "snapshots" / request["id"] / request["task_name"]
        snapshot.parent.mkdir(parents=True)
        shutil.copytree(task, snapshot)
        try:
            receipt = execute(state, snapshot, request)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
            receipt = {"request": request, "accepted": False,
                       "error": type(error).__name__, "detail": str(error)}
        receipt_path = state / "receipts" / (request["id"] + ".json")
        atomic_json(receipt_path, receipt)
    atomic_json(attempt / "acceptance.json", {
        "backend": backend(), "request": request, "receipt_sha256": digest(receipt_path),
        "receipt": str(receipt_path), "accepted": receipt.get("accepted") is True,
    })
    check_receipt(state, receipt, request)
    if digest(task) != request["task_sha256"]:
        raise AcceptanceBlocked("conversion changed during acceptance")


def verify(root, candidate):
    attempt = Path(candidate["stages"]["gate3"]["path"])
    evidence = json.loads((attempt / "acceptance.json").read_text())
    state = Path("/acceptance-receipts") if evidence["backend"] == "spool" else root / ".acceptance"
    receipt_path = contained(state / "receipts", Path(evidence["receipt"]))
    if digest(receipt_path) != evidence["receipt_sha256"]:
        raise AcceptanceBlocked("trusted receipt hash mismatch")
    request = evidence["request"]
    task = Path(candidate["stages"]["convert"]["path"]) / "task"
    if (request["task_sha256"] != digest(task) or request["task_name"] != candidate["id"]
            or request["identity"] != candidate["identity"]):
        raise AcceptanceBlocked("acceptance is not bound to this conversion/identity")
    check_receipt(state, json.loads(receipt_path.read_text()), request)


def docker_copy(container, path, destination):
    """Extract regular bytes only, never tar links, devices or archive traversal."""
    result = subprocess.run(["docker", "cp", f"{container}:{path}", "-"],
                            capture_output=True, check=True)
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        for member in archive:
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts or not (member.isdir() or member.isfile()):
                raise AcceptanceBlocked("unsafe Docker copy archive")
            target = contained(destination, destination / relative)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    shutil.copyfileobj(archive.extractfile(member), stream)


def validate_controller(container, state, command):
    """Accept only the wrapper's restricted Docker shape; inspect mount metadata only."""
    if os.getuid() == 0 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]+", container):
        raise ValueError("an ordinary host user and valid controller name are required")
    if command[:2] != ["docker", "run"]:
        raise ValueError("worker requires docker run")
    options, mounts, environments = {}, {}, set()
    flags = {"--init", "--read-only", "-i", "-it"}
    values = {"--name", "--user", "--cap-drop", "--security-opt", "--pids-limit",
              "--network", "--tmpfs", "--workdir", "--env", "--mount"}
    index = 2
    while index < len(command) and command[index].startswith("-"):
        option = command[index]
        index += 1
        if option in flags:
            value = True
        elif option in values and index < len(command):
            value = command[index]
            index += 1
        else:
            raise ValueError("unsupported Docker option; privileged, host networking and socket access are forbidden")
        if option == "--mount":
            fields = {}
            for field in value.split(","):
                key, _, item = field.partition("=")
                if key in fields:
                    raise ValueError("duplicate mount field")
                fields[key] = item
            if set(fields) - {"type", "src", "dst", "readonly"} or not {"type", "src", "dst"} <= fields.keys():
                raise ValueError("unsupported mount shape")
            destination = fields["dst"]
            if destination in mounts or not destination.startswith("/") or ".." in Path(destination).parts:
                raise ValueError("duplicate or ambiguous mount destination")
            mounts[destination] = fields
        elif option == "--env":
            if value not in {"PAPERSMITH_ACCEPTANCE_BACKEND=spool", "RUFF_CACHE_DIR=/cache/ruff",
                             "OPENCODE_CONFIG=/opt/opencode.json"} or value in environments:
                raise ValueError("unsupported controller environment override")
            environments.add(value)
        else:
            if option in options:
                raise ValueError("duplicate Docker option")
            options[option] = value
    required = {"--init": True, "--read-only": True, "--name": container,
                "--user": f"{os.getuid()}:{os.getgid()}", "--cap-drop": "ALL",
                "--security-opt": "no-new-privileges", "--pids-limit": "512",
                "--tmpfs": "/tmp:rw,nosuid,nodev,mode=1777", "--workdir": "/runs"}
    if (any(options.get(k) != v for k, v in required.items())
            or options.get("--network") not in {"none", "bridge"}
            or "PAPERSMITH_ACCEPTANCE_BACKEND=spool" not in environments):
        raise ValueError("controller isolation options differ from the shipped wrapper")
    if index >= len(command) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:-]*", command[index]):
        raise ValueError("missing or invalid controller image")
    payload = command[index + 1:]
    bootstrap = 'umask 077; mkdir -p "$HOME/.local/share/opencode" "$HOME/.config/opencode" "$HOME/.codex"; chmod 700 "$HOME"; exec "$@"'
    if len(payload) < 7 or payload[:5] != ["sh", "-ec", bootstrap, "sh", "papersmith"] or payload[5] not in {"create", "resume"}:
        raise ValueError("worker may supervise only the installed PaperSmith create/resume controller")
    home = Path.home()
    broad = {Path(p).resolve() for p in ("/", "/home", "/run", "/var/run", "/var",
                                        "/tmp", "/dev", "/proc", "/sys", str(home),
                                        str(home / ".config"), str(home / ".codex"),
                                        str(home / ".config/opencode"))}
    volume_prefix = None
    for destination in ("/runs", "/state", "/cache", "/acceptance"):
        mount = mounts.get(destination, {})
        source = mount.get("src", "")
        suffix = "-" + destination[1:]
        if (mount.get("type") != "volume" or "readonly" in mount
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", source)
                or not source.endswith(suffix)):
            raise ValueError("only dedicated PaperSmith state volumes are allowed")
        prefix = source[:-len(suffix)]
        if volume_prefix is not None and prefix != volume_prefix:
            raise ValueError("controller volumes must share one prefix")
        volume_prefix = prefix
    for destination, mount in mounts.items():
        if destination in {"/runs", "/state", "/cache", "/acceptance"}:
            continue
        if mount["type"] != "bind" or mount.get("readonly") != "":
            raise ValueError("host binds must be read-only")
        source = Path(mount["src"])
        if not source.is_absolute() or source.resolve() in broad:
            raise ValueError("broad host mount refused")
        if (destination not in {"/acceptance-receipts", "/input", "/opt/opencode.json",
                                "/state/home/.local/share/opencode/auth.json"}
                and (Path(destination).resolve() != source.resolve()
                     or Path(destination).parts[1] in {"bin", "sbin", "usr", "etc", "dev", "proc", "sys", "run", "var", "opt"})):
            raise ValueError("bind destination is not an allowed narrow provider/input path")
        pending, visited = [source], set()
        while pending:
            path = pending.pop()
            try:
                info = path.stat()
            except FileNotFoundError:
                if path == source:
                    raise
                continue  # Atomic receipt/log replacement can remove an intermediate entry.
            if stat.S_ISSOCK(info.st_mode):
                raise ValueError("Unix socket or socket-containing directory mount refused")
            if stat.S_ISDIR(info.st_mode):
                inode = (info.st_dev, info.st_ino)
                if inode not in visited:
                    visited.add(inode)
                    pending.extend(path.iterdir())
    receipt_mount = mounts.get("/acceptance-receipts", {})
    if Path(receipt_mount.get("src", "")).resolve() != state.resolve():
        raise ValueError("trusted receipts must be bound read-only from this worker's state")


def launch(container, state, invocation, command):
    state = state.expanduser().resolve()
    invocation = contained(state / "invocations", invocation.expanduser().absolute())
    validate_controller(container, state, command)
    log_path, pid_path = invocation / "supervisor.log", invocation / "pid.json"
    executable = str(Path(sys.executable).parent / "papersmith")
    with log_path.open("x") as log:
        process = subprocess.Popen(
            ["nohup", executable, "acceptance-worker", "--container", container,
             "--state", str(state), "--invocation", str(invocation), "--", *command],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    result = {"status": "spawned", "pid": process.pid, "pid_path": str(pid_path),
              "log": str(log_path), "state": str(invocation / "supervisor.json"),
              "acceptance_state": str(state), "container": container,
              "note": "Background startup/exit outcome is recorded in state and log; no model wait."}
    atomic_json(pid_path, {"pid": process.pid, "container": container})
    atomic_json(invocation / "launch.json", result)
    return result


def cleanup_controller(container, worker_id, controller):
    """Stop/kill by immutable Docker ID only after verifying our unique owner label."""
    def inspect(reference):
        result = subprocess.run(
            ["docker", "container", "inspect", "--format",
             '{{.Id}} {{index .Config.Labels "io.papersmith.worker"}} {{.State.Running}}', reference],
            capture_output=True, text=True, check=False, timeout=10,
        )
        fields = result.stdout.split()
        if result.returncode or len(fields) != 3 or fields[1] != worker_id or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
            raise AcceptanceBlocked("container ownership unavailable; refusing name-based cleanup")
        return fields[0], fields[2] == "true"

    cleanup = {"retained": True, "status": "pending"}
    try:
        owned_id, running = inspect(container)
        cleanup["container_id"] = owned_id
        if running:
            stop_failed = False
            try:
                result = subprocess.run(["docker", "stop", "--time", "30", owned_id],
                                        check=False, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=45)
                stop_failed = result.returncode != 0
            except subprocess.TimeoutExpired:
                stop_failed = True
            if stop_failed or inspect(owned_id)[1]:
                subprocess.run(["docker", "kill", owned_id], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            _, running = inspect(owned_id)
        cleanup["status"] = "pending" if running else "stopped"
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        cleanup["error"] = type(error).__name__
    finally:
        try:
            controller.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(controller.pid, signal.SIGTERM)
            try:
                controller.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(controller.pid, signal.SIGKILL)
                controller.wait()
    return cleanup


def worker(container, state, invocation, command):
    state = state.expanduser().resolve()
    invocation = contained(state / "invocations", invocation.expanduser().absolute())
    record = {"pid": os.getpid(), "container": container, "status": "starting",
              "started_at": time.time()}
    record_path = invocation / "supervisor.json"
    atomic_json(record_path, record)
    try:
        validate_controller(container, state, command)
        code = serve(container, state, command, record, record_path)
        record.update(status="exited", returncode=code)
        return code
    except BaseException as error:
        record.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                      error=type(error).__name__)
        raise
    finally:
        record["finished_at"] = time.time()
        atomic_json(record_path, record)


def serve(container, state, command, record, record_path):
    """Supervise exactly one controller and its fixed-path queue, on the Docker host."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]+", container):
        raise ValueError("invalid controller name")
    state = state.expanduser().resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    check_service()
    with (state / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        controller = None
        stopped = threading.Event()
        worker_id = uuid4().hex

        def heartbeat():
            atomic_json(state / "heartbeat.json", {
                "protocol": protocol(), "time": time.time(), "worker_id": worker_id,
            })

        def active_heartbeat():
            if controller is not None and controller.poll() is not None:
                raise AcceptanceBlocked("controller exited during acceptance")
            heartbeat()

        def pulse():
            # Long snapshot copies/hashes are not worker failures or execution timeouts.
            while not stopped.wait(5):
                heartbeat()

        def stop(signum, frame):
            raise KeyboardInterrupt

        old = signal.signal(signal.SIGTERM, stop)
        thread = threading.Thread(target=pulse, daemon=True)
        try:
            heartbeat()
            if subprocess.run(["docker", "container", "inspect", container], check=False,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                raise ValueError("controller name already exists; refusing to start or stop it")
            command = command[:2] + ["--label", f"io.papersmith.worker={worker_id}"] + command[2:]
            controller = subprocess.Popen(command, start_new_session=True)
            record.update(status="supervising", worker_id=worker_id)
            atomic_json(record_path, record)
            thread.start()
            while controller.poll() is None:
                heartbeat()
                inbox = state / "poll" / uuid4().hex
                inbox.mkdir(parents=True)
                try:
                    docker_copy(container, "/acceptance/request.json", inbox)
                except subprocess.CalledProcessError:
                    inbox.rmdir()
                    time.sleep(1)
                    continue
                request_path = inbox / "request.json"
                request = json.loads(request_path.read_text())
                request_path.unlink()
                inbox.rmdir()
                if request.get("worker_id") != worker_id:
                    time.sleep(1)
                    continue
                rid = request.get("id", "")
                if not re.fullmatch(r"[0-9a-f]{32}", rid):
                    raise AcceptanceBlocked("invalid queue request id")
                target = state / "receipts" / (rid + ".json")
                if not target.exists():
                    snapshot_parent = state / "snapshots" / (rid + "-" + uuid4().hex)
                    snapshot_parent.mkdir(parents=True, exist_ok=False)
                    try:
                        if not re.fullmatch(r"candidate-[0-9]{4,}", request.get("task_name", "")):
                            raise AcceptanceBlocked("invalid task name")
                        docker_copy(container, f"/acceptance/tasks/{rid}/{request['task_name']}", snapshot_parent)
                        receipt = execute(state, snapshot_parent / request["task_name"], request, active_heartbeat)
                    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
                        receipt = {"request": request, "accepted": False,
                                   "error": type(error).__name__, "detail": str(error)}
                    atomic_json(target, receipt)
                time.sleep(1)
            return controller.returncode
        finally:
            stopped.set()
            if thread.is_alive():
                thread.join()
            if controller is not None:
                record["controller_returncode"] = controller.poll()
                record["cleanup"] = cleanup_controller(container, worker_id, controller)
            (state / "heartbeat.json").unlink(missing_ok=True)
            signal.signal(signal.SIGTERM, old)
            if record.get("cleanup", {}).get("status") == "pending":
                raise AcceptanceBlocked("owned-container cleanup incomplete; inspect supervisor state")
