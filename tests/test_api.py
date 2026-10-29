import json
from pathlib import Path

import pytest

import chronex
from chronex import In, Out
from chronex import graph as graphs


def records(root: Path) -> list[dict]:
    return graphs.load(root)


def test_decorator_records_typed_paths_and_parameters(workdir: Path) -> None:
    Path("a.txt").write_text("hello")

    @chronex.step
    def upper(source: In[Path], target: Out[Path], times: int = 2) -> None:
        target.write_text(source.read_text().upper() * times)

    upper(Path("a.txt"), Path("b.txt"), times=3)
    (record,) = records(workdir)
    assert record["name"] == "upper"
    assert record["status"] == "completed"
    assert record["params"] == {"times": 3}
    assert [i["param"] for i in record["inputs"]] == ["source"]
    assert [o["rel"] for o in record["outputs"]] == ["b.txt"]
    assert record["undeclared_reads"] == []
    assert record["undeclared_writes"] == []


def test_decorator_accepts_collections_of_paths(workdir: Path) -> None:
    for name in "xyz":
        Path(name).write_text(name)

    @chronex.step
    def join(parts: In[list[str]], joined: Out[str]) -> None:
        Path(joined).write_text("".join(Path(p).read_text() for p in parts))

    join(["x", "y", "z"], "joined")
    (record,) = records(workdir)
    assert len(record["inputs"]) == 3


def test_undeclared_read_is_reported(workdir: Path) -> None:
    Path("declared").write_text("1")
    Path("hidden").write_text("2")

    @chronex.step
    def sneaky(source: In[Path], target: Out[Path]) -> None:
        target.write_text(source.read_text() + Path("hidden").read_text())

    sneaky(Path("declared"), Path("out"))
    (record,) = records(workdir)
    assert [Path(p).name for p in record["undeclared_reads"]] == ["hidden"]


def test_failure_is_recorded_and_raised(workdir: Path) -> None:
    @chronex.step
    def broken(target: Out[Path]) -> None:
        target.write_text("partial")
        raise ValueError("nope")

    with pytest.raises(ValueError):
        broken(Path("out"))
    (record,) = records(workdir)
    assert record["status"] == "failed"
    assert "nope" in record["error"]
    assert record["outputs"][0]["kind"] == "file"


def test_block_declares_files_where_they_are_used(workdir: Path) -> None:
    Path("in.json").write_text(json.dumps({"x": 1}))
    with chronex.step("double", factor=2) as s:
        data = json.loads(Path(s.input("in.json")).read_text())
        Path(s.output("out.json")).write_text(json.dumps({"x": data["x"] * 2}))
    (record,) = records(workdir)
    assert record["kind"] == "block"
    assert record["params"] == {"factor": 2}
    assert record["inputs"][0]["rel"] == "in.json"


def test_module_level_input_is_a_no_op_outside_a_step(workdir: Path) -> None:
    assert chronex.input("anything") == "anything"
    assert not (workdir / ".chronex").exists()


def test_nested_steps_record_their_parent(workdir: Path) -> None:
    with chronex.step("outer") as outer, chronex.step("inner"):
        Path("f").write_text("x")
    found = {r["name"]: r for r in records(workdir)}
    assert found["inner"]["parent"] == outer.id
