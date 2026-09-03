"""Check stable cross-dataset documentation links and inventory coverage."""

from __future__ import annotations

from pathlib import Path

DATASETS = (
    "Jack-Jieke-Wu/Paper-Writing-Exam",
    "Jack-Jieke-Wu/Paper-Writing-Exam-Trials",
    "Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive",
)


def validate_documentation(root: Path) -> list[str]:
    required = {
        "README.md": DATASETS,
        "docs/huggingface-paper-writing-exam.md": DATASETS,
        "docs/trial-dataset.md": (
            "Jack-Jieke-Wu/Paper-Writing-Exam",
            "Jack-Jieke-Wu/Paper-Writing-Exam-Trials",
            "Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive",
        ),
        "packaging/huggingface/paper-writing-exam/README.md": DATASETS,
        "packaging/huggingface/paper-writing-exam-trials/README.md": DATASETS,
        "packaging/huggingface/paper-writing-exam-source-archive/README.md": DATASETS,
    }
    errors: list[str] = []
    for relative, expected in required.items():
        path = root / relative
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        for value in expected:
            if value not in text:
                errors.append(f"{relative} does not link {value}")

    inventory = root / "docs" / "documentation-inventory.md"
    inventory_text = inventory.read_text(encoding="utf-8") if inventory.is_file() else ""
    for document in sorted((root / "docs").glob("*.md")):
        relative = document.relative_to(root).as_posix()
        if f"`{relative}`" not in inventory_text:
            errors.append(f"documentation inventory does not cover {relative}")
    return errors


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    errors = validate_documentation(root)
    if errors:
        raise SystemExit("\n".join(errors))


if __name__ == "__main__":
    main()
