# chronex

Provenance records for computational research: what each step read, wrote and ran, linked
into a lineage you can check.

Experimental. Not on PyPI yet.

## Install

```bash
uv add git+https://github.com/Mads-PeterVC/chronex      # into a uv project
uv pip install -e /path/to/chronex                       # or a local checkout
```

chronex has no dependencies. It must be installed in the environment the steps run in,
including on a cluster or in a container.

## How it works

Every step writes one JSON record to `.chronex/` in the directory it ran in: its parameters,
the SHA-256 of every file it read and wrote, its code (git commit and diff) and environment.
Steps do not know about each other. `chronex check` finds the records below a directory and
links them afterwards: an input comes from the step that wrote a file with the same hash, so
copies between folders and machines need no special handling. A Python audit hook watches
every `open()` while a step runs, so files the code reads without declaring them are flagged.

## Example

Five steps, each marked up the way that costs least in that piece of code.

```python
# simulate.py: a script. One line records the rest of it as a step.
seed = int(sys.argv[1])
chronex.track(seed=seed)
Path(chronex.output(f"data/run-{seed}.csv")).write_text(...)
```

```python
# fit.py: a function. Typed parameters say which arguments are files.
@chronex.step
def fit(data: In[Path], result: Out[Path], scale: float = 1.0) -> None: ...


for seed in range(3):
    fit(Path(f"data/run-{seed}.csv"), Path(f"fits/run-{seed}.json"))
```

```python
# aggregate.py: a block, with files declared where they are used.
with chronex.step("aggregate") as s:
    rows = [json.loads(Path(s.input(p)).read_text()) for p in sorted(Path("fits").glob("*.json"))]
    Path(s.output("summary.csv")).write_text(...)
```

```bash
# A shell step: declare its files, as chronex cannot see inside sort.
chronex run --name filter --in summary.csv --out top.csv -- \
    sh -c 'sort -t, -k2 -nr summary.csv | head -2 > top.csv'

# Unmarked Python: every file it opens is recorded.
chronex run -- python plot.py
```

Then check the lineage, and show where the result came from:

```console
$ chronex check
10 steps, 8 linked inputs, 0 origin inputs, 0 flags

$ chronex show figure.txt
plot [completed]  top.csv → figure.txt
  filter [completed]  summary.csv → top.csv
    aggregate [completed]  fits/run-0.json, fits/run-1.json and 1 more → summary.csv
      fit [completed] scale=1.0  data/run-0.csv → fits/run-0.json
        simulate [completed] seed=0  → data/run-0.csv
      ...
```

Edit `summary.csv` by hand and re-run the last two steps, and `check` fails:

```console
$ chronex check
error modified-after-write   filter     954e2b9a  summary.csv differs from what aggregate wrote there (807ee04089… then, c13f4544bb… when read): changed without a record
10 steps, 7 linked inputs, 0 origin inputs (3 not current, --history to show), 1 flags
```

Re-run `aggregate.py` and the steps after it, and it passes again: the steps that used the
edited file have been redone, so they are no longer current.

`chronex report figure.png` writes `lineage.html`, a self-contained page with the figure, every
step upstream of it, and every flag.

## Which markup to use

| Code | Use | Granularity |
|---|---|---|
| A function, a shephex experiment | `@chronex.step` with `In[...]` / `Out[...]` | one step per call |
| A script, e.g. written by an agent | `chronex.track()` and `chronex.input/output(path)` | one step per process |
| A notebook cell, part of a script | `with chronex.step("name") as s:` | one step per block |
| Code you cannot change, shell tools | `chronex run [--in …] [--out …] -- cmd` | one step per command |

`chronex.input(path)` and `chronex.output(path)` return `path`, work inside any of the above,
and do nothing outside a step. Use them for files a signature cannot name in advance.

## Words

- **Origin input**: an input no recorded step wrote, such as raw data or a config. The
  lineage starts there.
- **Current**: a step not redone by a later run. `check` looks only at current steps and
  their ancestry unless given `--history`.
- **Ambiguous input**: its content matches outputs of unrelated steps, or is too small
  (under 64 bytes) to identify. It is reported, but not linked.

## Checks

| Code | Level | Meaning |
|---|---|---|
| `modified-after-write` | error | An input differs from what a recorded step wrote at that path: something unrecorded changed it. |
| `missing-output` | error | A declared output was never written. |
| `failed` | warn | The step raised, exited non-zero, or was killed by SIGTERM. |
| `incomplete` | warn | The step never recorded an end: still running, or killed without warning. |
| `failed-producer` | warn | An input was written by a failed or incomplete step. |
| `undeclared-read` | warn | The step opened a file it did not declare. |
| `missing-input` | warn | A declared input did not exist. |
| `ambiguous-input` | warn / info | An input's content matches unrelated outputs (warn), or is too small to link (info). |
| `superseded-input` | warn | An input was later rewritten at its path, e.g. by a re-run. |
| `mixed-lineage` | warn | A step's inputs descend from different versions of the same file. |
| `untracked-workers` | warn | The step started worker processes (multiprocessing); their file access is unseen. |
| `unrecorded-code` | warn | The code was piped in on stdin, so the record does not hold it. |
| `subprocess` | info | The step ran another program; its file access is only known from declarations. |
| `undeclared-write` | info | The step wrote a file it did not declare. |
| `changed-on-disk` | info | An output on disk no longer matches what the step wrote. |

## Command line

```
chronex check [ROOTS…] [--target FILE] [--history] [--strict] [--all] [--json]
chronex show FILE [ROOTS…]
chronex report FILE [ROOTS…] [-o lineage.html]
chronex run [--name N] [--in PATH…] [--out PATH…] [--watch DIR…] [-q] -- COMMAND…
```

`ROOTS` defaults to the current directory; records are found anywhere below it. `check`
exits 1 if it finds an error, or a warning with `--strict`, and 0 otherwise, so it can gate a
pipeline or an agent's work. `--target FILE` checks only that file's lineage.

`CHRONEX_IGNORE` lists extra paths (separated like `PATH`) whose reads and writes are not
observed, e.g. scratch directories.

## More

The toy workflow in `examples/toy-workflow/` runs the same pipeline with each way of marking
up code, with and without planted mistakes. See `docs/` for the design and the findings.

## Development

```bash
uv sync
uv run pytest
uv sync --group examples                  # the toy workflow and its tests
uv pip install -e ../shephex              # its shephex variant needs an unreleased change
uv run ruff check && uv run ruff format --check
uv run mypy
```
