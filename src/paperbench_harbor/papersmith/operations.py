"""Shared uncapped process lifecycle and credential-safe operational categories."""

import os
import signal
import subprocess
from enum import StrEnum


class Category(StrEnum):
    QUOTA = "quota"
    NETWORK = "network"
    ACCESS = "access"
    SCHEMA = "schema"
    CONTENT = "content"
    COMPILE = "compile"
    DEPS = "deps"
    ACCEPTANCE = "acceptance"
    SCIENTIFIC = "scientific"
    INTERRUPTED = "interrupted"


class OperationalError(RuntimeError):
    def __init__(self, classification, message):
        self.classification = Category(classification).value
        super().__init__(message)


def classify(error):
    if isinstance(error, KeyboardInterrupt):
        return Category.INTERRUPTED.value
    if isinstance(error, OperationalError):
        return error.classification
    if isinstance(error, FileNotFoundError):
        return Category.DEPS.value
    if isinstance(error, PermissionError):
        return Category.ACCESS.value
    if isinstance(error, (ConnectionError, TimeoutError)):
        return Category.NETWORK.value
    if type(error).__name__ == "ValidationError":
        return Category.SCHEMA.value
    return Category.CONTENT.value if isinstance(error, ValueError) else Category.DEPS.value


def diagnostic(text):
    """Only return an allowlisted category, never raw provider output."""
    text = text.casefold()
    for category, terms in (
        (Category.QUOTA, ("quota", "usage limit", "rate limit", "insufficient credit", "429")),
        (Category.ACCESS, ("unauthorized", "forbidden", "permission", "authentication", "401", "403")),
        (Category.NETWORK, ("connection", "network", "timed out", "timeout", "dns", "502", "503")),
    ):
        if any(term in text for term in terms):
            return category.value
    return Category.DEPS.value


def terminate(process):
    if process.poll() is not None:
        return
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=15 if sig != signal.SIGKILL else None)
            return
        except subprocess.TimeoutExpired:
            continue


def run(command, **kwargs):
    """No execution duration limit; grace periods apply only after cancellation."""
    check = kwargs.pop("check", False)
    timeout = kwargs.pop("timeout", None)
    if kwargs.pop("capture_output", False):
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process = subprocess.Popen(command, start_new_session=True, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result
    finally:
        terminate(process)
