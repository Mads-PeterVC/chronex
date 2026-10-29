import os
import subprocess
import sys
from pathlib import Path

from chronex import graph as graphs

SCRIPT = """
from pathlib import Path
text = Path("in.txt").read_text()
Path("out.txt").write_text(text.upper())
"""


def chronex_run(*args: str, cwd: Path) -> int:
    env = dict(os.environ)
    env.pop("CHRONEX_AUTO", None)
    return subprocess.call([sys.executable, "-m", "chronex.cli", "run", *args], cwd=cwd, env=env)


def test_python_records_itself_without_changes(workdir: Path) -> None:
    Path("in.txt").write_text("hello")
    Path("script.py").write_text(SCRIPT)
    assert chronex_run("--", sys.executable, "script.py", cwd=workdir) == 0
    (record,) = graphs.load(workdir)
    assert record["name"] == "script"
    assert record["auto"] is True
    assert [i["rel"] for i in record["inputs"]] == ["in.txt"]
    assert [o["rel"] for o in record["outputs"]] == ["out.txt"]


def test_exit_code_marks_failure(workdir: Path) -> None:
    Path("script.py").write_text("import sys; sys.exit(3)")
    assert chronex_run("--", sys.executable, "script.py", cwd=workdir) == 3
    (record,) = graphs.load(workdir)
    assert record["status"] == "failed"


def test_other_commands_use_declared_inputs_and_watched_outputs(workdir: Path) -> None:
    Path("in.txt").write_text("hello")
    Path("results").mkdir()
    code = chronex_run(
        "--in",
        "in.txt",
        "--watch",
        "results",
        "--name",
        "copy",
        "--",
        "cp",
        "in.txt",
        "results/out.txt",
        cwd=workdir,
    )
    assert code == 0
    (record,) = graphs.load(workdir)
    assert record["name"] == "copy"
    assert [i["rel"] for i in record["inputs"]] == ["in.txt"]
    assert [o["rel"] for o in record["outputs"]] == ["results/out.txt"]
