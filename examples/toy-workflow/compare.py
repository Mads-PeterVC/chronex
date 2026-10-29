"""How much does each way of recording add to the scripts? Compares every variant to ``plain``.

    uv run python examples/toy-workflow/compare.py            # prints a Markdown table

Counts, per variant and summed over the eight scripts:

* added: lines that are new in the variant;
* changed: lines of plain that are modified (re-indenting counts as a change);
* chronex lines: lines that mention chronex at all (imports, decorators, declarations);
* in place: ``plain`` lines kept byte-for-byte.
"""

from __future__ import annotations

import ast
import difflib
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
VARIANTS = ["decorator", "block", "script", "mixed"]
SCRIPTS = ["generate", "label", "collect", "fit", "stage", "scan", "export", "plot"]
MENTIONS = re.compile(r"chronex|\bIn\[|\bOut\[|\bs\.(input|output)\(")


def code_lines(path: Path) -> list[str]:
    """Lines that are code: no blanks, comments, or the module docstring."""
    source = path.read_text()
    lines = source.splitlines()
    body = ast.parse(source).body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        lines = lines[body[0].end_lineno or 0 :]
    return [line for line in lines if line.strip() and not line.strip().startswith("#")]


def compare(variant: str, script: str) -> dict[str, int]:
    plain = code_lines(HERE / "variants" / "plain" / f"{script}.py")
    other = code_lines(HERE / "variants" / variant / f"{script}.py")
    added = changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, plain, other).get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "replace":
            changed += min(i2 - i1, j2 - j1)
            added += max(0, (j2 - j1) - (i2 - i1))
        elif tag == "delete":
            changed += i2 - i1
    kept = sum(1 for line in other if line in plain)
    return {
        "plain": len(plain),
        "lines": len(other),
        "added": added,
        "changed": changed,
        "mentions": sum(1 for line in other if MENTIONS.search(line)),
        "kept": kept,
    }


def main() -> None:
    plain = sum(compare("decorator", s)["plain"] for s in SCRIPTS)
    print(f"| Variant | Code lines (plain: {plain}) | Added | Changed | chronex lines | Kept |")
    print("|---|---:|---:|---:|---:|---:|")
    for variant in VARIANTS:
        rows = [compare(variant, s) for s in SCRIPTS]
        total = {k: sum(r[k] for r in rows) for k in rows[0]}
        print(
            f"| {variant} | {total['lines']} | {total['added']} | {total['changed']} | "
            f"{total['mentions']} | {100 * total['kept'] / total['plain']:.0f}% |"
        )
    print("| wrapper | 0 changes: the plain scripts, run through `chronex run --` | | | | 100% |")
    print()
    print("Per script, added + changed lines:")
    print()
    print("| Script | " + " | ".join(VARIANTS) + " |")
    print("|---|" + "---:|" * len(VARIANTS))
    for script in SCRIPTS:
        cells = []
        for variant in VARIANTS:
            r = compare(variant, script)
            cells.append(f"{r['added']} + {r['changed']}")
        print(f"| {script} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
