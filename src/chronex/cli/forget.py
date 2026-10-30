"""`chronex forget`: retire records that should not count."""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click

from chronex.cli._common import load


@click.command(
    short_help="Stop counting steps: a failed experiment, a mistaken command.",
    epilog="Moves the records of the given steps, and of steps nested inside them, to "
    ".chronex/forgotten/, where nothing reads them. Move them back to undo.",
)
@click.argument("steps", nargs=-1, required=True)
@click.option(
    "--root",
    "roots",
    multiple=True,
    type=click.Path(file_okay=False),
    help="Directory to search for records (default: .; repeatable).",
)
@click.option("-n", "--dry-run", is_flag=True, help="Only say what would be forgotten.")
def forget(steps: tuple[str, ...], roots: tuple[str, ...], dry_run: bool) -> int:
    """Stop counting STEPS, e.g. a failed experiment or a mistaken command: each a name, or an
    id (or its last 8 characters, as check shows)."""
    graph = load(roots)

    def matches(wanted: str) -> set[str]:
        return {
            sid
            for sid, r in graph.records.items()
            if wanted in (sid, r["name"]) or (len(wanted) >= 8 and sid.endswith(wanted))
        }

    chosen = {sid for wanted in steps for sid in matches(wanted)}
    unknown = [wanted for wanted in steps if not matches(wanted)]
    if unknown:
        print(f"chronex forget: no record matches {', '.join(unknown)}", file=sys.stderr)
        return 2
    # Steps nested inside a forgotten step go with it.
    chosen |= {sid for sid, r in graph.records.items() if chosen & set(r["_enclosing"])}
    verb = "would forget" if dry_run else "forgot"
    for sid in sorted(chosen, key=lambda s: graph.records[s]["started"]):
        record = graph.records[sid]
        print(f"{verb} {record['name']} {sid[-8:]} [{record['status']}] {record['started'][:19]}")
        if not dry_run:
            source = Path(record["_file"])
            target = source.parent / "forgotten" / source.name
            target.parent.mkdir(exist_ok=True)
            source.rename(target)
    users = sorted(
        {
            graph.records[sid]["name"]
            for sid, links in graph.links.items()
            if sid not in chosen and any(lk.producer in chosen for lk in links)
        }
    )
    if users:
        print(f"note: {', '.join(users)} read files these steps wrote; re-run them, or forget them")
    return 0
