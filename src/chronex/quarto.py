"""Figures with their provenance in a Quarto document: a tabset of the figure and its lineage.

In a Python cell:

    import chronex.quarto as cq

    cq.figure("results/fit.png", caption="Fit quality")  # a figure the pipeline wrote

    with cq.make_figure("figures/residuals.png", caption="Residuals") as s:  # made here
        data = np.load(s.input("fits/all.npy"))
        ...
        plt.savefig("figures/residuals.png")

The provenance tab draws the figure's lineage with Graphviz (one node per step; hover a step for
its parameters and code version), and lists its flags. Quarto renders it; no Graphviz install
is needed.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from chronex import graph as graphs
from chronex.dot import Lineage, lineage, to_dot
from chronex.recording.markup import step
from chronex.recording.step import Step

# Directories searched for records; set to include a pipeline's directory elsewhere.
roots: list[str] = ["."]

FENCE = "`" * 3
MAX_FLAGS = 12  # listed under a graph; the rest are counted
# Quarto draws every diagram in a 7 by 5 inch box, which shrinks a long lineage; this gives
# each graph its natural size (Graphviz points, at 96 px per inch), up to the column width.
# Graphviz keeps a tooltip as a link's title attribute, which browsers do not show inside SVG
# (and native tooltips are slow, and unreliable in Safari): this shows it in a box of its own,
# at once, beside the pointer.
SCRIPT = """
```{=html}
<style>
.chronex-tip { position: fixed; z-index: 1000; display: none; max-width: 480px;
  padding: 6px 9px; background: #fff; color: #2f343a; border: 1px solid #c7ccd1;
  border-radius: 4px; box-shadow: 0 2px 8px rgba(0, 0, 0, .15); pointer-events: none;
  font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; }
.chronex-lineage svg a { cursor: help; }
</style>
<script>
document.addEventListener("DOMContentLoaded", () => {
  const tip = document.createElement("div");
  tip.className = "chronex-tip";
  document.body.append(tip);
  const place = (event) => {
    const x = event.clientX + 14, y = event.clientY + 14;
    tip.style.left = Math.max(4, Math.min(x, innerWidth - tip.offsetWidth - 8)) + "px";
    tip.style.top = (y + tip.offsetHeight > innerHeight - 8
      ? Math.max(4, event.clientY - tip.offsetHeight - 10) : y) + "px";
  };
  document.querySelectorAll(".chronex-lineage svg").forEach((svg) => {
    const box = svg.viewBox.baseVal;
    if (box && box.width) {
      svg.setAttribute("width", box.width * 4 / 3);
      svg.setAttribute("height", box.height * 4 / 3);
      Object.assign(svg.style, { maxWidth: "100%", height: "auto", display: "block",
        margin: "0 auto" });
    }
    svg.querySelectorAll("title").forEach((title) => title.remove());  // node ids
    const xlink = "http://www.w3.org/1999/xlink";
    svg.querySelectorAll("a[title], a[*|title]").forEach((a) => {
      const text = a.getAttribute("title") || a.getAttributeNS(xlink, "title");
      a.removeAttribute("title");
      a.removeAttributeNS(xlink, "title");
      a.removeAttribute("href");
      a.removeAttributeNS(xlink, "href");
      a.addEventListener("mouseenter", (event) => {
        tip.textContent = text.replace(/\u00a0/g, " ");
        tip.style.display = "block";
        place(event);
      });
      a.addEventListener("mousemove", place);
      a.addEventListener("mouseleave", () => { tip.style.display = "none"; });
    });
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
) -> None:
    """Show a figure in a tabset with its provenance.

    `label` gives the figure a cross-reference id (`fig-<label>`); `search` overrides `roots`.
    """
    _display(markdown(path, caption, label=label, search=search))


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
    graph = graphs.build(graphs.load(*(search or roots)))
    # Markdown paths are relative to the document, which cells need not run in.
    document = os.environ.get("QUARTO_DOCUMENT_PATH") or os.getcwd()
    shown = os.path.relpath(os.path.abspath(path), document)
    ident = f"#fig-{label}" if label else ""
    image = f"![{caption or ''}]({shown})" + (f"{{{ident}}}" if ident else "")
    try:
        found = lineage(graph, path)
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
                *flag_list(found),
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
    return " · ".join(parts) + ". Hover a step for its parameters and code."


def flag_list(found: Lineage) -> list[str]:
    """The flags as a list, errors first, then by step: what the colours stand for."""
    entries = sorted(
        (level != "error", name, code, text)
        for name, flags in found.flags.items()
        for level, code, text in flags
    )
    lines = [
        f"- **{'warning' if warn else 'error'}** `{code}` in {_escape(name)}: {_escape(text)}"
        for warn, name, code, text in entries[:MAX_FLAGS]
    ]
    if len(entries) > MAX_FLAGS:
        more = len(entries) - MAX_FLAGS
        lines.append(f"- and {more} more: `chronex check --target {found.target}`")
    return ["", *lines] if lines else []


def _escape(text: str) -> str:
    """Text shown as is in markdown: paths hold underscores and asterisks."""
    return re.sub(r"([\\`*_\[\]<>#|~])", r"\\\1", text)


def _display(text: str) -> None:
    """As markdown in a notebook or a Quarto cell, else as text."""
    ipython = sys.modules.get("IPython")
    if ipython is not None and ipython.get_ipython() is not None:
        from IPython.display import Markdown, display  # type: ignore[import-not-found, unused-ignore]

        display(Markdown(text))  # type: ignore[no-untyped-call, unused-ignore]
    else:
        print(text)
