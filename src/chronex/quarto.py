"""Figures with their provenance in a Quarto document: a tabset of the figure and its lineage.

In a Python cell:

    import chronex.quarto as cq

    cq.figure("results/fit.png", caption="Fit quality")  # a figure the pipeline wrote

    with cq.make_figure("figures/residuals.png", caption="Residuals") as s:  # made here
        data = np.load(s.input("fits/all.npy"))
        ...
        plt.savefig("figures/residuals.png")

The provenance tab draws the figure's lineage with Graphviz (one node per step; hover a step for
its parameters, code version and flags). Quarto renders it; no Graphviz install is needed.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from chronex import graph as graphs
from chronex.api import step
from chronex.dot import Lineage, lineage, to_dot
from chronex.record import Step

# Directories searched for records; set to include a pipeline's directory elsewhere.
roots: list[str] = ["."]

FENCE = "`" * 3
# Graphviz puts a tooltip on a link's title attribute, which browsers do not show inside SVG;
# this turns each into the <title> element they do show, and keeps the links from navigating.
SCRIPT = """
```{=html}
<script>
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".chronex-lineage svg a[title]").forEach((a) => {
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = a.getAttribute("title");
    a.prepend(title);
    a.removeAttribute("title");
    a.removeAttribute("href");
    a.style.cursor = "default";
  });
});
</script>
```
"""
_script_shown = False


def figure(
    path: str | os.PathLike[str],
    caption: str | None = None,
    *,
    label: str | None = None,
    search: list[str] | None = None,
) -> str:
    """Show a figure in a tabset with its provenance, and return the markdown.

    `label` gives the figure a cross-reference id (`fig-<label>`); `search` overrides `roots`.
    """
    text = markdown(path, caption, label=label, search=search)
    _display(text)
    return text


@contextmanager
def make_figure(
    path: str | os.PathLike[str],
    caption: str | None = None,
    *,
    name: str | None = None,
    label: str | None = None,
    search: list[str] | None = None,
    **params: Any,
) -> Iterator[Step]:
    """Record the code in the block as a step that writes the figure, then show it.

    The step is named after the figure unless `name` is given; declare its inputs with
    `s.input(path)`. Keyword arguments are the step's parameters.
    """
    with step(name or Path(path).stem, **params) as s:
        s.output(path)
        yield s
    figure(path, caption, label=label, search=search)


def markdown(
    path: str | os.PathLike[str],
    caption: str | None = None,
    *,
    label: str | None = None,
    search: list[str] | None = None,
) -> str:
    """The tabset for a figure: the figure, then its lineage."""
    global _script_shown
    rel = os.fspath(path)
    graph = graphs.build(graphs.load(*(search or roots)))
    ident = f"#fig-{label}" if label else ""
    image = f"![{caption or ''}]({rel})" + (f"{{{ident}}}" if ident else "")
    try:
        found = lineage(graph, rel)
    except LookupError as error:
        tab, body = "Provenance", f"No recorded lineage: {error}."
    else:
        flagged = found.count("error") + found.count("warn")
        tab = "Provenance" + (f" ⚠ {flagged}" if flagged else "")
        body = "\n".join(
            [
                "::: {.chronex-lineage}",
                f"{FENCE}{{dot}}",
                to_dot(found).rstrip(),
                FENCE,
                ":::",
                "",
                summary(found),
            ]
        )
    parts = ["::: {.panel-tabset}", "", "## Figure", "", image, "", f"## {tab}", "", body, ""]
    if not _script_shown:
        parts.append(SCRIPT)
        _script_shown = True
    parts.append(":::")
    return "\n".join(parts) + "\n"


def summary(found: Lineage) -> str:
    """One line under the graph: flags, size, origins and code version."""
    errors, warnings = found.count("error"), found.count("warn")
    parts = []
    if errors:
        parts.append(f"**{errors} {'error' if errors == 1 else 'errors'}**")
    if warnings:
        parts.append(f"**{warnings} {'warning' if warnings == 1 else 'warnings'}**")
    if not errors and not warnings:
        parts.append("no flags")
    steps, runs = len(found.steps), found.runs
    parts.append(
        f"{steps} {'step' if steps == 1 else 'steps'}" + (f" ({runs} runs)" if runs > steps else "")
    )
    origins = {p for paths in found.origins.values() for p in paths}
    parts.append(f"{len(origins)} origin {'file' if len(origins) == 1 else 'files'}")
    if found.commits:
        parts.append("code " + ", ".join(f"`{c}`" for c in sorted(found.commits)))
    return " · ".join(parts) + ". Hover a step for its parameters, code and flags."


def _display(text: str) -> None:
    """As markdown in a notebook or a Quarto cell, else as text."""
    ipython = sys.modules.get("IPython")
    if ipython is not None and ipython.get_ipython() is not None:
        from IPython.display import Markdown, display  # type: ignore[import-not-found, unused-ignore]

        display(Markdown(text))
    else:
        print(text)
