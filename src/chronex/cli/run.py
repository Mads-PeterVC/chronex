"""`chronex run`: record a command without changing its code."""

from __future__ import annotations

import sys

import rich_click as click

from chronex.runner import run as record_command

# Options that take one or more values, as in `--in data/*.csv`; see expand_values.
MULTIPLE = ("--in", "--out", "--watch")


def expand_values(argv: list[str]) -> list[str]:
    """Rewrite `run --in a b` as `run --in a --in b`, as click options take one value each.

    Values run until the next option or `--`, which ends chronex's options; the command after
    it is left alone.
    """
    if argv[:1] != ["run"]:
        return argv
    expanded, option = ["run"], None
    for i, token in enumerate(argv[1:], start=1):
        if token == "--":
            return expanded + argv[i:]
        if token.startswith("-"):
            option = token if token in MULTIPLE else None
            if option is None:
                expanded.append(token)
        elif option is not None:
            expanded += [option, token]
        else:
            expanded.append(token)
    return expanded


@click.command(
    short_help="Run a command and record it without changing its code.",
    context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False},
    epilog="Exit code: the command's own, or 128 + the signal that killed it.",
)
@click.option("--in", "inputs", multiple=True, metavar="PATH…", help="Input paths or globs.")
@click.option("--out", "outputs", multiple=True, metavar="PATH…", help="Output paths.")
@click.option(
    "--watch", multiple=True, metavar="DIR…", help="Directories whose changes are outputs."
)
@click.option("--name", help="Step name (default: the command, or the Python script).")
@click.option("-q", "--quiet", is_flag=True, help="Do not report what was recorded.")
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
def run(
    inputs: tuple[str, ...],
    outputs: tuple[str, ...],
    watch: tuple[str, ...],
    name: str | None,
    quiet: bool,
    command: tuple[str, ...],
) -> int:
    """Run COMMAND and record it, e.g. chronex run --in a.csv --out b.csv -- sort -o b.csv a.csv

    Python processes it starts record themselves, with every file they open. Declare the files
    of anything else with --in, --out or --watch, each followed by one or more paths, and end
    chronex's options with --."""
    if not command:
        print(
            "chronex run: give the command after --, e.g. chronex run --in a.csv -- sort a.csv",
            file=sys.stderr,
        )
        return 2
    return record_command(
        list(command),
        inputs=list(inputs),
        outputs=list(outputs),
        watch=list(watch),
        name=name,
        quiet=quiet,
    )
