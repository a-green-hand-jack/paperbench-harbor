#!/usr/bin/env python3
"""Export one Harbor trial into the public Paper-Writing trial dataset.

The exporter intentionally has a small, explicit input surface. It copies the
Harbor result/configuration, the final submission, native ATIF trajectories and
agent logs/checkpoints, verifier outputs, and the official evaluation JSON when
present. It does not copy an entire job directory.

Example::

    python scripts/export_trial.py \
      --trial-dir /path/to/jobs/run/trial-id \
      --output-dir /path/to/Paper-Writing-Exam-Trials \
      --private-manifest /path/to/task/tests/private/source_manifest.json \
      --task-id pwb-0001 \
      --benchmark PaperWrite-Bench \
      --protocol short \
      --benchmark-hf-revision <immutable-revision> \
      --harbor-repo-commit <commit> \
      --agent-name codex \
      --agent-version 0.146.0 \
      --integration-commit <commit> \
       --model openai/gpt-5.6-sol \
       --provider openai \
       --agent-config-hash <sha256>

The command only creates local files. Upload the inspected output directory to
the Hugging Face repository separately.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import codecs
import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import stat
import tarfile
import tempfile
import zipfile
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
SANITIZATION_VERSION = "1.2"
SUPPORTED_ATIF_SCHEMA_VERSIONS = {f"ATIF-v1.{minor}" for minor in range(8)}
ATIF_ROOT_FIELDS = {
    "schema_version",
    "session_id",
    "trajectory_id",
    "agent",
    "steps",
    "notes",
    "final_metrics",
    "continued_trajectory_ref",
    "extra",
    "subagent_trajectories",
}
ATIF_STEP_FIELDS = {
    "step_id",
    "timestamp",
    "source",
    "model_name",
    "reasoning_effort",
    "message",
    "reasoning_content",
    "tool_calls",
    "observation",
    "metrics",
    "is_copied_context",
    "llm_call_count",
    "extra",
}
ATIF_CONTENT_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
SCAN_CHUNK_BYTES = 1024 * 1024
SCAN_OVERLAP_BYTES = 16 * 1024
MAX_ARCHIVE_DEPTH = 5
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024
MAX_TRAJECTORY_DEPTH = 8
MAX_TRAJECTORY_STEPS = 100_000
MAX_STRUCTURED_JSON_BYTES = 64 * 1024 * 1024

TRIAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
HF_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
RECOGNIZABLE_SECRET_RE = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{12,}|hf_[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9_-]{12,}|"
    rb"github_pat_[A-Za-z0-9_-]{12,}|xox[baprs]-[A-Za-z0-9-]{12,}|"
    rb"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
JSON_UNICODE_ESCAPE_RE = re.compile(r"(?:\\u[0-9a-fA-F]{4})+")
JSON_HEX_ESCAPE_RE = re.compile(r"(?:\\x[0-9a-fA-F]{2})+")
SAFE_ENV_REFERENCE_RE = re.compile(
    r"^(?:\$[A-Za-z_][A-Za-z0-9_]*|\$\{[A-Za-z_][A-Za-z0-9_]*\})$"
)
SECRET_ASSIGNMENT_VALUE = (
    r"\s*(?:(?:\\[\"'])(.*?)(?:\\[\"'])|"
    r"(?:[\"'])(.*?)(?:[\"'])|"
    r"((?:\\.|[^\\\s,\]])+))"
)
TEXT_SECRET_PATTERNS = (
    re.compile(
        r"(?i)(?<![\w.])(?:[A-Z][A-Z0-9]*_)?(?:API_KEY|ACCESS_TOKEN|REFRESH_TOKEN|CLIENT_SECRET)\b"
        r"\s*[\"']?\s*[:=]" + SECRET_ASSIGNMENT_VALUE
    ),
    re.compile(
        r"(?i)[\"'](?:token|secret|password|credential|credentials|secret[_-]?key|"
        r"private[_-]?key)[\"']\s*:" + SECRET_ASSIGNMENT_VALUE
    ),
    re.compile(
        r"(?i)(?:^|[\s,])(?:token|secret|password)\s*=" + SECRET_ASSIGNMENT_VALUE
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"(?i)\b(?:Authorization|Cookie|Set-Cookie)\b\s*[\"']?\s*[:=]"),
    re.compile(
        r"(?i)\b(?:aws[_-]?access[_-]?key[_-]?id|aws[_-]?secret[_-]?access[_-]?key)\b"
        r"\s*[\"']?\s*[:=]" + SECRET_ASSIGNMENT_VALUE
    ),
    re.compile(
        r"(?i)\b(?:credential|credentials|secret[_-]?key|private[_-]?key)\b"
        r"\s*[\"']?\s*[:=]" + SECRET_ASSIGNMENT_VALUE
    ),
)
SAFE_SECRET_VALUES = {"", "null", "none", "redacted", "masked", "***"}
UNSUPPORTED_COMPRESSED_SUFFIXES = {
    ".7z",
    ".br",
    ".bz2",
    ".lz4",
    ".lzh",
    ".lzip",
    ".lzo",
    ".xz",
    ".z",
    ".zst",
    ".zstd",
}
UNSUPPORTED_COMPRESSED_MAGICS = (
    b"\x28\xb5\x2f\xfd",  # zstandard
    b"\x04\x22\x4d\x18",  # lz4 frame
    b"BZh",  # bzip2
    b"\xfd7zXZ\x00",  # xz
    b"7z\xbc\xaf\x27\x1c",  # 7-Zip
    b"Rar!",  # RAR
    b"LZIP",  # lzip
    b"\x89LZO",  # lzop
    b"\x1f\x9d",  # compress(1)
    b"\x1f\xa0",  # compress(1), old magic
)

FORBIDDEN_BASENAMES = {
    ".env",
    "auth.json",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    "known_hosts",
    "eval_points.json",
    ".netrc",
    ".npmrc",
    "cookies.json",
    "cookies.sqlite",
    "application_default_credentials.json",
    "service-account.json",
    "service_account.json",
    "id_ecdsa",
    "id_dsa",
    "config.pem",
    "kubeconfig",
}
FORBIDDEN_PATH_MARKERS = (
    "/solution/",
    "/tests/private/",
    "/ground_truth/",
    "/ground-truth/",
    "/verifier-private/",
    "/.aws/",
    "/.azure/",
    "/.config/gcloud/",
    "/.docker/",
    "/.kube/",
)
FORBIDDEN_PATH_COMPONENTS = {
    "private",
    "solution",
    "ground_truth",
    "ground-truth",
    "verifier-private",
}


class TrialExportError(RuntimeError):
    """Raised when a trial cannot pass the export safety contract."""


@dataclass(frozen=True)
class SnapshotFile:
    """A source file copied once and used for every later export operation."""

    path: Path
    relative: Path
    size_bytes: int
    sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(SCAN_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _safe_trial_id(value: str) -> str:
    if not TRIAL_ID_RE.fullmatch(value):
        raise TrialExportError(f"invalid trial id: {value!r}")
    return value


def _path_key(path: Path) -> str:
    return "/" + path.as_posix().strip("/").lower() + "/"


def _assert_safe_path(relative_path: Path) -> None:
    parts = {part.lower() for part in relative_path.parts}
    normalized = _path_key(relative_path)
    if relative_path.name.lower() in FORBIDDEN_BASENAMES or relative_path.name.lower().startswith(
        ".env."
    ):
        raise TrialExportError(f"forbidden credential/private file in trial: {relative_path}")
    if parts & FORBIDDEN_PATH_COMPONENTS or any(
        marker in normalized for marker in FORBIDDEN_PATH_MARKERS
    ):
        raise TrialExportError(f"forbidden private path in trial: {relative_path}")


def _secret_error(relative_path: Path) -> TrialExportError:
    return TrialExportError(
        f"refusing to export {relative_path}: sensitive credential or encoded credential found"
    )


def _check_secret_bytes(data: bytes, relative_path: Path) -> None:
    if RECOGNIZABLE_SECRET_RE.search(data):
        raise _secret_error(relative_path)

    # Catch credentials represented as base64 or hex in logs, JSON, and binary
    # containers. Decoded values must still match a credential shape or field.
    for match in re.finditer(rb"[A-Za-z0-9+/=_-]{24,}", data):
        candidate = match.group(0)
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                decoded = decoder(candidate + b"=" * (-len(candidate) % 4))
            except (ValueError, binascii.Error):
                continue
            if RECOGNIZABLE_SECRET_RE.search(decoded):
                raise _secret_error(relative_path)
            try:
                decoded_text = decoded.decode("utf-8")
            except UnicodeDecodeError:
                decoded_text = decoded.decode("latin1")
            _check_secret_text(decoded_text, relative_path)
        if len(candidate) % 2 == 0 and re.fullmatch(rb"[0-9a-fA-F]+", candidate):
            try:
                decoded = bytes.fromhex(candidate.decode("ascii"))
            except ValueError:
                continue
            if RECOGNIZABLE_SECRET_RE.search(decoded):
                raise _secret_error(relative_path)
            _check_secret_text(decoded.decode("latin1"), relative_path)


def _check_secret_text(text: str, relative_path: Path) -> None:
    decoded = JSON_UNICODE_ESCAPE_RE.sub(
        lambda match: "".join(
            chr(int(match.group(0)[index + 2 : index + 6], 16))
            for index in range(0, len(match.group(0)), 6)
        ),
        text,
    )
    decoded = JSON_HEX_ESCAPE_RE.sub(
        lambda match: "".join(
            chr(int(match.group(0)[index + 2 : index + 4], 16))
            for index in range(0, len(match.group(0)), 4)
        ),
        decoded,
    )
    candidates = (text, decoded) if decoded != text else (text,)
    for candidate in candidates:
        if RECOGNIZABLE_SECRET_RE.search(candidate.encode("utf-8", errors="ignore")):
            raise _secret_error(relative_path)
        for pattern in TEXT_SECRET_PATTERNS:
            for match in pattern.finditer(candidate):
                if match.lastindex:
                    value = (
                        next(group for group in match.groups() if group is not None)
                        .replace('\\"', '"')
                        .replace("\\'", "'")
                        .strip("\"'")
                    )
                    if value.lower() in SAFE_SECRET_VALUES or SAFE_ENV_REFERENCE_RE.fullmatch(
                        value
                    ):
                        continue
                raise _secret_error(relative_path)


def _check_json_values(text: str, relative_path: Path) -> None:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return

    def visit(value: Any) -> None:
        if isinstance(value, str):
            _check_secret_text(value, relative_path)
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str):
                    _check_secret_text(key, relative_path)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)


def _check_jsonl_values(text: str, relative_path: Path) -> None:
    for line in text.splitlines():
        _check_json_values(line, relative_path)
def _text_encoding(path: Path) -> str | None:
    with path.open("rb") as handle:
        prefix = handle.read(4096)
    if prefix.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if prefix.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return "utf-32"
    if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    if b"\x00" in prefix:
        even_nuls = prefix[::2].count(0)
        odd_nuls = prefix[1::2].count(0)
        units = [prefix[index : index + 4] for index in range(0, len(prefix) - 3, 4)]
        if len(units) >= 4:
            le_units = [unit for unit in units if unit[0] != 0]
            be_units = [unit for unit in units if unit[3] != 0]
            if le_units and sum(unit[1:] == b"\x00\x00\x00" for unit in le_units) >= 4:
                return "utf-32-le"
            if be_units and sum(unit[:3] == b"\x00\x00\x00" for unit in be_units) >= 4:
                return "utf-32-be"
        if even_nuls > odd_nuls:
            return "utf-16-be"
        if odd_nuls > even_nuls:
            return "utf-16-le"
    try:
        prefix.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "utf-8"


def _scan_text_file(path: Path, relative_path: Path) -> None:
    encoding = _text_encoding(path)
    if encoding is None:
        return
    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    carry = ""
    structured_parts: list[str] | None = None
    structured_lines: list[str] | None = None
    if path.suffix.lower() == ".json":
        if path.stat().st_size > MAX_STRUCTURED_JSON_BYTES:
            raise TrialExportError(f"structured JSON artifact is too large: {relative_path}")
        structured_parts = []
    elif path.suffix.lower() == ".jsonl":
        structured_lines = []
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(SCAN_CHUNK_BYTES), b""):
                decoded_chunk = decoder.decode(chunk)
                if structured_parts is not None:
                    structured_parts.append(decoded_chunk)
                if structured_lines is not None:
                    structured_lines.append(decoded_chunk)
                text = carry + decoded_chunk
                _check_secret_text(text, relative_path)
                carry = text[-SCAN_OVERLAP_BYTES:]
            final_chunk = decoder.decode(b"", final=True)
            text = carry + final_chunk
            if structured_parts is not None:
                structured_parts.append(final_chunk)
            if structured_lines is not None:
                structured_lines.append(final_chunk)
            _check_secret_text(text, relative_path)
            if structured_parts is not None:
                _check_json_values("".join(structured_parts), relative_path)
            if structured_lines is not None:
                _check_jsonl_values("".join(structured_lines), relative_path)
    except UnicodeDecodeError:
        return


@dataclass
class _ScanBudget:
    members: int = 0
    expanded_bytes: int = 0

    def consume_member(self, relative_path: Path) -> None:
        self.members += 1
        if self.members > MAX_ARCHIVE_MEMBERS:
            raise TrialExportError(f"too many compressed members in {relative_path}")

    def consume_bytes(self, count: int, relative_path: Path) -> None:
        self.expanded_bytes += count
        if self.expanded_bytes > MAX_ARCHIVE_EXPANDED_BYTES:
            raise TrialExportError(f"compressed artifact expands too much: {relative_path}")


def _scan_archive_member(
    handle: Any, relative_path: Path, depth: int, budget: _ScanBudget, private_hashes: set[str]
) -> None:
    with tempfile.NamedTemporaryFile(prefix="paper-trial-member-", delete=False) as target:
        member_path = Path(target.name)
        try:
            for chunk in iter(lambda: handle.read(SCAN_CHUNK_BYTES), b""):
                budget.consume_bytes(len(chunk), relative_path)
                target.write(chunk)
        except Exception:
            member_path.unlink(missing_ok=True)
            raise
    try:
        _scan_file(member_path, relative_path, depth=depth, budget=budget, private_hashes=private_hashes)
    finally:
        member_path.unlink(missing_ok=True)


def _scan_compressed_file(
    path: Path, relative_path: Path, depth: int, budget: _ScanBudget, private_hashes: set[str]
) -> None:
    with path.open("rb") as handle:
        magic = handle.read(8)

    if magic.startswith(b"\x1f\x8b"):
        if depth >= MAX_ARCHIVE_DEPTH:
            raise TrialExportError(f"compressed artifact is nested too deeply: {relative_path}")
        decoded_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="paper-trial-gzip-", delete=False) as target:
                decoded_path = Path(target.name)
                try:
                    with path.open("rb") as handle:
                        pending = b""
                        source_eof = False
                        while True:
                            while len(pending) < 2 and not source_eof:
                                chunk = handle.read(SCAN_CHUNK_BYTES)
                                if chunk:
                                    pending += chunk
                                else:
                                    source_eof = True
                            if not pending:
                                break
                            if not pending.startswith(b"\x1f\x8b"):
                                raise TrialExportError(
                                    f"unexpected trailing gzip data in {relative_path}"
                                )
                            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
                            while not decompressor.eof:
                                if not pending:
                                    chunk = handle.read(SCAN_CHUNK_BYTES)
                                    if chunk:
                                        pending = chunk
                                    else:
                                        source_eof = True
                                if not pending:
                                    raise TrialExportError(
                                        f"truncated gzip artifact: {relative_path}"
                                    )
                                decoded = decompressor.decompress(pending)
                                if decoded:
                                    budget.consume_bytes(len(decoded), relative_path)
                                    target.write(decoded)
                                if decompressor.eof:
                                    pending = decompressor.unused_data
                                else:
                                    pending = decompressor.unconsumed_tail
                except (OSError, EOFError, zlib.error) as exc:
                    raise TrialExportError(
                        f"invalid compressed artifact: {relative_path}"
                    ) from exc
            if decoded_path is None:
                raise TrialExportError(f"cannot create decompressed artifact: {relative_path}")
            _scan_file(
                decoded_path,
                relative_path,
                depth=depth + 1,
                budget=budget,
                private_hashes=private_hashes,
            )
        finally:
            if decoded_path is not None:
                decoded_path.unlink(missing_ok=True)
        return

    if magic.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        if depth >= MAX_ARCHIVE_DEPTH:
            raise TrialExportError(f"compressed artifact is nested too deeply: {relative_path}")
        try:
            with zipfile.ZipFile(path) as archive:
                _check_secret_bytes(archive.comment, relative_path)
                try:
                    _check_secret_text(archive.comment.decode("utf-8"), relative_path)
                except UnicodeDecodeError:
                    pass
                for member in archive.infolist():
                    budget.consume_member(relative_path)
                    _check_secret_text(member.filename, relative_path)
                    _check_secret_bytes(member.comment, relative_path)
                    _check_secret_bytes(member.extra, relative_path)
                    try:
                        _check_secret_text(member.comment.decode("utf-8"), relative_path)
                        _check_secret_text(member.extra.decode("utf-8"), relative_path)
                    except UnicodeDecodeError:
                        pass
                    if (
                        member.filename.startswith(("/", "\\"))
                        or "\\" in member.filename
                        or ".." in Path(member.filename).parts
                    ):
                        raise TrialExportError(
                            f"refusing to inspect unsafe archive member in {relative_path}"
                        )
                    _assert_safe_path(relative_path / member.filename)
                    if member.is_dir():
                        continue
                    mode = (member.external_attr >> 16) & 0o170000
                    if mode and mode != stat.S_IFREG:
                        raise TrialExportError(
                            f"refusing non-regular archive member in {relative_path}"
                        )
                    with archive.open(member) as handle:
                        _scan_archive_member(
                            handle,
                            relative_path / member.filename,
                            depth + 1,
                            budget,
                            private_hashes,
                        )
        except (OSError, zipfile.BadZipFile) as exc:
            raise TrialExportError(f"invalid compressed artifact: {relative_path}") from exc
        return

    try:
        is_tar = tarfile.is_tarfile(path)
    except OSError as exc:
        raise TrialExportError(f"cannot inspect compressed artifact: {relative_path}") from exc
    if not is_tar:
        if magic.startswith((b"BZh", b"\xfd7zXZ\x00")):
            raise TrialExportError(
                f"unsupported standalone compressed artifact: {relative_path}"
            )
        return
    if depth >= MAX_ARCHIVE_DEPTH:
        raise TrialExportError(f"compressed artifact is nested too deeply: {relative_path}")
    try:
        with tarfile.open(path, mode="r:*") as archive:
            archive_metadata = json.dumps(archive.pax_headers, ensure_ascii=True)
            _check_secret_bytes(archive_metadata.encode("ascii"), relative_path)
            _check_secret_text(archive_metadata, relative_path)
            for member in archive.getmembers():
                budget.consume_member(relative_path)
                member_metadata = json.dumps(
                    {
                        "name": member.name,
                        "linkname": member.linkname,
                        "uname": member.uname,
                        "gname": member.gname,
                        "pax_headers": member.pax_headers,
                    },
                    ensure_ascii=True,
                )
                _check_secret_bytes(member_metadata.encode("ascii"), relative_path)
                _check_secret_text(member_metadata, relative_path)
                member_path = Path(member.name)
                if (
                    member_path.is_absolute()
                    or "\\" in member.name
                    or ".." in member_path.parts
                ):
                    raise TrialExportError(
                        f"refusing to inspect unsafe archive member in {relative_path}"
                    )
                _assert_safe_path(relative_path / member_path)
                if member.issym() or member.islnk() or member.isdev():
                    raise TrialExportError(
                        f"refusing non-regular archive member in {relative_path}"
                    )
                if member.isfile():
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise TrialExportError(
                            f"cannot inspect archive member in {relative_path}"
                        )
                    with handle:
                        _scan_archive_member(
                            handle,
                            relative_path / member.name,
                            depth + 1,
                            budget,
                            private_hashes,
                        )
    except (OSError, tarfile.TarError) as exc:
        raise TrialExportError(f"invalid compressed artifact: {relative_path}") from exc


def _scan_file(
    path: Path,
    relative_path: Path,
    *,
    depth: int = 0,
    budget: _ScanBudget | None = None,
    private_hashes: set[str] | None = None,
) -> None:
    _assert_safe_path(relative_path)
    _check_secret_text(relative_path.name, relative_path)
    if private_hashes and _sha256_file(path) in private_hashes:
        raise TrialExportError(
            f"refusing to export file matching verifier-private source material: {relative_path}"
        )
    with path.open("rb") as handle:
        carry = b""
        for chunk in iter(lambda: handle.read(SCAN_CHUNK_BYTES), b""):
            window = carry + chunk
            _check_secret_bytes(window, relative_path)
            carry = window[-SCAN_OVERLAP_BYTES:]
        if carry:
            _check_secret_bytes(carry, relative_path)
    _scan_text_file(path, relative_path)
    _scan_compressed_file(
        path,
        relative_path,
        depth,
        budget or _ScanBudget(),
        private_hashes or set(),
    )


def _assert_no_symlink_components(path: Path, label: str) -> None:
    for component in reversed(path.parents):
        if component.is_symlink():
            raise TrialExportError(f"refusing symlinked {label} path: {component}")
    if path.is_symlink():
        raise TrialExportError(f"refusing symlinked {label} path: {path}")


def _open_source_file(root: Path, relative: Path) -> Any:
    directory_flags = (
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd: int | None = None
    try:
        directory_fd = os.open(root, directory_flags)
        for part in relative.parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(relative.name, file_flags, dir_fd=directory_fd)
        return os.fdopen(file_fd, "rb")
    except OSError as exc:
        raise TrialExportError(f"cannot safely read source file: {relative}") from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _snapshot_file(
    source_root: Path,
    source: Path,
    relative: Path,
    snapshot_root: Path,
    private_hashes: set[str],
) -> SnapshotFile:
    _assert_safe_path(relative)
    destination = snapshot_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    try:
        with _open_source_file(source_root, relative) as source_handle:
            before = os.fstat(source_handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise TrialExportError(f"refusing non-regular trial file: {relative}")
            with destination.open("wb") as target:
                while True:
                    chunk = source_handle.read(SCAN_CHUNK_BYTES)
                    if not chunk:
                        break
                    digest.update(chunk)
                    target.write(chunk)
            after = os.fstat(source_handle.fileno())
    except (OSError, ValueError) as exc:
        raise TrialExportError(f"cannot snapshot trial file: {relative}") from exc
    if (
        before.st_ino != after.st_ino
        or before.st_dev != after.st_dev
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise TrialExportError(f"trial file changed while exporting: {relative}")
    os.chmod(destination, stat.S_IMODE(before.st_mode))
    snapshot = SnapshotFile(destination, relative, before.st_size, digest.hexdigest())
    _scan_file(snapshot.path, relative, private_hashes=private_hashes)
    return snapshot


def _iter_source_files(root: Path) -> Iterator[tuple[Path, Path]]:
    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise TrialExportError(f"trial directory not found: {root}") from exc
    if stat.S_ISLNK(root_stat.st_mode):
        raise TrialExportError(f"refusing symlinked trial path: {root}")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise TrialExportError(f"trial directory not found: {root}")

    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories.sort()
        filenames.sort()
        for name in list(directories):
            path = current_path / name
            if path.is_symlink():
                raise TrialExportError(f"refusing symlinked trial path: {path}")
            if not path.is_dir():
                raise TrialExportError(f"refusing non-directory trial path: {path}")
        for name in filenames:
            path = current_path / name
            relative = path.relative_to(root)
            try:
                mode = path.lstat().st_mode
            except OSError as exc:
                raise TrialExportError(f"cannot inspect trial file: {relative}") from exc
            if stat.S_ISLNK(mode):
                raise TrialExportError(f"refusing symlinked trial file: {relative}")
            if not stat.S_ISREG(mode):
                raise TrialExportError(f"refusing non-regular trial file: {relative}")
            yield path, relative


def _load_private_hashes(path: Path, trial_dir: Path) -> set[str]:
    _assert_no_symlink_components(path, "private source manifest")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise TrialExportError(f"private source manifest not found: {path}") from exc
    try:
        resolved.relative_to(trial_dir.resolve())
    except ValueError:
        pass
    else:
        raise TrialExportError("private source manifest must be outside the trial directory")
    payload = _read_json(resolved)
    private_hashes = payload.get("private_file_hashes")
    public_hashes = payload.get("public_file_hashes")
    if not isinstance(private_hashes, dict) or not private_hashes:
        raise TrialExportError("private source manifest has no private file hashes")
    if not isinstance(public_hashes, dict):
        public_hashes = {}
    public_values = {
        value.lower()
        for value in public_hashes.values()
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value)
    }
    hashes: set[str] = set()
    for value in private_hashes.values():
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise TrialExportError("private source manifest contains an invalid file hash")
        if value.lower() not in public_values:
            hashes.add(value.lower())
    if not hashes:
        raise TrialExportError("private source manifest has no private-only file hashes")
    return hashes


def _collect_files(
    trial_dir: Path, snapshot_root: Path, private_hashes: set[str]
) -> list[SnapshotFile]:
    snapshots: list[SnapshotFile] = []
    for source, relative in _iter_source_files(trial_dir):
        snapshot = _snapshot_file(trial_dir, source, relative, snapshot_root, private_hashes)
        if snapshot.sha256 in private_hashes:
            raise TrialExportError(
                f"refusing to export file matching verifier-private source material: {relative}"
            )
        snapshots.append(snapshot)

    result = next((item for item in snapshots if item.relative == Path("result.json")), None)
    if result is None:
        raise TrialExportError(f"Harbor result not found: {trial_dir / 'result.json'}")

    selected: list[SnapshotFile] = [
        SnapshotFile(result.path, Path("harbor/result.json"), result.size_bytes, result.sha256)
    ]
    for item in snapshots:
        if item.relative in {Path("result.json"), Path("config.json"), Path("lock.json"),
                             Path("trial.log"), Path("exception.txt")}:
            if item.relative != Path("result.json"):
                selected.append(
                    SnapshotFile(item.path, Path("harbor") / item.relative, item.size_bytes, item.sha256)
                )
            continue
        if (
            item.relative.parts
            and item.relative.parts[0] in {"agent", "verifier", "steps", "artifacts"}
        ) or item.relative.parts[:2] in {("logs", "agent"), ("logs", "verifier")}:
            selected.append(SnapshotFile(item.path, item.relative, item.size_bytes, item.sha256))

    if not any(item.relative.as_posix() != "harbor/result.json" for item in selected):
        raise TrialExportError("no allowlisted trial artifacts found")
    return selected


def _read_json(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=reject_constant
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise TrialExportError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise TrialExportError(f"expected a JSON object: {path}")
    _assert_finite_json(value, path)
    return value


def _assert_finite_json(value: Any, source: Path) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise TrialExportError(f"non-finite JSON number: {source}")
    if isinstance(value, dict):
        for child in value.values():
            _assert_finite_json(child, source)
    elif isinstance(value, list):
        for child in value:
            _assert_finite_json(child, source)


def _first_value(payload: Any, *keys: str) -> Any:
    if isinstance(payload, dict):
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        for value in payload.values():
            found = _first_value(value, *keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _first_value(value, *keys)
            if found is not None:
                return found
    return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _duration_seconds(result: dict[str, Any]) -> float | None:
    started = _parse_time(result.get("started_at"))
    finished = _parse_time(result.get("finished_at"))
    if started is None or finished is None:
        return None
    return max(0.0, (finished - started).total_seconds())


def _result_provenance(result: dict[str, Any]) -> dict[str, Any]:
    agent_info = result.get("agent_info")
    if not isinstance(agent_info, dict):
        agent_info = {}
    model_info = agent_info.get("model_info")
    if not isinstance(model_info, dict):
        model_info = {}
    return {
        "task_id": result.get("task_name") or result.get("task_id"),
        "task_checksum": result.get("task_checksum"),
        "agent_name": agent_info.get("name") or result.get("agent_name"),
        "agent_version": agent_info.get("version") or result.get("agent_version"),
        "model": model_info.get("name") or result.get("model"),
        "provider": model_info.get("provider") or result.get("provider"),
    }


def _validate_result_identity(
    result: dict[str, Any], args: argparse.Namespace, task_checksum: str
) -> dict[str, Any]:
    """Refuse manually supplied provenance that contradicts Harbor's result."""
    actual = _result_provenance(result)
    supplied = {
        "task_id": getattr(args, "task_id", None),
        "task_checksum": task_checksum,
        "agent_name": getattr(args, "agent_name", None),
        "agent_version": getattr(args, "agent_version", None),
        "model": getattr(args, "model", None),
        "provider": getattr(args, "provider", None),
    }
    for field, expected in supplied.items():
        found = actual.get(field)
        if found is not None and expected is not None and str(found) != str(expected):
            raise TrialExportError(
                f"{field} contradicts result.json: supplied {expected!r}, found {found!r}"
            )
    for field in ("task_id", "task_checksum", "agent_name", "agent_version"):
        value = actual[field] if actual.get(field) is not None else supplied[field]
        if not isinstance(value, str) or not value.strip():
            raise TrialExportError(f"{field} is required in result.json or exporter arguments")
    for field in ("model", "provider"):
        value = actual[field] if actual.get(field) is not None else supplied[field]
        if not isinstance(value, str) or not value.strip():
            raise TrialExportError(f"{field} is required in result.json or exporter arguments")
    return {
        field: actual[field] if actual.get(field) is not None else supplied[field]
        for field in supplied
    }


def _validate_atif_step(
    step: Any,
    source: Path,
    expected_id: int,
    step_count: list[int],
    trajectory_files: set[Path] | None,
) -> None:
    if not isinstance(step, dict):
        raise TrialExportError(f"ATIF trajectory step is not an object: {source}")
    if set(step) - ATIF_STEP_FIELDS:
        raise TrialExportError(f"ATIF trajectory step has unknown fields: {source}")
    step_id = step.get("step_id")
    if isinstance(step_id, bool) or not isinstance(step_id, int) or step_id != expected_id:
        raise TrialExportError(f"ATIF step_id is not sequential: {source}")
    if step_id < 1:
        raise TrialExportError(f"ATIF step_id is less than one: {source}")
    timestamp = step.get("timestamp")
    if timestamp is not None:
        if not isinstance(timestamp, str):
            raise TrialExportError(f"ATIF timestamp is not a string: {source}")
        try:
            datetime.fromisoformat(timestamp)
        except ValueError as exc:
            raise TrialExportError(f"ATIF timestamp is invalid: {source}") from exc
    source_name = step.get("source")
    if source_name not in {"system", "user", "agent"}:
        raise TrialExportError(f"ATIF source is invalid: {source}")
    message = step.get("message")
    if not isinstance(message, (str, list)):
        raise TrialExportError(f"ATIF message is missing or invalid: {source}")
    _validate_atif_content(message, source, "message", trajectory_files)
    agent_only = {"model_name", "reasoning_effort", "reasoning_content", "tool_calls", "metrics"}
    if source_name != "agent" and any(step.get(key) is not None for key in agent_only):
        raise TrialExportError(f"ATIF agent-only field on non-agent step: {source}")
    if step.get("model_name") is not None and not isinstance(step["model_name"], str):
        raise TrialExportError(f"ATIF model_name is invalid: {source}")
    if step.get("reasoning_effort") is not None and (
        not isinstance(step["reasoning_effort"], (str, int, float))
        or isinstance(step["reasoning_effort"], bool)
    ):
        raise TrialExportError(f"ATIF reasoning_effort is invalid: {source}")
    if step.get("reasoning_content") is not None and not isinstance(
        step["reasoning_content"], str
    ):
        raise TrialExportError(f"ATIF reasoning_content is invalid: {source}")
    if step.get("tool_calls") is not None:
        tool_calls = step["tool_calls"]
        if not isinstance(tool_calls, list):
            raise TrialExportError(f"ATIF tool_calls is not a list: {source}")
        tool_call_ids: set[str] = set()
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                raise TrialExportError(f"ATIF tool call is not an object: {source}")
            if set(tool_call) - {"tool_call_id", "function_name", "arguments", "extra"}:
                raise TrialExportError(f"ATIF tool call has unknown fields: {source}")
            if not isinstance(tool_call.get("tool_call_id"), str) or not isinstance(
                tool_call.get("function_name"), str
            ) or not isinstance(tool_call.get("arguments"), dict):
                raise TrialExportError(f"ATIF tool call is invalid: {source}")
            if tool_call.get("extra") is not None and not isinstance(tool_call["extra"], dict):
                raise TrialExportError(f"ATIF tool call extra is invalid: {source}")
            tool_call_ids.add(tool_call["tool_call_id"])
    else:
        tool_call_ids = set()
    observation = step.get("observation")
    if observation is not None:
        if not isinstance(observation, dict) or not isinstance(observation.get("results"), list):
            raise TrialExportError(f"ATIF observation is invalid: {source}")
        if set(observation) - {"results"}:
            raise TrialExportError(f"ATIF observation has unknown fields: {source}")
        for result in observation["results"]:
            if not isinstance(result, dict):
                raise TrialExportError(f"ATIF observation result is invalid: {source}")
            if set(result) - {"source_call_id", "content", "subagent_trajectory_ref", "extra"}:
                raise TrialExportError(f"ATIF observation result has unknown fields: {source}")
            content = result.get("content")
            if content is not None:
                if not isinstance(content, (str, list)):
                    raise TrialExportError(f"ATIF observation content is invalid: {source}")
                _validate_atif_content(content, source, "observation content", trajectory_files)
            source_call_id = result.get("source_call_id")
            if source_call_id is not None and (
                not isinstance(source_call_id, str) or source_call_id not in tool_call_ids
            ):
                raise TrialExportError(f"ATIF source_call_id is invalid: {source}")
            refs = result.get("subagent_trajectory_ref")
            if refs is not None:
                if not isinstance(refs, list):
                    raise TrialExportError(f"ATIF subagent references are not a list: {source}")
                for ref in refs:
                    _validate_atif_reference(ref, source)
            if result.get("extra") is not None and not isinstance(result["extra"], dict):
                raise TrialExportError(f"ATIF observation result extra is invalid: {source}")
    llm_call_count = step.get("llm_call_count")
    if llm_call_count is not None and (
        isinstance(llm_call_count, bool)
        or not isinstance(llm_call_count, int)
        or llm_call_count < 0
    ):
        raise TrialExportError(f"ATIF llm_call_count is invalid: {source}")
    if llm_call_count == 0 and source_name == "agent" and (
        "metrics" in step or "reasoning_content" in step
    ):
        raise TrialExportError(f"ATIF deterministic step contains LLM fields: {source}")
    _validate_atif_metrics(step.get("metrics"), source)
    if step.get("is_copied_context") is not None and not isinstance(
        step["is_copied_context"], bool
    ):
        raise TrialExportError(f"ATIF is_copied_context is invalid: {source}")
    if step.get("extra") is not None and not isinstance(step["extra"], dict):
        raise TrialExportError(f"ATIF step extra is invalid: {source}")
    step_count[0] += 1
    if step_count[0] > MAX_TRAJECTORY_STEPS:
        raise TrialExportError(f"ATIF trajectory has too many steps: {source}")


def _validate_atif_content(
    value: str | list[Any],
    source: Path,
    label: str,
    trajectory_files: set[Path] | None,
) -> None:
    if isinstance(value, str):
        return
    for part in value:
        if not isinstance(part, dict) or part.get("type") not in {"text", "image"}:
            raise TrialExportError(f"ATIF {label} content part is invalid: {source}")
        if part["type"] == "text":
            if set(part) - {"type", "text", "source"} or not isinstance(
                part.get("text"), str
            ) or part.get("source") is not None:
                raise TrialExportError(f"ATIF {label} text part is invalid: {source}")
        else:
            image_source = part.get("source")
            if set(part) - {"type", "source", "text"} or not isinstance(
                image_source, dict
            ) or ("text" in part and part["text"] is not None):
                raise TrialExportError(f"ATIF {label} image part is invalid: {source}")
            if (
                set(image_source) - {"media_type", "path"}
                or image_source.get("media_type") not in ATIF_CONTENT_MEDIA_TYPES
                or not isinstance(image_source.get("path"), str)
            ):
                raise TrialExportError(f"ATIF {label} image source is invalid: {source}")
            image_path = image_source["path"]
            image_relative = Path(image_path)
            if (
                image_relative.is_absolute()
                or ".." in image_relative.parts
                or "\\" in image_path
                or "://" in image_path
            ):
                raise TrialExportError(f"ATIF {label} image source is not local: {source}")
            if trajectory_files is not None:
                image_target = Path(
                    os.path.normpath((source.parent / image_relative).as_posix())
                )
                if image_target not in trajectory_files:
                    raise TrialExportError(
                        f"ATIF {label} image source is not included in the archive: {source}"
                    )


def _validate_atif_metrics(value: Any, source: Path) -> None:
    if value is None:
        return
    fields = {
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "cost_usd",
        "prompt_token_ids",
        "completion_token_ids",
        "logprobs",
        "extra",
    }
    if not isinstance(value, dict) or set(value) - fields:
        raise TrialExportError(f"ATIF metrics are invalid: {source}")
    for key in ("prompt_tokens", "completion_tokens", "cached_tokens"):
        if key in value and value[key] is not None and (
            isinstance(value[key], bool) or not isinstance(value[key], int)
        ):
            raise TrialExportError(f"ATIF metrics are invalid: {source}")
    if value.get("cost_usd") is not None and (
        isinstance(value["cost_usd"], bool) or not isinstance(value["cost_usd"], (int, float))
    ):
        raise TrialExportError(f"ATIF metrics are invalid: {source}")
    for key in ("prompt_token_ids", "completion_token_ids"):
        if key in value and value[key] is not None and (
            not isinstance(value[key], list)
            or any(isinstance(item, bool) or not isinstance(item, int) for item in value[key])
        ):
            raise TrialExportError(f"ATIF metrics are invalid: {source}")
    if value.get("logprobs") is not None and (
        not isinstance(value["logprobs"], list)
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value["logprobs"])
    ):
        raise TrialExportError(f"ATIF metrics are invalid: {source}")
    if value.get("extra") is not None and not isinstance(value["extra"], dict):
        raise TrialExportError(f"ATIF metrics are invalid: {source}")


def _validate_atif_final_metrics(value: Any, source: Path) -> None:
    fields = {
        "total_prompt_tokens",
        "total_completion_tokens",
        "total_cached_tokens",
        "total_cost_usd",
        "total_steps",
        "extra",
    }
    if not isinstance(value, dict) or set(value) - fields:
        raise TrialExportError(f"ATIF final_metrics are invalid: {source}")
    for key in (
        "total_prompt_tokens",
        "total_completion_tokens",
        "total_cached_tokens",
        "total_steps",
    ):
        if key in value and value[key] is not None and (
            isinstance(value[key], bool) or not isinstance(value[key], int)
        ):
            raise TrialExportError(f"ATIF final_metrics are invalid: {source}")
    if value.get("total_steps") is not None and value["total_steps"] < 0:
        raise TrialExportError(f"ATIF final_metrics are invalid: {source}")
    if value.get("total_cost_usd") is not None and (
        isinstance(value["total_cost_usd"], bool)
        or not isinstance(value["total_cost_usd"], (int, float))
    ):
        raise TrialExportError(f"ATIF final_metrics are invalid: {source}")
    if value.get("extra") is not None and not isinstance(value["extra"], dict):
        raise TrialExportError(f"ATIF final_metrics are invalid: {source}")


def _validate_atif_reference(value: Any, source: Path) -> None:
    if not isinstance(value, dict):
        raise TrialExportError(f"ATIF subagent reference is not an object: {source}")
    if set(value) - {"trajectory_id", "session_id", "trajectory_path", "extra"}:
        raise TrialExportError(f"ATIF subagent reference has unknown fields: {source}")
    trajectory_id = value.get("trajectory_id")
    trajectory_path = value.get("trajectory_path")
    if trajectory_id is None and trajectory_path is None:
        raise TrialExportError(f"ATIF subagent reference is not resolvable: {source}")
    if trajectory_id is not None and (
        not isinstance(trajectory_id, str) or not trajectory_id
    ):
        raise TrialExportError(f"ATIF subagent trajectory_id is invalid: {source}")
    if trajectory_path is not None and (
        not isinstance(trajectory_path, str) or not trajectory_path
    ):
        raise TrialExportError(f"ATIF subagent trajectory_path is invalid: {source}")
    if value.get("session_id") is not None and not isinstance(value["session_id"], str):
        raise TrialExportError(f"ATIF subagent session_id is invalid: {source}")
    if value.get("extra") is not None and not isinstance(value["extra"], dict):
        raise TrialExportError(f"ATIF subagent reference extra is invalid: {source}")
    if value.get("session_id") is not None and not isinstance(value["session_id"], str):
        raise TrialExportError(f"ATIF subagent session_id is invalid: {source}")
    if value.get("extra") is not None and not isinstance(value["extra"], dict):
        raise TrialExportError(f"ATIF subagent reference extra is invalid: {source}")

def _validate_atif_trajectory(
    trajectory: dict[str, Any],
    source: Path,
    *,
    nested: bool = False,
    depth: int = 0,
    step_count: list[int] | None = None,
    trajectory_files: set[Path] | None = None,
) -> list[dict[str, Any]]:
    if depth > MAX_TRAJECTORY_DEPTH:
        raise TrialExportError(f"ATIF trajectory is nested too deeply: {source}")
    if set(trajectory) - ATIF_ROOT_FIELDS:
        raise TrialExportError(f"ATIF trajectory has unknown fields: {source}")
    if trajectory.get("schema_version") not in SUPPORTED_ATIF_SCHEMA_VERSIONS:
        raise TrialExportError(f"unsupported ATIF schema version: {source}")
    agent = trajectory.get("agent")
    if (
        not isinstance(agent, dict)
        or set(agent) - {"name", "version", "model_name", "tool_definitions", "extra"}
        or not isinstance(agent.get("name"), str)
        or not isinstance(agent.get("version"), str)
    ):
        raise TrialExportError(f"ATIF agent identity is missing: {source}")
    if agent.get("model_name") is not None and not isinstance(agent["model_name"], str):
        raise TrialExportError(f"ATIF agent model_name is invalid: {source}")
    if agent.get("tool_definitions") is not None and (
        not isinstance(agent["tool_definitions"], list)
        or any(not isinstance(tool, dict) for tool in agent["tool_definitions"])
    ):
        raise TrialExportError(f"ATIF agent tool_definitions are invalid: {source}")
    if agent.get("extra") is not None and not isinstance(agent["extra"], dict):
        raise TrialExportError(f"ATIF agent extra is invalid: {source}")
    for field in ("session_id", "trajectory_id", "notes", "continued_trajectory_ref"):
        if trajectory.get(field) is not None and not isinstance(trajectory[field], str):
            raise TrialExportError(f"ATIF {field} is invalid: {source}")
    if trajectory.get("final_metrics") is not None:
        _validate_atif_final_metrics(trajectory["final_metrics"], source)
    if trajectory.get("extra") is not None and not isinstance(trajectory["extra"], dict):
        raise TrialExportError(f"ATIF trajectory extra is invalid: {source}")
    if agent.get("model_name") is not None and not isinstance(agent["model_name"], str):
        raise TrialExportError(f"ATIF agent model_name is invalid: {source}")
    if agent.get("tool_definitions") is not None and (
        not isinstance(agent["tool_definitions"], list)
        or any(not isinstance(tool, dict) for tool in agent["tool_definitions"])
    ):
        raise TrialExportError(f"ATIF agent tool_definitions are invalid: {source}")
    if agent.get("extra") is not None and not isinstance(agent["extra"], dict):
        raise TrialExportError(f"ATIF agent extra is invalid: {source}")
    for field in ("session_id", "trajectory_id", "notes", "continued_trajectory_ref"):
        if trajectory.get(field) is not None and not isinstance(trajectory[field], str):
            raise TrialExportError(f"ATIF {field} is invalid: {source}")
    if trajectory.get("final_metrics") is not None:
        _validate_atif_final_metrics(trajectory["final_metrics"], source)
    if trajectory.get("extra") is not None and not isinstance(trajectory["extra"], dict):
        raise TrialExportError(f"ATIF trajectory extra is invalid: {source}")
    if nested and not isinstance(trajectory.get("trajectory_id"), str):
        raise TrialExportError(f"nested ATIF trajectory id is missing: {source}")
    steps = trajectory.get("steps")
    if not isinstance(steps, list) or not steps:
        raise TrialExportError(f"ATIF trajectory has no steps array: {source}")
    step_count = step_count or [0]
    for expected_id, step in enumerate(steps, start=1):
        _validate_atif_step(step, source, expected_id, step_count, trajectory_files)
    nested_trajectories = trajectory.get("subagent_trajectories")
    if nested_trajectories is not None:
        if not isinstance(nested_trajectories, list):
            raise TrialExportError(f"ATIF subagent trajectories are not a list: {source}")
        nested_ids: set[str] = set()
        for value in nested_trajectories:
            if not isinstance(value, dict):
                raise TrialExportError(f"nested ATIF trajectory is not an object: {source}")
            trajectory_id = value.get("trajectory_id")
            if not isinstance(trajectory_id, str) or not trajectory_id or trajectory_id in nested_ids:
                raise TrialExportError(f"nested ATIF trajectory id is invalid: {source}")
            nested_ids.add(trajectory_id)
            _validate_atif_trajectory(
                value,
                source,
                nested=True,
                depth=depth + 1,
                step_count=step_count,
                trajectory_files=trajectory_files,
            )
    continued_ref = trajectory.get("continued_trajectory_ref")
    if continued_ref is not None and (
        not isinstance(continued_ref, str) or not continued_ref
    ):
        raise TrialExportError(f"ATIF continuation reference is invalid: {source}")
    return steps


def _iter_atif_steps(
    trajectory: dict[str, Any], trajectory_path: str
) -> Iterator[tuple[str, dict[str, Any]]]:
    for step in trajectory["steps"]:
        yield trajectory_path, step
    for value in trajectory.get("subagent_trajectories") or []:
        yield from _iter_atif_steps(
            value, f"{trajectory_path}#subagent/{value['trajectory_id']}"
        )


def _iter_atif_references(trajectory: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for step in trajectory["steps"]:
        observation = step.get("observation")
        if not isinstance(observation, dict):
            continue
        for result in observation.get("results", []):
            if not isinstance(result, dict):
                continue
            yield from result.get("subagent_trajectory_ref") or []


def _resolve_local_trajectory_reference(
    source: Path, reference_path: str, trajectory_files: set[Path]
) -> Path:
    candidate = Path(reference_path)
    if (
        candidate.is_absolute()
        or "\\" in reference_path
        or "://" in reference_path
    ):
        raise TrialExportError(f"ATIF external trajectory reference is not local: {source}")
    resolved = Path(os.path.normpath((source.parent / candidate).as_posix()))
    if ".." in resolved.parts:
        raise TrialExportError(f"ATIF external trajectory reference escapes trial: {source}")
    if resolved not in trajectory_files:
        raise TrialExportError(f"ATIF external trajectory reference is missing: {source}")
    return resolved


def _validate_atif_references(
    trajectory: dict[str, Any],
    source: Path,
    trajectory_files: set[Path],
    trajectories: dict[Path, dict[str, Any]],
) -> None:
    embedded_ids = {
        child.get("trajectory_id")
        for child in trajectory.get("subagent_trajectories") or []
        if isinstance(child, dict)
    }
    for reference in _iter_atif_references(trajectory):
        trajectory_id = reference.get("trajectory_id")
        trajectory_path = reference.get("trajectory_path")
        if trajectory_id is not None and trajectory_path is None and trajectory_id not in embedded_ids:
            raise TrialExportError(f"ATIF embedded trajectory reference is missing: {source}")
        if trajectory_path is not None:
            resolved = _resolve_local_trajectory_reference(source, trajectory_path, trajectory_files)
            if trajectory_id is not None:
                target = trajectories[resolved]
                if target.get("trajectory_id") != trajectory_id:
                    raise TrialExportError(f"ATIF trajectory reference identity mismatch: {source}")
    continued_ref = trajectory.get("continued_trajectory_ref")
    if continued_ref is not None:
        _resolve_local_trajectory_reference(source, continued_ref, trajectory_files)
    for child in trajectory.get("subagent_trajectories") or []:
        _validate_atif_references(child, source, trajectory_files, trajectories)


def _load_events(files: list[SnapshotFile], trial_id: str) -> list[dict[str, Any]]:
    """Derive queryable rows from Harbor's native ATIF trajectory files."""
    events: list[dict[str, Any]] = []
    trajectories: dict[Path, dict[str, Any]] = {}
    available_paths = {item.relative for item in files}
    for item in files:
        if not _is_trajectory_path(item.relative):
            continue
        trajectory = _read_json(item.path)
        trajectories[item.relative] = trajectory
    trajectory_files = set(trajectories)
    for trajectory_path, trajectory in trajectories.items():
        _validate_atif_trajectory(
            trajectory, trajectory_path, trajectory_files=available_paths
        )
        _validate_atif_references(trajectory, trajectory_path, trajectory_files, trajectories)
    for item in files:
        trajectory = trajectories.get(item.relative)
        if trajectory is None:
            continue
        for trajectory_path, step in _iter_atif_steps(trajectory, item.relative.as_posix()):
            events.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "trial_id": trial_id,
                    "trajectory_path": trajectory_path,
                    "sequence": len(events),
                    "step_id": step.get("step_id"),
                    "timestamp": step.get("timestamp"),
                    "source": step.get("source"),
                    "event": step,
                }
            )
    return events


def _find_evaluation(files: list[SnapshotFile]) -> dict[str, Any]:
    candidates = [item for item in files if _is_evaluation_path(item.relative)]
    root = [item for item in candidates if item.relative.parts[0] != "steps"]
    if len(root) > 1:
        raise TrialExportError("multiple root verifier evaluation files found")
    if root:
        return _read_json(root[0].path)
    if len(candidates) == 1:
        return _read_json(candidates[0].path)
    if candidates:
        return {
            "step_evaluations": {
                item.relative.as_posix(): _read_json(item.path) for item in candidates
            }
        }
    return {}


def _is_trajectory_path(relative: Path) -> bool:
    if not relative.name.startswith("trajectory") or relative.suffix != ".json":
        return False
    parts = relative.parts
    return (
        parts[0] == "agent"
        or (parts[0] == "steps" and "agent" in parts)
        or parts[:2] == ("logs", "agent")
    )


def _is_evaluation_path(relative: Path) -> bool:
    parts = relative.parts
    if parts == ("verifier", "evaluation.json"):
        return True
    if parts == ("logs", "verifier", "evaluation.json"):
        return True
    return parts[0] == "steps" and len(parts) >= 3 and parts[-2:] == ("verifier", "evaluation.json")


def _archive(files: list[SnapshotFile], archive_path: Path) -> tuple[str, list[dict[str, Any]]]:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_files: list[dict[str, Any]] = []
    with (
        archive_path.open("wb") as raw_handle,
        gzip.GzipFile(fileobj=raw_handle, mode="wb", filename="", mtime=0) as gzip_handle,
        tarfile.open(fileobj=gzip_handle, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        for item in sorted(files, key=lambda value: value.relative.as_posix()):
            info = archive.gettarinfo(item.path, arcname=item.relative.as_posix())
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mode = 0o755 if item.path.stat().st_mode & stat.S_IXUSR else 0o644
            info.pax_headers = {
                key: value
                for key, value in info.pax_headers.items()
                if key not in {"atime", "ctime"}
            }
            with item.path.open("rb") as source:
                archive.addfile(info, source)
            manifest_files.append(
                {
                    "path": item.relative.as_posix(),
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
            )
    return _sha256_file(archive_path), manifest_files


@contextmanager
def _output_lock(output_dir: Path) -> Iterator[None]:
    lock_path = output_dir.parent / f".{output_dir.name}.export.lock"
    _assert_no_symlink_components(lock_path, "output lock")
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _existing_record_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    if path.is_symlink() or not path.is_file():
        raise TrialExportError(f"output index is not a regular file: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise TrialExportError(f"invalid trial index: {path}") from exc
    record_ids: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TrialExportError(f"invalid trial index: {path}") from exc
        if not isinstance(record, dict) or not isinstance(record.get("trial_id"), str):
            raise TrialExportError(f"trial index record has no trial id: {path}")
        record_ids.add(record["trial_id"])
    return record_ids


def _assert_optional_regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise TrialExportError(f"{label} is not a regular file: {path}")


def _has_exception(payload: Any) -> bool:
    if isinstance(payload, dict):
        if payload.get("exception_info"):
            return True
        return any(_has_exception(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_has_exception(value) for value in payload)
    return False


def _validate_config_hash(value: Any) -> None:
    if value is not None and (
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value)
    ):
        raise TrialExportError("agent config hash must be a SHA-256 hex digest")


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrialExportError(f"{label} must be a non-empty string")
    return value


def _validate_trial_record(record: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "trial_id",
        "task_id",
        "benchmark",
        "benchmark_protocol",
        "benchmark_hf_repo",
        "benchmark_hf_revision",
        "harbor_repo_commit",
        "task_checksum",
        "agent_name",
        "agent_version",
        "integration_commit",
        "model",
        "provider",
        "agent_config_hash",
        "status",
        "official_metrics",
        "artifact_archive",
        "artifact_sha256",
        "sanitization_version",
    }
    if not required.issubset(record):
        raise TrialExportError("generated trial record does not match its schema")
    for field in required - {
        "schema_version",
        "status",
        "official_metrics",
        "agent_config_hash",
        "artifact_sha256",
        "sanitization_version",
    }:
        _require_text(record[field], field)
    if not HF_COMMIT_RE.fullmatch(record["benchmark_hf_revision"]):
        raise TrialExportError("benchmark_hf_revision must be an immutable commit SHA")
    if record["schema_version"] != SCHEMA_VERSION or record["sanitization_version"] != SANITIZATION_VERSION:
        raise TrialExportError("generated trial record has an unsupported schema version")
    if record["status"] not in {"completed", "failed"} or not isinstance(
        record["official_metrics"], dict
    ):
        raise TrialExportError("generated trial record does not match its schema")
    if record.get("run_id") is not None and not isinstance(record["run_id"], str):
        raise TrialExportError("generated trial record has an invalid run id")
    for field in ("started_at", "finished_at"):
        if record.get(field) is not None and not isinstance(record[field], str):
            raise TrialExportError(f"generated trial record has an invalid {field}")
    if record.get("duration_seconds") is not None and (
        isinstance(record["duration_seconds"], bool)
        or not isinstance(record["duration_seconds"], (int, float))
        or record["duration_seconds"] < 0
    ):
        raise TrialExportError("generated trial record has an invalid duration")
    _validate_config_hash(record["agent_config_hash"])
    if not isinstance(record["artifact_sha256"], str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", record["artifact_sha256"]
    ):
        raise TrialExportError("generated trial record has an invalid archive hash")
    reward = record.get("harbor_reward")
    if isinstance(reward, bool) or not (
        reward is None or isinstance(reward, (int, float, str, dict, list))
    ):
        raise TrialExportError("generated trial record has an invalid Harbor reward")
    if not isinstance(record.get("event_count"), int) or isinstance(
        record["event_count"], bool
    ) or record["event_count"] < 0:
        raise TrialExportError("generated trial record has an invalid event count")
    _assert_finite_json(record, Path("trial-record"))


def _harbor_reward(result: dict[str, Any]) -> Any:
    verifier_result = result.get("verifier_result")
    if not isinstance(verifier_result, dict):
        return None
    reward = _first_value(verifier_result, "reward")
    if reward is not None:
        return reward
    rewards = verifier_result.get("rewards")
    if isinstance(rewards, dict) and len(rewards) == 1:
        only_value = next(iter(rewards.values()))
        if isinstance(only_value, (int, float)) and not isinstance(only_value, bool):
            return only_value
    return rewards


def _assert_output_is_usable(output_dir: Path) -> None:
    _assert_no_symlink_components(output_dir, "output")
    if output_dir.exists() and not output_dir.is_dir():
        raise TrialExportError(f"output path is not a directory: {output_dir}")
    for path in (output_dir / "artifacts", output_dir / "manifests", output_dir / "data"):
        _assert_no_symlink_components(path, "output")
        if path.exists() and not path.is_dir():
            raise TrialExportError(f"output path is not a directory: {path}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)


def _copy_append(path: Path, destination: Path, line: str | None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_bytes() if path.is_file() else b""
    if line is not None:
        if existing and not existing.endswith(b"\n"):
            existing += b"\n"
        existing += line.encode("utf-8")
    destination.write_bytes(existing)


def _commit_outputs(
    additions: list[tuple[Path, Path]], replacements: list[tuple[Path, Path]], temp_root: Path
) -> None:
    backups: list[tuple[Path, Path]] = []
    committed: list[Path] = []
    created_directories: list[Path] = []

    def ensure_parent(path: Path) -> None:
        missing: list[Path] = []
        current = path.parent
        while not current.exists():
            missing.append(current)
            current = current.parent
        path.parent.mkdir(parents=True, exist_ok=True)
        created_directories.extend(reversed(missing))

    try:
        for source, destination in replacements:
            ensure_parent(destination)
            if destination.exists():
                backup = temp_root / "backups" / destination.name
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup)
                backups.append((backup, destination))
            os.replace(source, destination)
            committed.append(destination)
        for source, destination in additions:
            ensure_parent(destination)
            if destination.exists() or destination.is_symlink():
                raise TrialExportError(f"trial already exists in output: {destination.name}")
            os.replace(source, destination)
            committed.append(destination)
    except Exception:
        for path in reversed(committed):
            path.unlink(missing_ok=True)
        for backup, destination in reversed(backups):
            os.replace(backup, destination)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def export_trial(args: argparse.Namespace) -> dict[str, Any]:
    trial_input = args.trial_dir.expanduser().absolute()
    _assert_no_symlink_components(trial_input, "trial")
    try:
        if stat.S_ISLNK(trial_input.lstat().st_mode):
            raise TrialExportError(f"refusing symlinked trial path: {trial_input}")
    except OSError as exc:
        raise TrialExportError(f"trial directory not found: {trial_input}") from exc
    trial_dir = trial_input
    if not trial_dir.is_dir():
        raise TrialExportError(f"trial directory not found: {trial_dir}")

    private_manifest = getattr(args, "private_manifest", None)
    if private_manifest is None:
        raise TrialExportError("private source manifest is required for trial export")
    private_hashes = _load_private_hashes(Path(private_manifest), trial_dir)

    output_input = args.output_dir.expanduser().absolute()
    _assert_output_is_usable(output_input)
    output_dir = output_input.resolve()
    try:
        output_dir.relative_to(trial_dir)
    except ValueError:
        pass
    else:
        raise TrialExportError("output directory must be outside the trial directory")
    trial_id_hint = getattr(args, "trial_id", None)

    # All validation and derived data consume this snapshot. The source tree is
    # never read again after this block, which keeps the archive and hashes
    # consistent even when Harbor is still flushing files.
    with tempfile.TemporaryDirectory(prefix="paper-trial-snapshot-") as snapshot_name:
        snapshot_root = Path(snapshot_name)
        files = _collect_files(trial_dir, snapshot_root, private_hashes)
        result_item = next(item for item in files if item.relative == Path("harbor/result.json"))
        trial_result = _read_json(result_item.path)
        result_task_checksum = trial_result.get("task_checksum")
        if not isinstance(result_task_checksum, str) or not result_task_checksum.strip():
            raise TrialExportError("result.json must contain a non-empty task checksum")
        task_checksum = getattr(args, "task_checksum", None) or result_task_checksum
        if not isinstance(task_checksum, str) or not task_checksum.strip():
            raise TrialExportError("task checksum is required via --task-checksum or result.json")
        provenance = _validate_result_identity(trial_result, args, task_checksum)
        result_trial_id = trial_result.get("id")
        if result_trial_id is not None and (
            not isinstance(result_trial_id, str) or not result_trial_id.strip()
        ):
            raise TrialExportError("result.json must contain a valid trial id")
        if trial_id_hint is not None and result_trial_id is not None and trial_id_hint != result_trial_id:
            raise TrialExportError(
                f"trial_id contradicts result.json: supplied {trial_id_hint!r}, "
                f"found {result_trial_id!r}"
            )
        trial_id = _safe_trial_id(trial_id_hint or result_trial_id or "")

        config_hash = getattr(args, "agent_config_hash", None)
        config_file = getattr(args, "agent_config_file", None)
        if config_file:
            config_path = Path(config_file).expanduser().absolute()
            _assert_no_symlink_components(config_path, "agent config")
            if not config_path.is_file():
                raise TrialExportError(f"agent config file not found: {config_path}")
            _scan_file(config_path, Path("agent-config"), private_hashes=private_hashes)
            config_hash = _sha256_file(config_path)
        _validate_config_hash(config_hash)
        if config_hash is None:
            raise TrialExportError("agent config hash or file is required")

        archive_path = output_dir / "artifacts" / f"{trial_id}.tar.gz"
        manifest_path = output_dir / "manifests" / f"{trial_id}.json"
        records_path = output_dir / "data" / "trials.jsonl"
        events_path = output_dir / "data" / "events.jsonl"

        official_metrics = _find_evaluation(files)
        events = _load_events(files, trial_id)
        archive_parent = output_dir.parent
        with tempfile.TemporaryDirectory(prefix="paper-trial-output-", dir=archive_parent) as temp_name:
            temp_root = Path(temp_name)
            temp_archive = temp_root / "artifacts" / archive_path.name
            archive_sha256, artifact_files = _archive(files, temp_archive)
            record = {
                "schema_version": SCHEMA_VERSION,
                "trial_id": trial_id,
                "run_id": getattr(args, "run_id", None)
                or trial_result.get("trial_name")
                or trial_result.get("source"),
                "task_id": provenance["task_id"],
                "benchmark": args.benchmark,
                "benchmark_protocol": args.protocol,
                "benchmark_hf_repo": args.benchmark_hf_repo,
                "benchmark_hf_revision": args.benchmark_hf_revision,
                "harbor_repo_commit": args.harbor_repo_commit,
                "task_checksum": provenance["task_checksum"],
                "agent_name": provenance["agent_name"],
                "agent_version": provenance["agent_version"],
                "integration_commit": args.integration_commit,
                "model": provenance["model"],
                "provider": provenance["provider"],
                "agent_config_hash": config_hash,
                "started_at": trial_result.get("started_at"),
                "finished_at": trial_result.get("finished_at"),
                "duration_seconds": _duration_seconds(trial_result),
                "status": "failed" if _has_exception(trial_result) else "completed",
                "harbor_reward": _harbor_reward(trial_result),
                "official_metrics": official_metrics,
                "event_count": len(events),
                "artifact_archive": archive_path.relative_to(output_dir).as_posix(),
                "artifact_sha256": archive_sha256,
                "sanitization_version": SANITIZATION_VERSION,
            }
            _validate_trial_record(record)
            _check_secret_bytes(
                json.dumps(record, allow_nan=False, sort_keys=True).encode("utf-8"),
                Path("trial-record"),
            )
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "trial_id": trial_id,
                "artifact_archive": record["artifact_archive"],
                "artifact_sha256": archive_sha256,
                "files": artifact_files,
                "source_result_sha256": result_item.sha256,
                "sanitization_version": SANITIZATION_VERSION,
            }
            temp_manifest = temp_root / "manifests" / manifest_path.name
            temp_records = temp_root / "data" / records_path.name
            temp_events = temp_root / "data" / events_path.name
            _json_dump(temp_manifest, manifest)
            with _output_lock(output_dir):
                _assert_output_is_usable(output_dir)
                if any(
                    path.exists() or path.is_symlink()
                    for path in (archive_path, manifest_path)
                ):
                    raise TrialExportError(f"trial already exists in output: {trial_id}")
                if trial_id in _existing_record_ids(records_path):
                    raise TrialExportError(f"trial already exists in output index: {trial_id}")
                _assert_optional_regular_file(records_path, "trial index")
                _assert_optional_regular_file(events_path, "event index")
                _copy_append(
                    records_path,
                    temp_records,
                    json.dumps(record, allow_nan=False, sort_keys=True) + "\n",
                )
                if events:
                    event_lines = "".join(
                        json.dumps(event, allow_nan=False, sort_keys=True) + "\n"
                        for event in events
                    )
                    _copy_append(events_path, temp_events, event_lines)

                replacements = [(temp_records, records_path)]
                if events:
                    replacements.append((temp_events, events_path))
                _commit_outputs(
                    [(temp_archive, archive_path), (temp_manifest, manifest_path)],
                    replacements,
                    temp_root,
                )
        return record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--private-manifest", type=Path, required=True)
    parser.add_argument("--trial-id")
    parser.add_argument("--run-id")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--task-checksum")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument(
        "--benchmark-hf-repo", default="Jack-Jieke-Wu/Paper-Writing-Exam"
    )
    parser.add_argument("--benchmark-hf-revision", required=True)
    parser.add_argument("--harbor-repo-commit", required=True)
    parser.add_argument("--agent-name", required=True)
    parser.add_argument("--agent-version", required=True)
    parser.add_argument("--integration-commit", required=True)
    parser.add_argument("--model")
    parser.add_argument("--provider")
    config_group = parser.add_mutually_exclusive_group(required=True)
    config_group.add_argument("--agent-config-file", type=Path)
    config_group.add_argument("--agent-config-hash")
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        record = export_trial(args)
    except TrialExportError as exc:
        raise SystemExit(f"trial export refused: {exc}") from exc
    print(json.dumps(record, allow_nan=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
