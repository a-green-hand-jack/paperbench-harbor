from pathlib import Path

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
    assert "--human-approval" in text
    assert "human approval" in text
