# Phase 1: a first implementation and the toy workflow

**Date:** 2026-10-29

**Question:** What should the API look like, and how much does each option cost in the code
it is added to?

**Built:**

- `chronex.record`: the `Step` record, written to `.chronex/` in the step's working directory.
- `chronex.audit`: one process-wide audit hook, forwarding `open()` and `subprocess.Popen`
  events to the active step.
- `chronex.api`: the four ways to mark up code.
  - `@chronex.step` with `In[...]` / `Out[...]` typed parameters
  - `with chronex.step(...)`
  - `chronex.track()`
  - `chronex.input()` / `chronex.output()`, which work inside any of the above and do
    nothing outside a step
- `chronex.runner`: `chronex run`, zero-touch recording through `sitecustomize`, plus
  `--in`/`--out`/`--watch` for non-Python commands.
- `chronex.graph`: links records by hash and runs the checks.
- `chronex.report`: a self-contained HTML lineage page.

**The toy workflow and its results** are on [their own page](../toy-workflow.md).

In short, the decorator, block and script styles all found all ten planted faults and
produced identical graphs. The zero-touch wrapper found seven: it could not see past `awk`,
and it cannot call a read "undeclared".

**Changes forced by the experiment:**

- Output directories now list their files' hashes. Collecting into `data/labels/` and then
  reading one file from it still links to the collect step.
- shephex's `ScriptProcedure` must unwrap decorated functions before reading their source.
  The three-line change belongs in shephex and is not released yet.
- shephex's bookkeeping files (`meta.json`, `context.json`, `result.pkl`, ...) are ignored by
  the audit hook. They are not the experiment's data.
- chronex's own modules are recorded by version, not listed as user code.

**Next:**

- Test agent ergonomics: give an agent the README and a new task, and see which style it
  picks and whether its declarations are complete.
- Add a persistent hash cache, before trying chronex on temper's checkpoints.
- Try a shephex integration that records experiment creation, so `options.json` links up.
