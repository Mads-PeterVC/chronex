# Phase 3: figures with their provenance, in Quarto

**Date:** 2026-10-30

**Question:** Can a figure's provenance be shown next to it in a Quarto site, at a level of
detail someone checking their own work, or a collaborator, can take in at a glance?

**Background:** `chronex report` showed that the records hold what is needed, but it shows
every run, file and hash: too much for everyday use.

**Decisions:** A Python call in a cell, not a Quarto extension. The provenance tab draws the
lineage with Graphviz, with one node per step and its runs folded together; parameters, code
and flags go in tooltips. Expanding a step into its runs is left for later.

**Spike:** A ```` ```{dot} ```` block that a cell displays as markdown (an IPython `Markdown`
object, or `output: asis`) is rendered by Quarto like one written in the source, so no
Graphviz install is needed. Two things did not work as hoped:

- Quarto keeps a Graphviz tooltip only as a `title` attribute on a link, which browsers do not
  show inside SVG.
- Quarto draws every diagram in a 7 by 5 inch box, so a long lineage became unreadably small.

A small script in the page fixes both. A chronex step in a Jupyter kernel saw no stray reads,
but recorded `ipykernel_launcher.py` as its code. It now records the document Quarto renders
(from `QUARTO_DOCUMENT_PATH`) and the cell's source.

**Made:**

- `chronex.dot` groups a lineage by step name and writes Graphviz source:
  - nodes coloured by their worst flag, and dashed when a run failed;
  - origin and unrecorded inputs (undeclared, changed, ambiguous) as notes beside the step
    that read them;
  - edges labelled with files.
- `chronex show FILE --dot` prints it.
- `chronex.quarto`:
  - `figure(path)` shows a tabset with the figure and its lineage, with a one-line summary
    and a flag count in the tab title;
  - `make_figure(path)` records the cell that draws a figure as a step first.
- `examples/quarto/` renders the toy workflow with its planted faults. Its test renders the
  site when Quarto is installed.

**Next:**

- Expand a step into its runs, probably with a little of our own JS, or a second graph per
  step.
- Try it on a real figure from temper, with a sweep of hundreds of runs.
- A site-wide page listing every figure and its flags.
- PDF output, where tooltips do not exist.
