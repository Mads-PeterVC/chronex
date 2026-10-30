"""How inputs link to the steps that produced them: by content, in time, through copies."""

import shutil
from pathlib import Path

import chronex
from chronex import In, Out
from chronex import graph as graphs
from tests.helpers import codes, copy, make, use


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


def test_a_directory_input_links_to_the_steps_that_wrote_its_files(workdir: Path) -> None:
    Path("fits").mkdir()
    for i in range(2):
        make(Path(f"fits/run-{i}.json"), f"a fit result, long enough to link by content: {i}")

    @chronex.step
    def aggregate(fits: In[Path], summary: Out[Path]) -> None:
        summary.write_text("".join(p.read_text() for p in sorted(fits.iterdir())))

    aggregate(Path("fits"), Path("summary.txt"))
    graph = graphs.build(graphs.load(workdir))
    (record,) = [r for r in graph.records.values() if r["name"] == "aggregate"]
    assert [i["rel"] for i in record["inputs"]] == ["fits/run-0.json", "fits/run-1.json"]
    producers = {graph.records[lk.producer]["name"] for lk in graph.links[record["id"]]}
    assert producers == {"make"}
    assert codes(graph) == {}


def test_a_directory_of_raw_files_stays_one_origin(workdir: Path) -> None:
    Path("raw").mkdir()
    for i in range(3):
        Path(f"raw/{i}.dat").write_text(str(i))
    with chronex.step("ingest") as s:
        s.input("raw")
        Path(s.output("out")).write_text("x")
    graph = graphs.build(graphs.load(workdir))
    (record,) = graph.records.values()
    assert [i["rel"] for i in record["inputs"]] == ["raw"]
    assert graph.links[record["id"]][0].origin


def test_a_step_links_to_the_output_of_a_step_nested_in_it(workdir: Path) -> None:
    with chronex.step("outer") as outer:
        make(Path("tiny.txt"), "x")
        outer.input("tiny.txt")
        Path(outer.output("total.txt")).write_text(Path("tiny.txt").read_text())
    graph = graphs.build(graphs.load(workdir))
    assert codes(graph) == {}
    (record,) = [r for r in graph.records.values() if r["name"] == "outer"]
    (link,) = graph.links[record["id"]]
    assert graph.records[link.producer]["name"] == "make"
