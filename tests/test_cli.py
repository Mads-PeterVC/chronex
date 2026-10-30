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
    assert show("nope", capsys) == (2, "nope does not exist\n")
    assert show("raw", capsys) == (2, "no recorded step wrote raw; it is an origin input of use\n")
    code, out = show("c", capsys)
    assert code == 2 and out.startswith("c was written by make at ")
    assert out.endswith("UTC, but has changed since\n")
    assert show("loose", capsys) == (2, "no recorded step wrote or read loose\n")


def test_report_embeds_the_figure_and_lists_hidden_reads(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    Path("config.json").write_text("{}")
    with chronex.step("plot") as s:
        Path("config.json").read_text()
        Path(s.output("figure.png")).write_bytes(b"\x89PNG not really")
    assert main(["report", "figure.png"]) == 0
    html = Path("lineage.html").read_text()
    data = json.loads(html.split("const D = ", 1)[1].split(";\n", 1)[0])
    assert data["image"].startswith("data:image/png;base64,")
    (act,) = data["acts"].values()
    assert act["undeclared_reads"] == ["config.json"]
    assert main(["report", "config.json"]) == 2
    assert check("--target", "config.json", capsys=capsys)[0] == 2


def test_an_identical_rerun_replaces_the_old_lineage(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Path("hidden").write_text("x")
    make(Path("a"), "the same content from both runs of make, long enough to link")
    with chronex.step("first") as s:
        Path("hidden").read_text()  # a flag on the old run only
        Path(s.output("b")).write_text(Path(s.input("a")).read_text())
    use(Path("a"), Path("c"))
    with chronex.step("first") as s:
        Path(s.output("b")).write_text(Path(s.input("a")).read_text())
    code, out = show("b", capsys)
    assert code == 0 and out.count("first [") == 1
    assert check("--target", "b", "--strict", capsys=capsys)[0] == 0


def test_content_written_elsewhere_is_not_a_files_lineage(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make(Path("count.txt"), "123")
    Path("tiny_out.txt").write_text("123")
    code, out = show("tiny_out.txt", capsys)
    assert code == 2
    assert out == "tiny_out.txt has the same content as an output of make, too little to link\n"


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
    import json

    make(Path("a"), "v1")
    Path("a").write_text("edited")
    use(Path("a"), Path("b"))
    code, out = check("--json", capsys=capsys)
    assert code == 1
    (entry,) = json.loads(out)
    assert entry["name"] == "use"
    assert entry["status"] == "completed"
    assert entry["code"] == "modified-after-write"
    assert entry["path"] == str(workdir / "a")
    assert Path(entry["record"]).is_file()


def test_forget_retires_a_failed_experiment(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make(Path("a"), "v1")
    with contextlib.suppress(RuntimeError), chronex.step("experiment"):
        raise RuntimeError("did not work")
    assert check("--strict", capsys=capsys)[0] == 1
    assert main(["forget", "experiment"]) == 0
    assert "forgot experiment" in capsys.readouterr().out
    assert check("--strict", capsys=capsys)[0] == 0
    assert len(list(Path(".chronex/forgotten").glob("*.json"))) == 1
    assert main(["forget", "nothing-by-this-name"]) == 2


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
