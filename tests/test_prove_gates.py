from pathlib import Path

import pytest

import prove_gates as pg

MAIN = """from fastapi import FastAPI

app = FastAPI()


@app.get("/hello")
def hello(name: str = "world") -> str:
    return f"Hello, {name}!"
"""


@pytest.fixture
def service(tmp_path: Path) -> Path:
    (tmp_path / "src" / "svc").mkdir(parents=True)
    (tmp_path / "src" / "svc" / "main.py").write_text(MAIN)
    (tmp_path / "requirements.txt").write_text("fastapi==0.142.2\n")
    (tmp_path / "README.md").write_text("# svc\n")
    (tmp_path / ".copier-answers.yml").write_text("package_name: svc\nproject_slug: svc\n")
    return tmp_path


def test_package_name_read_from_copier_answers(service: Path) -> None:
    assert pg.package_name(service) == "svc"


def test_leaked_secret_is_random_and_obviously_assigned(service: Path) -> None:
    pg.leaked_secret(service, "svc")
    first = (service / "src" / "svc" / "payment_client.py").read_text()
    pg.leaked_secret(service, "svc")
    second = (service / "src" / "svc" / "payment_client.py").read_text()
    assert "PAYMENT_API_KEY = " in first
    assert first != second


def test_vulnerable_dependency_appends_pinned_urllib3(service: Path) -> None:
    pg.vulnerable_dependency(service, "svc")
    assert (service / "requirements.txt").read_text().splitlines()[-1] == "urllib3==1.24.1"


def test_failing_test_changes_greeting(service: Path) -> None:
    pg.failing_test(service, "svc")
    text = (service / "src" / "svc" / "main.py").read_text()
    assert 'f"Hi, {name}!"' in text
    assert "Hello," not in text


def test_type_error_adds_method_returned_as_str(service: Path) -> None:
    pg.type_error(service, "svc")
    assert "return hello(name).message.upper\n" in (service / "src" / "svc" / "main.py").read_text()


def make_result(expected: list[str], failed: list[str]) -> pg.Result:
    return pg.Result("s", "d", expected, "https://x/pull/1", "sha", failed_checks=failed)


@pytest.mark.parametrize(
    ("expected", "failed", "verdict"),
    [
        ([], [], "PASS: nothing blocked"),
        ([], ["quality / lint"], "UNEXPECTED: control failed"),
        (["a", "b"], ["a", "b", "c"], "CAUGHT by all expected gates"),
        (["a", "b"], ["a"], "CAUGHT by some expected gates"),
        (["a"], ["c"], "CAUGHT, but by other gates"),
        (["a"], [], "MISSED"),
    ],
)
def test_judge(expected: list[str], failed: list[str], verdict: str) -> None:
    result = make_result(expected, failed)
    pg.judge(result)
    assert result.verdict == verdict
