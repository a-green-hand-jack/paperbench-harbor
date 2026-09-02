"""Harbor network-policy resolution, and the contract check built on it.

The rules pinned here are Harbor 0.22.0's, reproduced in
`paperbench_harbor.fidelity.audit` so the audit can check the policy that
actually takes effect rather than the policy a file appears to declare. If a
Harbor upgrade changes the resolution order, these tests are the thing that
should fail first.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from paperbench_harbor.fidelity.audit import (
    DEFAULT_NETWORK_MODE,
    TaskReport,
    _audit_contract,
    effective_network_mode,
)


def _config(text: str) -> dict:
    return tomllib.loads(text)


def test_default_is_public_when_nothing_declares_a_policy() -> None:
    config = _config("[environment]\ncpus = 2\n")
    assert effective_network_mode(config, "agent") == DEFAULT_NETWORK_MODE
    assert effective_network_mode(config, "verifier") == "public"


def test_environment_baseline_is_inherited_by_both_phases() -> None:
    config = _config('[environment]\nnetwork_mode = "allowlist"\n')
    assert effective_network_mode(config, "agent") == "allowlist"
    assert effective_network_mode(config, "verifier") == "allowlist"


def test_phase_override_wins_over_the_baseline() -> None:
    config = _config(
        '[environment]\nnetwork_mode = "public"\n'
        '[verifier]\nnetwork_mode = "no-network"\n'
    )
    assert effective_network_mode(config, "verifier") == "no-network"
    assert effective_network_mode(config, "agent") == "public"


def test_separate_verifier_environment_does_not_imply_isolation() -> None:
    """The bug this module exists to catch.

    `environment_mode = "separate"` says the verifier runs in its own
    environment, not that the environment is offline. With no verifier policy
    declared, it inherits the writer environment's baseline.
    """
    config = _config(
        '[environment]\nallow_internet = true\n'
        '[verifier]\nenvironment_mode = "separate"\n'
    )
    assert effective_network_mode(config, "verifier") == "public"


def test_nested_verifier_environment_baseline_is_used() -> None:
    config = _config(
        '[environment]\nnetwork_mode = "public"\n'
        '[verifier.environment]\nnetwork_mode = "no-network"\n'
    )
    assert effective_network_mode(config, "verifier") == "no-network"
    assert effective_network_mode(config, "agent") == "public"


def test_phase_override_wins_over_its_nested_environment() -> None:
    config = _config(
        '[verifier]\nnetwork_mode = "allowlist"\n'
        '[verifier.environment]\nnetwork_mode = "no-network"\n'
    )
    assert effective_network_mode(config, "verifier") == "allowlist"


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [("true", "public"), ("false", "no-network")],
)
def test_deprecated_allow_internet_migrates(legacy: str, expected: str) -> None:
    config = _config(f"[environment]\nallow_internet = {legacy}\n")
    assert effective_network_mode(config, "agent") == expected


def test_explicit_network_mode_wins_over_deprecated_allow_internet() -> None:
    """Harbor's `_apply_legacy_allow_internet` only migrates when unset."""
    config = _config('[environment]\nallow_internet = true\nnetwork_mode = "no-network"\n')
    assert effective_network_mode(config, "agent") == "no-network"


def _report() -> TaskReport:
    return TaskReport(
        benchmark="PaperWrite-Bench", task_id="t-0001", upstream_paper_id="paper_1", ok=True
    )


def _write_task(tmp_path: Path, task_toml: str) -> Path:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text(task_toml, encoding="utf-8")
    (task_dir / "instruction.md").write_text(
        "Write main.tex and references.bib.", encoding="utf-8"
    )
    return task_dir


CURRENT_SPEC = """
[verifier]
environment_mode = "separate"

[environment]
network_mode = "public"
"""


def test_contract_check_passes_on_the_current_specification(tmp_path: Path) -> None:
    report = _report()
    _audit_contract(_write_task(tmp_path, CURRENT_SPEC), report)
    assert report.errors == []
    assert report.contract_checks > 0


def test_contract_check_accepts_the_deprecated_spelling(tmp_path: Path) -> None:
    """v0.3.1 ships `allow_internet`; the audit must keep passing on it."""
    report = _report()
    task_toml = '[verifier]\nenvironment_mode = "separate"\n[environment]\nallow_internet = true\n'
    _audit_contract(_write_task(tmp_path, task_toml), report)
    assert report.errors == []


def test_contract_check_rejects_a_wrong_phase_policy(tmp_path: Path) -> None:
    report = _report()
    task_toml = (
        '[verifier]\nenvironment_mode = "separate"\nnetwork_mode = "no-network"\n'
        '[environment]\nnetwork_mode = "public"\n'
    )
    _audit_contract(_write_task(tmp_path, task_toml), report)
    assert any("verifier network policy" in error for error in report.errors)


def test_contract_check_rejects_an_unknown_network_mode(tmp_path: Path) -> None:
    report = _report()
    task_toml = (
        '[verifier]\nenvironment_mode = "separate"\n[environment]\nnetwork_mode = "offline"\n'
    )
    _audit_contract(_write_task(tmp_path, task_toml), report)
    assert any("is a Harbor network mode" in error for error in report.errors)


def test_contract_check_rejects_unparseable_toml(tmp_path: Path) -> None:
    report = _report()
    _audit_contract(_write_task(tmp_path, "[environment\n"), report)
    assert any("not valid TOML" in error for error in report.errors)


def test_contract_check_reports_a_missing_task_toml(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    report = _report()
    _audit_contract(task_dir, report)
    assert report.errors == ["task.toml missing"]
