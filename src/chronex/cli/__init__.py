"""Command line: `chronex run`, `check`, `show`, `report` and `forget`, one module each."""

from __future__ import annotations

import sys

import rich_click as click

from chronex.cli.check import check
from chronex.cli.forget import forget
from chronex.cli.report import report
from chronex.cli.run import expand_values, run
from chronex.cli.show import show


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def chronex() -> None:
    """Provenance records for computational research: what each step read, wrote and ran,
    linked into a lineage you can check."""


for command in (run, check, show, report, forget):
    chronex.add_command(command)


def main(argv: list[str] | None = None) -> int:
    """Run the command line and return its exit code: 2 for wrong arguments."""
    args = expand_values(sys.argv[1:] if argv is None else argv)
    try:
        code = chronex.main(args=args, prog_name="chronex", standalone_mode=False)
    except click.ClickException as error:
        error.show()
        return error.exit_code
    except click.Abort:
        return 130
    return int(code or 0)
