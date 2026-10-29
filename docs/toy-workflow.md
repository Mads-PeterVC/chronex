# The toy workflow

`examples/toy-workflow/` is a miniature of the temper pipeline in numpy, small enough to run
on a laptop in about 15 seconds:

```
generate → label (4 array tasks) → collect (copy) → fit → stage (copy) → scan (4 seeds) → export (awk) → plot
```

Configurations are rings of 12 spins. The "oracle" labels them with an energy model; a
cluster expansion is fitted to the labels; Metropolis Monte Carlo of the expansion gives the
heat capacity against temperature, and the plot is the result. The physics lives in
`toymodel.py`, so the variants differ only in how they handle and record files.

The pipeline is written once without provenance (`plain`) and then once per way of recording.
`drive.py` runs a variant one command per step, the way an agent would. With `--faults` it
plants four realistic mistakes:

1. **Failed but used.** Labelling chunk 3 writes its energies, then fails a check. Collect
   copies the file anyway.
2. **Hand-edited intermediate.** A collected label file is edited between collect and fit.
3. **Hidden read.** `configs/prior.json` exists, and `toymodel.fit_eci` reads it. Nothing in
   the scripts or signatures mentions it.
4. **Re-staged model.** After two Monte Carlo seeds, the model is refitted and re-staged. The
   last two seeds then use a different model than the first two, and the plot mixes them.

`tests/test_toy.py` is the known-answer test. Each variant must link every step in a clean
run, and must report exactly the expected flags when the faults are planted.

## The same step, five ways

The fit step in `plain`:

```python
structures = np.load("data/structures.npy")
configs = np.concatenate([structures[c :: args.chunks] for c in range(args.chunks)])
energies = np.concatenate([np.load(f"data/labels/chunk-{c}.npy") for c in range(args.chunks)])
model = toymodel.fit_eci(configs, energies, args.alpha)
Path("model").mkdir(exist_ok=True)
Path("model/eci.json").write_text(json.dumps(model, indent=1))
```

**Script** (`chronex.track`): one line after argument parsing, and paths are wrapped where
they are used.

```python
chronex.track(**vars(args))

structures = np.load(chronex.input("data/structures.npy"))
...
energies = np.concatenate(
    [np.load(chronex.input(f"data/labels/chunk-{c}.npy")) for c in range(args.chunks)]
)
...
Path(chronex.output("model/eci.json")).write_text(json.dumps(model, indent=1))
```

**Block** (`with chronex.step`): the same, inside an indented block.

```python
with chronex.step("fit", alpha=args.alpha) as s:
    structures = np.load(s.input("data/structures.npy"))
    ...
    Path(s.output("model/eci.json")).write_text(json.dumps(model, indent=1))
```

**Decorator** (`@chronex.step`): the signature declares the files, and the body uses its parameters instead of fixed paths.

```python
@chronex.step
def fit(structures: In[Path], labels: In[list[Path]], model: Out[Path], alpha: float) -> None:
    chunks = len(labels)
    all_structures = np.load(structures)
    configs = np.concatenate([all_structures[c::chunks] for c in range(chunks)])
    energies = np.concatenate([np.load(path) for path in labels])
    model.parent.mkdir(exist_ok=True)
    model.write_text(json.dumps(toymodel.fit_eci(configs, energies, alpha), indent=1))
```

**Mixed** (shephex): the decorator stacks under `@shephex.hexperiment`. A path known only
inside the experiment, like a shared file, is declared where it is read.

```python
@shephex.hexperiment(procedure_type="ScriptProcedure", hex_directory="runs/scan")
@chronex.step
def scan(seed: int, curve: Out[str] = "curve.csv") -> None:
    model = chronex.input(shephex.shared_path("eci.json"))
    ...
```

**Wrapper**: the plain scripts, unchanged, run as `chronex run -- python fit.py --alpha 1e-3`.

## What each one caught

Faults planted: 2 × modified-after-write, 1 × failed, 1 × failed-producer,
2 × undeclared-read, 3 × superseded-input, 1 × mixed-lineage. That is 10 flags in total.

| Variant | Clean run: flags | Faults: flags found | Linked inputs | Figure traced back to `generate` |
|---|---:|---:|---:|:---:|
| decorator | 0 | 10 / 10 | 27 | yes |
| block | 0 | 10 / 10 | 27 | yes |
| script | 0 | 10 / 10 | 27 | yes |
| mixed (shephex) | 0 | 10 / 10 | 27 | yes |
| wrapper | 0 | 7 / 10 | 23 | **no**: the chain stops at export |

The three annotated styles produce the same graph. The choice between them is ergonomics,
not capability.

The wrapper misses three flags, for two reasons:

- **It cannot call a read "undeclared".** It records every read as an input, so
  `configs/prior.json` shows up as an origin input of fit. That is visible to a reviewer, but
  not flagged.
- **It is blind past a non-Python subprocess.** Export runs `awk`, and the wrapper never sees
  what awk read. Export therefore has no inputs, the figure's lineage stops there, and the
  mixed-lineage check never gets to run. With declarations, export declares its inputs and
  the chain is complete.

## What it costs

`compare.py` diffs each variant against `plain`. The counts cover code lines only (no
docstrings, comments or blanks), summed over the eight scripts:

| Variant | Code lines (plain: 94) | Added | Changed | chronex lines | Plain lines kept |
|---|---:|---:|---:|---:|---:|
| script | 115 | 21 | 15 | 32 | 84% |
| block | 115 | 21 | 43 | 32 | 54% |
| decorator | 148 | 62 | 35 | 32 | 54% |
| mixed | 162 | 69 | 53 | 35 | 43% |
| wrapper | 94 | 0 | 0 | 0 | 100% |

- Every annotated style needs about the same chronex content: 32 lines that mention it.
  That is two imports per script plus one declaration per file.
- **Script** is the cheapest diff, because declarations are inline and nothing is re-indented.
- **Block** costs the same lines, but re-indents the body. That shows up as changed lines and
  noisy diffs.
- **Decorator** adds the most lines. Most of them are not chronex: they come from turning a
  script into a function plus a call. Code that is already a function (every shephex
  experiment, most library code) only gains the decorator and the `In`/`Out` annotations.
  Those annotations read as documentation of what the function touches.
- **Mixed** includes the shephex scaffolding itself; the chronex part is the same as the
  decorator's.

At run time a recorded step costs about 4–5 ms (hashing, code identity, and writing a
2–3 kB JSON record), against 0.3 ms for a trivial bare step (`dev/overhead.py`). Git state
is read once per process.

## Findings

1. **Declarations plus the audit hook is the right foundation.** Declarations alone would
   miss the hidden read; the hook alone (the wrapper) misses anything outside Python. Together
   they caught every planted fault.
2. **Granularity follows the API.** `track()` gives one step per process. That matches one
   array task per process, but not a script that runs several logical steps in a loop; use
   the decorator or a block there.
3. **shephex needs one small change.** `ScriptProcedure` saves the source of
   `inspect.getsourcefile(function)`. For a decorated function that is the decorator's
   module, so the experiment ships chronex's source as `procedure.py`. Unwrapping first
   (`inspect.getsourcefile(inspect.unwrap(function))`) fixes it. The three-line patch is in
   `dev/shephex-unwrap.patch`, and the mixed variant's tests are skipped until shephex has it.
4. **shephex's own files become origins.** Collect reads `shephex/options.json` to learn each
   experiment's chunk, and those files appear as origin inputs because no step wrote them. A
   shephex integration could write a small chronex record when it creates an experiment, so
   the options link up.
5. **Copies are free.** Collect and stage copy files, and the copies link by hash without any
   special handling: the same result as in the temper backfill.

## Recommendation

- Use the **decorator** for functions, including shephex experiments.
- Use **`track()`** for one-off scripts, which is what agents mostly write. It is one line,
  plus a wrapped path per file.
- Use a **block** in notebooks and Quarto cells.
- Keep **`chronex run`** for code you do not control.
- Keep the **audit hook** on in all of them.

The open question is agent ergonomics: which of these an agent gets right without prompting,
given only the README. That is the next experiment.
