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


def env_without_chronex() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("CHRONEX_")}


def test_python_records_itself_without_changes(workdir: Path) -> None:
    Path("in.txt").write_text("hello")
    Path("script.py").write_text(SCRIPT)
    assert chronex_run("--", sys.executable, "script.py", cwd=workdir) == 0
    (record,) = graphs.load(workdir)  # the command adds nothing to what Python recorded
    assert record["name"] == "script"
    assert record["auto"] is True
    assert record["parent"] is None
    assert [i["rel"] for i in record["inputs"]] == ["in.txt"]
    assert [o["rel"] for o in record["outputs"]] == ["out.txt"]
    script = os.path.realpath(workdir / "script.py")
    assert record["code"]["entry"] == script
    assert script in record["code"]["files"]


def test_name_applies_to_the_recorded_python_process(workdir: Path) -> None:
    Path("in.txt").write_text("hello")
    Path("script.py").write_text(SCRIPT)
    assert chronex_run("--name", "shout", "--", sys.executable, "script.py", cwd=workdir) == 0
    (record,) = graphs.load(workdir)
    assert record["name"] == "shout"


def test_inline_python_records_its_source(workdir: Path) -> None:
    Path("in.txt").write_text("hello")
    assert chronex_run("--", sys.executable, "-c", SCRIPT, cwd=workdir) == 0
    (record,) = graphs.load(workdir)
    assert record["name"] == "inline"
    assert record["code"]["inline"]["source"] == SCRIPT


def test_exit_code_marks_failure(workdir: Path) -> None:
    Path("script.py").write_text("import sys; sys.exit(3)")
    assert chronex_run("--", sys.executable, "script.py", cwd=workdir) == 3
    (record,) = graphs.load(workdir)
    assert record["status"] == "failed"
    assert record["error"] == "exit code 3"


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


def test_one_flag_takes_several_paths(workdir: Path) -> None:
    Path("a.txt").write_text("a")
    Path("b.txt").write_text("b")
    command = [
        "--in",
        "a.txt",
        "b.txt",
        "--out",
        "c.txt",
        "--",
        "sh",
        "-c",
        "cat a.txt b.txt > c.txt",
    ]
    assert chronex_run(*command, cwd=workdir) == 0
    (record,) = graphs.load(workdir)
    assert [i["rel"] for i in record["inputs"]] == ["a.txt", "b.txt"]


def test_a_command_that_cannot_run_is_a_clear_error(workdir: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "chronex.cli", "run", "--", "./no-such-program"],
        cwd=workdir,
        env=env_without_chronex(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 127
    assert result.stderr.startswith("chronex run: cannot run ./no-such-program")
    assert "Traceback" not in result.stderr
    assert graphs.load(workdir) == []


SLOW = """
import sys, time
from pathlib import Path
Path("a.txt").write_text("half")
print("ready", flush=True)
time.sleep(30)
"""


def test_sigterm_reaches_the_command_and_is_recorded(workdir: Path) -> None:
    import signal

    command = ["run", "--name", "slow", "--out", "a.txt", "--", sys.executable, "-c", SLOW]
    process = subprocess.Popen(
        [sys.executable, "-m", "chronex.cli", *command],
        cwd=workdir,
        env=env_without_chronex(),
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None and process.stdout.readline().strip() == "ready"
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=20) == 128 + signal.SIGTERM
    wrapper, (child,) = by_kind(workdir)
    assert wrapper["status"] == child["status"] == "failed"
    assert wrapper["error"] == child["error"] == "killed: SIGTERM"
    assert wrapper["outputs"][0]["kind"] == "file"


def test_a_declared_file_that_is_missing_is_reported_at_once(workdir: Path) -> None:
    declared = ["--in", "nope.csv", "--out", "never.txt"]
    result = subprocess.run(
        [sys.executable, "-m", "chronex.cli", "run", *declared, "--", "true"],
        cwd=workdir,
        env=env_without_chronex(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0  # the command's own exit code
    assert "declared input nope.csv did not exist" in result.stderr
    assert "declared output never.txt was not written" in result.stderr
