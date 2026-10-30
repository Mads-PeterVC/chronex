"""`chronex forget`: retiring records that should not count."""

import contextlib
from pathlib import Path

import pytest

import chronex
from chronex.cli import main
from tests.helpers import check, make


def test_forget_retires_a_failed_experiment(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make(Path("a"), "v1")
    with contextlib.suppress(RuntimeError), chronex.step("experiment"):
        raise RuntimeError("did not work")
    assert check("--strict", capsys=capsys)[0] == 1
    assert main(["forget", "experiment"]) == 0
    assert "forgot experiment" in capsys.readouterr().out
    assert check("--strict", capsys=capsys)[0] == 0
    assert len(list(Path(".chronex/forgotten").glob("*.json"))) == 1
    assert main(["forget", "nothing-by-this-name"]) == 2
