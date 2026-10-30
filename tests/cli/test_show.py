"""`chronex show`: the lineage of a file, or why it has none."""

from pathlib import Path

import pytest

import chronex
from tests.helpers import check, make, show, use


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
