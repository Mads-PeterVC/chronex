"""The flags a linked graph raises: failures, superseded and mixed inputs, missing outputs."""

import contextlib
import json
from pathlib import Path

import chronex
from chronex import In, Out
from chronex import graph as graphs
from tests.helpers import codes, copy, make, use


def test_rerun_supersedes_and_mixes(workdir: Path) -> None:
    make(Path("a"), "v1")
    use(Path("a"), Path("b1"))
    make(Path("a"), "v2")
    use(Path("a"), Path("b2"))

    @chronex.step
    def combine(parts: In[list[Path]], target: Out[Path]) -> None:
        target.write_text("".join(p.read_text() for p in parts))

    combine([Path("b1"), Path("b2")], Path("c"))
    graph = graphs.build(graphs.load(workdir))
    assert codes(graph) == {"superseded-input": ["use"], "mixed-lineage": ["combine"]}


def test_failed_producer(workdir: Path) -> None:
    @chronex.step
    def flaky(target: Out[Path]) -> None:
        target.write_text("written")
        raise RuntimeError("after writing")

    with contextlib.suppress(RuntimeError):
        flaky(Path("a"))
    use(Path("a"), Path("b"))
    graph = graphs.build(graphs.load(workdir))
    assert codes(graph) == {"failed": ["flaky"], "failed-producer": ["use"]}


def test_a_cycle_of_links_does_not_crash(workdir: Path) -> None:
    Path("a").write_text("content copied back and forth between two files " * 2)
    copy(Path("a"), Path("b"))
    copy(Path("b"), Path("a"))
    # Equal timestamps (coarse clocks, or one clock across fast steps) allow a cycle.
    for record in graphs.load(workdir):
        record["started"] = record["ended"] = "2026-01-01T00:00:00.000+00:00"
        Path(record.pop("_file")).write_text(json.dumps(record))
    graph = graphs.build(graphs.load(workdir))
    assert len(graph.records) == 2


def test_a_failure_is_reported_once_at_the_innermost_step(workdir: Path) -> None:
    @chronex.step
    def inner() -> None:
        raise ValueError("deep down")

    with contextlib.suppress(ValueError), chronex.step("outer"):
        inner()
    graph = graphs.build(graphs.load(workdir))
    assert codes(graph) == {"failed": ["inner"]}


def test_a_failed_step_is_not_also_missing_its_outputs(workdir: Path) -> None:
    @chronex.step
    def broken(target: Out[Path]) -> None:
        raise RuntimeError("before writing")

    with contextlib.suppress(RuntimeError):
        broken(Path("out/never.txt"))

    @chronex.step
    def lazy(target: Out[Path]) -> None:
        pass

    lazy(Path("out/never.txt"))
    graph = graphs.build(graphs.load(workdir))
    assert codes(graph) == {"missing-output": ["lazy"], "failed": ["broken"]}
    (text,) = [f.text for _, f in graph.all_flags() if f.code == "missing-output"]
    assert text == "declared output out/never.txt was not written"


def test_flag_times_say_they_are_utc(workdir: Path) -> None:
    make(Path("a"), "v1")
    use(Path("a"), Path("b1"))
    make(Path("a"), "v2")
    graph = graphs.build(graphs.load(workdir))
    (text,) = [f.text for _, f in graph.all_flags() if f.code == "superseded-input"]
    assert text.count(" UTC") == 2


def test_superseded_input_names_one_path_and_what_to_rerun(workdir: Path) -> None:
    Path("sub").mkdir()
    make(Path("sub/a"), "v1")
    use(Path("sub/a"), Path("b"))
    make(Path("sub/a"), "v2")
    graph = graphs.build(graphs.load(workdir))
    (text,) = [f.text for _, f in graph.all_flags() if f.code == "superseded-input"]
    assert text.count("sub/a") == 2
    assert text.endswith("re-run use to use the new version")
