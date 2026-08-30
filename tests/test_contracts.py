import ast
import contextlib
import io
import os
from pathlib import Path

from paperbench_harbor.common.contracts import SubmissionContract


def test_submission_contract_is_stable() -> None:
    contract = SubmissionContract()
    assert contract.root == Path("/workspace/submission")
    assert contract.required_relative_paths == ("main.tex", "references.bib")


def test_evaluator_bridges_judge_key_without_logging_secret() -> None:
    for name in ("grader_pwb.py.j2", "grader_pwbw.py.j2"):
        source = Path("src/paperbench_harbor/common/templates") / name
        text = source.read_text(encoding="utf-8")
        tree = ast.parse(text.replace("{{", "__jinja_open__").replace("}}", "__jinja_close__"))
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_configure_judge_environment"
        )
        namespace = {"os": os}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)  # noqa: S102
        configure = namespace["_configure_judge_environment"]

        sentinel = "judge-secret-sentinel"
        # Exercise the helper in a temporary environment without touching the host shell.
        from unittest.mock import patch

        with patch.dict(os.environ, {"JUDGE_API_KEY": sentinel}, clear=True):
            configure()
            assert os.environ["OPENAI_API_KEY"] == sentinel
        with patch.dict(
            os.environ,
            {"JUDGE_API_KEY": sentinel, "OPENAI_BASE_URL": "https://judge.example/v1"},
            clear=True,
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                configure()
            assert os.environ["OPENAI_API_KEY"] == sentinel
            assert os.environ["OPENAI_API_BASE"] == "https://judge.example/v1"
            assert sentinel not in output.getvalue()
        with patch.dict(
            os.environ,
            {
                "JUDGE_API_KEY": sentinel,
                "OPENAI_API_KEY": "explicit-key",
                "OPENAI_API_BASE": "https://explicit.example/v1",
                "OPENAI_BASE_URL": "https://ignored.example/v1",
            },
            clear=True,
        ):
            configure()
            assert os.environ["OPENAI_API_KEY"] == "explicit-key"
            assert os.environ["OPENAI_API_BASE"] == "https://explicit.example/v1"
