import json
import os
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


def test_a_coroutine_is_recorded_while_it_runs(workdir: Path) -> None:
    import asyncio

    @chronex.step
    async def write(target: Out[Path]) -> int:
        await asyncio.sleep(0)
        target.write_text("async")
        return 1

    assert asyncio.run(write(Path("a.txt"))) == 1
    (record,) = records(workdir)
    assert record["status"] == "completed"
    assert record["missing_outputs"] == []


def test_a_generator_cannot_be_a_step() -> None:
    def numbers(target: Out[Path]):  # type: ignore[no-untyped-def]
        yield 1

    with pytest.raises(TypeError, match="block"):
        chronex.step(numbers)


def test_large_arguments_are_summarised(workdir: Path) -> None:
    np = pytest.importorskip("numpy")

    @chronex.step
    def total(values: object, numbers: list[int], target: Out[Path]) -> None:
        target.write_text("done")

    total(np.zeros((400, 500)), list(range(1000)), Path("t"))
    (record,) = records(workdir)
    assert Path(record["_file"]).stat().st_size < 20_000
    assert record["params"]["values"]["shape"] == [400, 500]
    assert record["params"]["values"]["dtype"] == "float64"
    assert record["params"]["numbers"]["len"] == 1000
    small = np.arange(3)
    total(small, [1, 2], Path("t"))
    assert {r["params"]["numbers"] == [1, 2] for r in records(workdir)} == {True, False}


def test_a_parent_may_read_what_its_child_steps_wrote(workdir: Path) -> None:
    @chronex.step
    def shout(source: In[Path], target: Out[Path]) -> None:
        target.write_text(source.read_text().upper())

    Path("in.txt").write_text("hi")
    with chronex.step("outer") as s:
        shout(Path(s.input("in.txt")), Path("mid.txt"))
        Path(s.output("final.txt")).write_text(Path("mid.txt").read_text() + "!")
    found = {r["name"]: r for r in records(workdir)}
    assert found["outer"]["undeclared_reads"] == []


def test_track_records_its_script_and_inline_source(workdir: Path) -> None:
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if not k.startswith("CHRONEX_")}
    Path("job.py").write_text("import chronex\nchronex.track(n=1)\n")
    subprocess.run([sys.executable, "job.py"], cwd=workdir, env=env, check=True)
    code = "import chronex; chronex.track()"
    subprocess.run([sys.executable, "-c", code], cwd=workdir, env=env, check=True)
    found = {r["name"]: r for r in records(workdir)}
    assert found["job"]["code"]["entry"] == os.path.realpath(workdir / "job.py")
    assert found["inline"]["code"]["inline"]["source"] == code


def test_a_named_decorator_records_its_parameters(workdir: Path) -> None:
    @chronex.step("scaled", alpha=2)
    def scale(target: Out[Path], factor: int = 3) -> None:
        target.write_text("x")

    scale(Path("out"))
    (record,) = records(workdir)
    assert record["name"] == "scaled"
    assert record["params"] == {"alpha": 2, "factor": 3}


def test_code_from_stdin_is_flagged(workdir: Path) -> None:
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if not k.startswith("CHRONEX_")}
    code = "import chronex; chronex.track()"
    subprocess.run([sys.executable, "-"], input=code, text=True, cwd=workdir, env=env, check=True)
    (record,) = records(workdir)
    assert record["name"] == "stdin"
    assert record["code"]["unrecorded"] == "read from stdin"
    graph = graphs.build([record])
    assert [f.code for _, f in graph.all_flags()] == ["unrecorded-code"]


def test_a_step_in_a_quarto_cell_records_the_document_and_the_cell(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys
    import types

    shell = types.SimpleNamespace(user_ns={"In": ["", "with chronex.step('plot'):\n    pass"]})
    ipython = types.ModuleType("IPython")
    ipython.get_ipython = lambda: shell  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "IPython", ipython)
    monkeypatch.setenv("QUARTO_DOCUMENT_PATH", str(workdir))
    monkeypatch.setenv("QUARTO_DOCUMENT_FILE", "index.qmd")
    Path("index.qmd").write_text("# a document")
    with chronex.step("plot"):
        pass
    (record,) = records(workdir)
    assert record["code"]["entry"] == os.path.realpath("index.qmd")
    assert str(workdir.resolve() / "index.qmd") in record["code"]["files"]
    assert record["code"]["inline"]["source"] == "with chronex.step('plot'):\n    pass"
