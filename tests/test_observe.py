"""What the audit hook sees, and what a step makes of it."""

import json
import os
from pathlib import Path

import pytest

import chronex
from chronex import graph as graphs


def only_record(root: Path) -> dict:
    (record,) = graphs.load(root)
    return record


def flag_codes(root: Path) -> list[str]:
    graph = graphs.build(graphs.load(root))
    return [f.code for _, f in graph.all_flags() if f.level != "info"]


def test_a_declared_input_that_does_not_exist_is_flagged(workdir: Path) -> None:
    with chronex.step("typo") as s:
        s.input("dat.csv")
        Path(s.output("out")).write_text("x")
    assert only_record(workdir)["missing_inputs"] == [str(workdir / "dat.csv")]
    assert flag_codes(workdir) == ["missing-input"]


def test_a_file_read_and_then_rewritten_is_still_a_read(workdir: Path) -> None:
    Path("db.json").write_text("{}")
    with chronex.step("update"):
        data = json.loads(Path("db.json").read_text())
        Path("db.json").write_text(json.dumps({**data, "a": 1}))
    assert only_record(workdir)["undeclared_reads"] == [str(workdir / "db.json")]


def test_auto_mode_records_the_content_read_before_it_was_rewritten(workdir: Path) -> None:
    Path("db.json").write_text("{}")
    with chronex.step("update") as s:
        s.auto = True
        Path("db.json").read_text()
        Path("db.json").write_text('{"a": 1}')
    record = only_record(workdir)
    (read,) = [i for i in record["inputs"] if i["rel"] == "db.json"]
    (written,) = [o for o in record["outputs"] if o["rel"] == "db.json"]
    assert read["sha"] != written["sha"]


def test_reading_a_file_the_step_wrote_is_not_an_input(workdir: Path) -> None:
    with chronex.step("roundtrip") as s:
        Path(s.output("a")).write_text("x")
        Path("a").read_text()
    assert only_record(workdir)["undeclared_reads"] == []


def test_files_in_a_user_cache_are_observed(workdir: Path) -> None:
    weights = workdir / ".cache" / "huggingface" / "model.bin"
    weights.parent.mkdir(parents=True)
    weights.write_text("weights")
    with chronex.step("load"):
        weights.read_text()
    assert only_record(workdir)["undeclared_reads"] == [str(weights)]


def test_chronex_ignore_skips_extra_paths(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (workdir / "scratch").mkdir()
    Path("scratch/tmp").write_text("x")
    monkeypatch.setenv("CHRONEX_IGNORE", str(workdir / "scratch"))
    with chronex.step("load"):
        Path("scratch/tmp").read_text()
    assert only_record(workdir)["undeclared_reads"] == []


def test_a_renamed_temporary_file_records_its_final_name(workdir: Path) -> None:
    with chronex.step("atomic") as s:
        Path("result.json.tmp").write_text("{}")
        os.replace("result.json.tmp", s.output("result.json"))
    record = only_record(workdir)
    assert record["observed"]["writes"] == [str(workdir / "result.json")]
    assert record["undeclared_writes"] == []
