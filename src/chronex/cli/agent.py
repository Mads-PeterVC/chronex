"""`chronex agent install-skill`: the chronex skill for Claude Code."""

from __future__ import annotations

import shutil
from importlib.resources import as_file, files
from pathlib import Path

import rich_click as click


@click.group()
def agent() -> None:
    """Commands for using chronex with AI agents."""


@agent.command(name="install-skill")
@click.option(
    "--project",
    is_flag=True,
    help="Install into .claude/skills of the current directory instead of ~/.claude/skills.",
)
@click.option("-o", "--overwrite", is_flag=True, help="Replace an installed skill.")
def install_skill(project: bool, overwrite: bool) -> None:
    """Install the chronex skill for Claude Code, which tells agents how to mark up steps,
    check a lineage and show figures with their provenance in Quarto."""
    base = Path.cwd() if project else Path.home()
    target = base / ".claude" / "skills" / "chronex" / "SKILL.md"
    if target.exists() and not overwrite:
        raise click.ClickException(f"{target} already exists; --overwrite replaces it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with as_file(files("chronex.agent") / "SKILL.md") as source:
        shutil.copy(source, target)
    click.echo(f"Installed the chronex skill to {target}.")
