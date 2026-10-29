import contextlib
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
