from __future__ import annotations

import os
from pathlib import Path

from paperbench_harbor.construction.core.latex import _resolve_tex_tool


def test_resolve_tex_tool_skips_a_path_wrapper_when_a_native_binary_exists(
    monkeypatch, tmp_path: Path
) -> None:
    wrappers = tmp_path / "wrappers"
    native = tmp_path / "native"
    wrappers.mkdir()
    native.mkdir()
    wrapper = wrappers / "pdflatex"
    wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary = native / "pdflatex"
    binary.write_bytes(b"\x7fELFnative-test")
    wrapper.chmod(0o755)
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join((str(wrappers), str(native))))

    assert _resolve_tex_tool("pdflatex") == str(binary)
