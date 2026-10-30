"""The command group: unknown commands and options, and help."""

import pytest

from chronex.cli import main


def test_wrong_arguments_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "--no-such-option"]) == 2
    assert main(["no-such-command"]) == 2
    assert main(["--help"]) == 0
    assert "forget" in capsys.readouterr().out
