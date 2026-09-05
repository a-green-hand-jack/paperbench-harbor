from pathlib import Path

import pytest
import yaml

AGENT = (
    Path(__file__).resolve().parents[1]
    / ".opencode"
    / "agent"
    / "papersmith-lifesci.md"
)


def test_papersmith_cannot_write_or_disable_required_audits() -> None:
    text = AGENT.read_text(encoding="utf-8")

    assert "mode: primary" in text
    assert '  "*": deny' in text
    assert "  write: deny" in text
    assert "  edit: deny" in text
    assert "  task: deny" in text
    assert '    "* --no-audit": deny' in text
    assert '    "* --no-semantic-review": deny' in text
    assert "--agent-approval" in text
    assert "independent verifier" in text


@pytest.mark.parametrize("domain", ["lifesci", "physics", "chemistry", "mathematics"])
def test_entry_allows_guidance_and_read_only_preflight(domain):
    text = AGENT.with_name(f"papersmith-{domain}.md").read_text()
    permission = yaml.safe_load(text.split("---", 2)[1])["permission"]
    assert permission["external_directory"]["*"] == "ask"
    assert permission["external_directory"]["~/.agents/consensus/**"] == "allow"
    assert permission["bash"]["pwd"] == "allow"
    assert permission["bash"]["git status --short --branch"] == "allow"
    assert permission["bash"]["*"] == "deny"
    assert permission["edit"] == "deny"
    assert permission["task"] == "deny"
