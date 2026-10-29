import contextlib
import json
import shutil
from pathlib import Path

import chronex
from chronex import In, Out
from chronex import graph as graphs


@chronex.step
def make(target: Out[Path], value: str) -> None:
    target.write_text(value)


@chronex.step
def copy(source: In[Path], target: Out[Path]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


@chronex.step
def use(source: In[Path], target: Out[Path]) -> None:
    target.write_text(source.read_text() + "!")


def codes(graph: graphs.Graph) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for sid, flag in graph.all_flags():
        if flag.level != "info":
            found.setdefault(flag.code, []).append(graph.records[sid]["name"])
    return found


def test_copies_link_by_content(workdir: Path) -> None:
    make(Path("a"), "v1")
    copy(Path("a"), Path("staged/a"))
    use(Path("staged/a"), Path("b"))
    graph = graphs.build(graphs.load(workdir))
    assert codes(graph) == {}
    (user,) = [r for r in graph.records.values() if r["name"] == "use"]
    (link,) = graph.links[user["id"]]
    assert graph.records[link.producer]["name"] == "copy"
    assert {graph.records[s]["name"] for s in graph.ancestry(user["id"])} == {"make", "copy"}


def test_edit_between_steps_is_an_error(workdir: Path) -> None:
    make(Path("a"), "v1")
    Path("a").write_text("edited by hand")
    use(Path("a"), Path("b"))
    graph = graphs.build(graphs.load(workdir))
    assert codes(graph) == {"modified-after-write": ["use"]}


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


def test_directory_outputs_link_to_files_inside(workdir: Path) -> None:
    @chronex.step
    def many(folder: Out[Path]) -> None:
        folder.mkdir()
        for i in range(3):
            (folder / f"{i}.txt").write_text(str(i))

    many(Path("folder"))
    use(Path("folder/1.txt"), Path("b"))
    graph = graphs.build(graphs.load(workdir))
    (user,) = [r for r in graph.records.values() if r["name"] == "use"]
    assert graph.records[graph.links[user["id"]][0].producer]["name"] == "many"


def link_of(graph: graphs.Graph, name: str) -> graphs.Link:
    (record,) = [r for r in graph.records.values() if r["name"] == name]
    (link,) = graph.links[record["id"]]
    return link


def test_a_producer_must_finish_before_the_consumer_starts(workdir: Path) -> None:
    content = "the same bytes, long enough to count as real content " * 2
    Path("x").write_text(content)
    use(Path("x"), Path("y"))
    make(Path("z"), content)
    graph = graphs.build(graphs.load(workdir))
    assert link_of(graph, "use").origin
    assert codes(graph) == {}


def test_a_later_write_to_an_input_path_is_not_a_modification(workdir: Path) -> None:
    Path("cfg").write_text("v1")
    use(Path("cfg"), Path("out"))
    make(Path("cfg"), "v2")
    graph = graphs.build(graphs.load(workdir))
    assert codes(graph) == {}


def test_unrelated_producers_of_the_same_content_are_ambiguous(workdir: Path) -> None:
    content = "identical output from two unrelated steps, long enough to count " * 2
    make(Path("a"), content)
    make(Path("b"), content)
    shutil.copyfile("a", "c")  # an unrecorded copy: either step could be the source
    use(Path("c"), Path("d"))
    graph = graphs.build(graphs.load(workdir))
    link = link_of(graph, "use")
    assert link.producer is None and not link.origin
    assert len(link.ambiguous) == 2
    assert codes(graph) == {"ambiguous-input": ["use"]}


def test_copies_of_one_original_are_not_ambiguous(workdir: Path) -> None:
    content = "one original, copied by a recorded step and then by hand, still links " * 2
    make(Path("a"), content)
    copy(Path("a"), Path("staged/a"))
    shutil.copyfile("staged/a", "elsewhere")
    use(Path("elsewhere"), Path("d"))
    graph = graphs.build(graphs.load(workdir))
    assert graph.records[link_of(graph, "use").producer]["name"] == "copy"


def test_trivial_content_does_not_link_across_paths(workdir: Path) -> None:
    make(Path("a"), "")
    shutil.copyfile("a", "c")
    use(Path("c"), Path("d"))
    graph = graphs.build(graphs.load(workdir))
    link = link_of(graph, "use")
    assert link.producer is None and link.ambiguous
    flags = [f for sid, f in graph.all_flags() if f.code == "ambiguous-input"]
    assert [f.level for f in flags] == ["info"]


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
