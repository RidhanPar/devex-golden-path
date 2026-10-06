from pathlib import Path

import measure_dx as dx

ROOT = Path(__file__).resolve().parent.parent


def test_handmade_baseline_gates_are_lint_and_tests_only() -> None:
    workflow = (dx.BASELINE / ".github" / "workflows" / "ci.yml").read_text()
    assert dx.gates_in(workflow) == ["lint", "tests"]


def test_golden_path_service_workflow_has_every_gate() -> None:
    workflow = (ROOT / "template" / ".github" / "workflows" / "ci.yml.jinja").read_text()
    assert dx.gates_in(workflow) == [
        "lint",
        "typecheck",
        "tests",
        "windows tests",
        "SAST",
        "dependency scan",
        "secret scan",
        "container build + scan",
        "deploy (OIDC)",
    ]


def test_hand_written_counts_non_blank_lines(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n\n\ny = 2\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("one\n")
    assert dx.hand_written(tmp_path) == {"files": 2, "lines": 3}
