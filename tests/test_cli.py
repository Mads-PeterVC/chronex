"""The command line: scoping and exit codes of check, and the messages of show."""

import contextlib
import os
from pathlib import Path

import pytest

import chronex
from chronex import In, Out
from chronex.cli import main


@chronex.step
def make(target: Out[Path], value: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value)


@chronex.step
def use(source: In[Path], target: Out[Path]) -> None:
    target.write_text(source.read_text() + "!")


def check(*args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["check", *args])
    return code, capsys.readouterr().out


def test_a_mistake_fixed_by_rerunning_no_longer_fails_check(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make(Path("a"), "v1")
    Path("a").write_text("edited by hand")
    use(Path("a"), Path("b"))
    assert check(capsys=capsys)[0] == 1
    make(Path("a"), "v1")
    use(Path("a"), Path("b"))
    code, out = check(capsys=capsys)
    assert code == 0
    assert "modified-after-write" not in out
    assert "2 not current" in out
    assert check("--history", capsys=capsys)[0] == 1


def test_a_failed_step_rerun_successfully_is_not_current(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for fail in (True, False):
        with contextlib.suppress(RuntimeError), chronex.step("flaky", n=1):
            if fail:
                raise RuntimeError("first try")
    assert "failed" not in check(capsys=capsys)[1]


def test_strict_fails_on_warnings(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    Path("hidden").write_text("x")
    with chronex.step("sneaky") as s:
        Path("hidden").read_text()
        Path(s.output("out")).write_text("y")
    assert check(capsys=capsys)[0] == 0
    assert check("--strict", capsys=capsys)[0] == 1


def test_target_limits_check_to_one_lineage(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make(Path("good/a"), "fine")
    use(Path("good/a"), Path("good/b"))
    make(Path("bad/a"), "v1")
    Path("bad/a").write_text("edited")
    use(Path("bad/a"), Path("bad/b"))
    assert check(capsys=capsys)[0] == 1
    assert check("--target", "good/b", capsys=capsys)[0] == 0
    assert check("--target", "bad/b", capsys=capsys)[0] == 1


def test_check_says_when_inputs_come_from_outside_the_roots(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Path("up").mkdir()
    Path("down").mkdir()
    os.chdir("up")
    make(Path("a"), "content written by a step whose record lives in up/")
    os.chdir("../down")
    use(Path("../up/a"), Path("b"))
    os.chdir("..")
    out = check("down", capsys=capsys)[1]
    assert "1 origin input outside the searched directories" in out
    assert "outside" not in check(capsys=capsys)[1]


def test_records_are_found_without_walking_virtualenvs(workdir: Path) -> None:
    from chronex import graph as graphs

    (workdir / ".venv" / "lib" / ".chronex").mkdir(parents=True)
    (workdir / ".venv" / "lib" / ".chronex" / "x.json").write_text("not json")
    make(Path("a"), "v1")
    assert len(graphs.load(workdir)) == 1


def show(path: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["show", path])
    return code, capsys.readouterr().out


def test_show_names_the_files_on_each_step(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make(Path("a"), "v1")
    use(Path("a"), Path("b"))
    code, out = show("b", capsys)
    assert code == 0
    assert out.splitlines() == ["use [completed]  a → b", "  make [completed] value=v1  → a"]


def test_show_explains_why_a_file_has_no_lineage(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Path("raw").write_text("measured")
    use(Path("raw"), Path("b"))
    make(Path("c"), "v1")
    Path("c").write_text("edited")
    Path("loose").write_text("x")
    assert show("nope", capsys) == (1, "nope does not exist\n")
    assert show("raw", capsys) == (1, "no recorded step wrote raw; it is an origin input of use\n")
    code, out = show("c", capsys)
    assert code == 1 and out.startswith("c was written by make at ")
    assert out.endswith("UTC, but has changed since\n")
    assert show("loose", capsys) == (1, "no recorded step wrote or read loose\n")
