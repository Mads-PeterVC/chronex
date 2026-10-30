"""`chronex check`: what counts as current, scoping, exit codes and JSON."""

import contextlib
import json
import os
from pathlib import Path

import pytest

import chronex
from tests.helpers import check, make, use


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
    assert "(2 older runs hidden, --history to show)" in out
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


def test_the_summary_counts_origin_files_once(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Path("config").write_text("{}")
    use(Path("config"), Path("a"))
    use(Path("config"), Path("b"))
    out = check(capsys=capsys)[1]
    assert out.strip() == "2 current steps; 0 linked inputs, 1 origin file, 0 flags"


def test_json_names_the_step_and_the_file(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:

    make(Path("a"), "v1")
    Path("a").write_text("edited")
    use(Path("a"), Path("b"))
    code, out = check("--json", capsys=capsys)
    assert code == 1
    found = json.loads(out)
    assert found["summary"]["flags"] == {"error": 1, "warn": 0, "info": 0}
    assert found["summary"]["passed"] is False
    (entry,) = found["flags"]
    assert entry["name"] == "use"
    assert entry["status"] == "completed"
    assert entry["code"] == "modified-after-write"
    assert entry["path"] == str(workdir / "a")
    assert Path(entry["record"]).is_file()


def test_check_names_the_steps_that_keep_an_older_run_current(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make(Path("a"), "v1" * 40)
    use(Path("a"), Path("b"))
    with chronex.step("peek") as s:
        Path(s.input("b")).read_text()
    make(Path("a"), "v2" * 40)
    use(Path("a"), Path("b"))  # the old use is redone, but peek still read its b
    out = check(capsys=capsys)[1]
    (line,) = [line for line in out.splitlines() if "  use  " in line]
    assert "use has been re-run since [an older run" in line
    assert "still current because peek used its output: re-run or forget peek" in line
