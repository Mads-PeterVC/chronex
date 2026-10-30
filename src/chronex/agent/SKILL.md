---
name: chronex
description: Use when recording provenance with chronex (chronex.step, chronex.track, chronex run), checking a result's lineage (chronex check, show, report), or showing figures with their provenance in a Quarto document (chronex.quarto).
---

# Recording and checking provenance with chronex

chronex records what each step of a computation read, wrote and ran, one JSON record per
step in `.chronex/` of the directory it ran in. `chronex check` links the records by file
content and flags what does not add up, such as an input changed by hand or a step that
used an old version of a file. chronex must be installed in the environment the steps run in.

## Marking up code

Mark up each piece of code the way that costs least there:

| Code | Use |
|---|---|
| A function | `@chronex.step`, with `In[Path]` / `Out[Path]` on file parameters |
| A script | `chronex.track(**params)` near the top |
| A block, e.g. a notebook cell | `with chronex.step("name", **params) as s:` and `s.input(p)`, `s.output(p)` |
| A shell tool, code you cannot change | `chronex run --name N --in A --out B -- command …` |
| Unmarked Python | `chronex run -- python script.py`: every file it opens is recorded |

- Declare files with `chronex.input(path)` / `chronex.output(path)`, which return `path`.
  Files opened but not declared are flagged `undeclared-read`; declare them rather than
  ignoring the flag.
- A step is named after its function, block name or script; `name=` / `--name` overrides it.
- `chronex run` sees nothing inside a non-Python command: declare its files with `--in`,
  `--out` or `--watch`, before the `--`.

## Checking

```
chronex check [ROOTS…]            # all current steps below ROOTS (default .)
chronex check --target FILE       # only FILE's lineage
chronex show FILE                 # the steps FILE came from, as a tree
```

- `check` exits 1 on an error, and on a warning only with `--strict`. Use `--strict` to gate
  work, and read warnings even when it exits 0.
- After fixing a stale input, re-run the step that used it and every step after it. A
  re-run step replaces its older runs, so they no longer count.
- `chronex forget STEP` retires a mistaken or failed run. Ask the user before forgetting a
  step: it hides the run from every later check.
- Never edit or delete records in `.chronex/` by hand.

## Figures in Quarto

`chronex.quarto` shows a figure in a tabset: the figure, then its lineage as a graph with the
flags listed under it.

```python
import chronex.quarto as cq

cq.figure("results/fit.png", caption="Fit")  # a figure the pipeline wrote

with cq.make_figure("figures/residuals.png", caption="Residuals") as s:  # drawn in the cell
    data = np.load(s.input("results/fits.npy"))
    ...
    fig.savefig("figures/residuals.png")
```

- Paths are relative to the cell's working directory, which is the document's directory.
- `make_figure` records the cell as a step named after the figure's file stem
  (`residuals`), unless given `name=`; keyword arguments are its parameters. Declare what
  the cell reads with `s.input`.
- Records are searched for below the document's directory. When the pipeline ran elsewhere,
  set `cq.roots = ["../pipeline"]` (a list of directories) before the first figure.
- No `output: asis` is needed, and Graphviz need not be installed: Quarto draws the graph.

**The Python Quarto runs.** Quarto runs Python cells in a Jupyter kernel, and must use the
environment chronex is installed in. That environment also needs `ipykernel`, `nbformat`,
`nbclient` and `pyyaml`, e.g. `uv add ipykernel nbformat nbclient pyyaml`. Then either

- render with that environment activated (`source .venv/bin/activate; quarto render`), or
- point Quarto at its interpreter: `QUARTO_PYTHON=.venv/bin/python quarto render`.

Check which Python Quarto finds with `quarto check jupyter`. An inherited `VIRTUAL_ENV` from
another project can make Quarto, and `uv pip install`, use the wrong environment; check it
before installing anything.

Each render records the cells' steps again; the newest run replaces the older ones, so
flags do not pile up, but records do. Re-render after the pipeline changes, as the
provenance tab shows the records as they were at render time.
