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
    env = {k: v for k, v in os.environ.items() if not k.startswith("CHRONEX_")}
    return subprocess.call([sys.executable, "-m", "chronex.cli", "run", *args], cwd=cwd, env=env)


def by_kind(root: Path) -> tuple[dict, list[dict]]:
    found = graphs.load(root)
    (wrapper,) = [r for r in found if r["parent"] is None]
    return wrapper, [r for r in found if r["parent"] is not None]


def test_python_records_itself_without_changes(workdir: Path) -> None:
    Path("in.txt").write_text("hello")
    Path("script.py").write_text(SCRIPT)
    assert chronex_run("--", sys.executable, "script.py", cwd=workdir) == 0
    wrapper, (record,) = by_kind(workdir)
    assert record["name"] == "script"
    assert record["auto"] is True
    assert record["parent"] == wrapper["id"]
    assert wrapper["params"]["argv"] == [sys.executable, "script.py"]
    assert [i["rel"] for i in record["inputs"]] == ["in.txt"]
    assert [o["rel"] for o in record["outputs"]] == ["out.txt"]
    script = os.path.realpath(workdir / "script.py")
    assert record["code"]["entry"] == script
    assert script in record["code"]["files"]


def test_name_applies_to_the_recorded_python_process(workdir: Path) -> None:
    Path("in.txt").write_text("hello")
    Path("script.py").write_text(SCRIPT)
    assert chronex_run("--name", "shout", "--", sys.executable, "script.py", cwd=workdir) == 0
    wrapper, (record,) = by_kind(workdir)
    assert record["name"] == wrapper["name"] == "shout"


def test_inline_python_records_its_source(workdir: Path) -> None:
    Path("in.txt").write_text("hello")
    assert chronex_run("--", sys.executable, "-c", SCRIPT, cwd=workdir) == 0
    _, (record,) = by_kind(workdir)
    assert record["name"] == "inline"
    assert record["code"]["inline"]["source"] == SCRIPT


def test_exit_code_marks_failure(workdir: Path) -> None:
    Path("script.py").write_text("import sys; sys.exit(3)")
    assert chronex_run("--", sys.executable, "script.py", cwd=workdir) == 3
    wrapper, (record,) = by_kind(workdir)
    assert record["status"] == wrapper["status"] == "failed"
    assert wrapper["error"] == "exit code 3"


def test_a_command_with_nothing_declared_warns(workdir: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CHRONEX_")}
    result = subprocess.run(
        [sys.executable, "-m", "chronex.cli", "run", "--", "sh", "-c", "echo 1 > x"],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--in" in result.stderr
    assert "recorded" in result.stderr


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
