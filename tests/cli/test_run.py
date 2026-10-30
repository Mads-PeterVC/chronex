"""`chronex run`: parsing its options."""

from chronex.cli.run import expand_values


def test_run_options_take_several_values() -> None:
    argv = ["run", "--in", "a", "b", "-q", "--out", "c", "--", "cmd", "--in", "x"]
    assert expand_values(argv) == [
        *["run", "--in", "a", "--in", "b", "-q", "--out", "c"],
        *["--", "cmd", "--in", "x"],
    ]
    assert expand_values(["check", "--target", "a", "b"]) == ["check", "--target", "a", "b"]
