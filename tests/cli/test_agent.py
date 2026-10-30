"""`chronex agent install-skill` copies the packaged skill for Claude Code."""

from pathlib import Path

import pytest

from chronex.cli import main


def test_install_skill_into_the_project_and_refuse_to_overwrite(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["agent", "install-skill", "--project"]) == 0
    skill = workdir / ".claude" / "skills" / "chronex" / "SKILL.md"
    assert skill.read_text().startswith("---\nname: chronex\n")
    assert "QUARTO_PYTHON" in skill.read_text()
    skill.write_text("edited")
    assert main(["agent", "install-skill", "--project"]) == 1
    assert "already exists" in capsys.readouterr().err
    assert main(["agent", "install-skill", "--project", "--overwrite"]) == 0
    assert skill.read_text().startswith("---\nname: chronex\n")


def test_install_skill_for_all_projects(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(workdir))
    assert main(["agent", "install-skill"]) == 0
    assert (workdir / ".claude" / "skills" / "chronex" / "SKILL.md").is_file()
