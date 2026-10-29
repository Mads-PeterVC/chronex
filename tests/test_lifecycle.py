import os
import signal
import subprocess
import sys
from pathlib import Path

from chronex import graph as graphs

KILLED = """
import sys, time
from pathlib import Path
import chronex
chronex.track()
Path(chronex.output("partial.txt")).write_text("half")
print("ready", flush=True)
time.sleep(30)
"""

VANISHED = """
import os
from pathlib import Path
import chronex
with chronex.step("vanish", n=1) as s:
    Path(s.output("partial.txt")).write_text("half")
    os._exit(1)  # SIGKILL, an out-of-memory kill or a node failure: nothing runs after this
"""


def start(script: str, workdir: Path) -> subprocess.Popen[str]:
    Path("job.py").write_text(script)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CHRONEX_")}
    return subprocess.Popen(
        [sys.executable, "job.py"], cwd=workdir, env=env, stdout=subprocess.PIPE, text=True
    )


def test_sigterm_finishes_the_step_as_failed(workdir: Path) -> None:
    process = start(KILLED, workdir)
    assert process.stdout is not None and process.stdout.readline().strip() == "ready"
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=20) == -signal.SIGTERM
    (record,) = graphs.load(workdir)
    assert record["status"] == "failed"
    assert record["error"] == "killed: SIGTERM"
    assert record["outputs"][0]["kind"] == "file"


def test_a_step_that_never_finished_is_incomplete(workdir: Path) -> None:
    assert start(VANISHED, workdir).wait(timeout=20) == 1
    (record,) = graphs.load(workdir)
    assert record["status"] == "running"
    assert record["params"] == {"n": 1}
    graph = graphs.build([record])
    assert [f.code for _, f in graph.all_flags()] == ["incomplete"]


def test_a_user_sigterm_handler_is_left_alone(workdir: Path) -> None:
    import chronex

    def handler(signum: int, frame: object) -> None: ...

    previous = signal.signal(signal.SIGTERM, handler)
    try:
        with chronex.step("polite"):
            assert signal.getsignal(signal.SIGTERM) is handler
        assert signal.getsignal(signal.SIGTERM) is handler
    finally:
        signal.signal(signal.SIGTERM, previous)


def test_the_default_sigterm_handler_is_restored(workdir: Path) -> None:
    import chronex

    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
    with chronex.step("outer"), chronex.step("inner"):
        assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
