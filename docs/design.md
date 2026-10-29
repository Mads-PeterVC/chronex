# Design

## The problem

A shephex run already keeps everything needed to check what *that run* did: its options, its
code and its Slurm log. What is missing is the link *between* runs. In practice that link is
a path string pointing into a checkout on another machine, a staged copy that was renamed, or
a paragraph of prose written afterwards. Backfilling the lineage of one figure in temper (see
[phase 0](log/phase-0.md)) showed that hashing files was enough to rebuild most of the chain.
It also showed which links could only be guessed.

## Principles

1. **Files are identified by content.** Every input and output is recorded with its SHA-256.
   Two steps are linked when one step's output has the same hash as another step's input.
   Copying, staging, renaming and rsync therefore never break a link, and nothing has to
   track them.
2. **Steps do not know about each other.** A step records only itself. The graph is built
   afterwards, from any set of records. This works across clusters, schedulers and tools, and
   needs no server or central database.
3. **Records live next to the results.** Each step writes `.chronex/<id>.json` in its working
   directory. For a shephex experiment that is the experiment directory, so the record comes
   home with `hex remote pull`.
4. **Declared, then cross-checked.** Code declares its files, through typed parameters or
   explicit calls. Python's audit hook (PEP 578) observes every `open()` while the step runs.
   Anything opened but not declared is reported. Declarations give the graph its meaning; the
   hook makes forgetting visible.
5. **Problems become flags, not failures.** chronex never stops a run. Checks happen when the
   graph is built, and each finding names the steps involved.

## Linking

An input links to a producer only if the producer ended before the consumer started. A step
that wrote the same path on the same host is preferred, and the latest such step wins. Content
found only at other paths (a copy, a staged file) links when it has a single original source:
a step that read the content and wrote it again is a copy, and a chain of copies counts as one
source. If unrelated steps wrote the same content, or the content is under 64 bytes (empty
files, `{}`), the input is *ambiguous*: flagged, and kept out of the lineage. Clocks on
different hosts must therefore roughly agree; a producer whose clock runs ahead of the
consumer's is not linked.

A step is *current* unless a later run redid it: every path it wrote (or declared and did not
write) was written again later on the same host, or, for a step without outputs, a later run
has the same name, parameters and directory. `chronex check` looks at current steps and
everything upstream of them, so a mistake fixed by re-running stops failing the check.

## Lifecycle

A step writes its record when it starts, with status `running`, and rewrites it when it ends.
A record still `running` means the process died without finishing: SIGKILL, an out-of-memory
kill or a node failure. SIGTERM, which Slurm sends at the time limit, is caught (only while
SIGTERM has its default handler): open steps are finished as failed, with their outputs
hashed, and the process then dies of the signal as it would have.

A step belongs to its process. Reads on any thread count towards the current step. A forked
child forgets its parent's open steps, and processes started by multiprocessing or
`concurrent.futures` are counted and flagged, but not followed.

## A record

```json
{
  "schema": "chronex/0",
  "id": "20261029T140312-scan-13303881",
  "name": "scan", "kind": "function", "function": "procedure:scan",
  "status": "completed", "error": null,
  "started": "...", "ended": "...", "cwd": ".../runs/scan/LVvY...-exp",
  "params": {"seed": 2},
  "inputs":  [{"path": ".../staging/eci.json", "sha": "93af...", "kind": "file", "how": "declared"}],
  "outputs": [{"path": ".../curve.csv", "sha": "a54f...", "kind": "file", "param": "curve"}],
  "observed": {"reads": [...], "writes": [...], "subprocesses": []},
  "undeclared_reads": [], "undeclared_writes": [], "missing_outputs": [],
  "code": {"entry": ".../scan.py", "files": {"...": "sha"}, "git": [{"commit": "...", "dirty": false}]},
  "env": {"host": "...", "python": "3.13", "variables": {"SLURM_JOB_ID": "..."}, "packages": {...}},
  "shephex": {"identifier": "LVvYeecvdkzdasxjoG9fZR"}
}
```

`code.files` lists every loaded module that belongs to the user's code: the entry script,
modules from the same git repository and modules on `PYTHONPATH`. For a shephex
`ScriptProcedure` it includes the `procedure.py` that actually ran. `git` records the commit,
whether the tree was dirty, and a hash of the uncommitted diff. Only an explicit allow-list of
environment variables is recorded.

## Checks

| Code | Level | Meaning |
|---|---|---|
| `modified-after-write` | error | An input's path was written by an earlier recorded step, but its content differs: something unrecorded changed it in between. |
| `missing-output` | error | A declared output was never written (not reported for a failed step). |
| `failed` | warn | The step raised, exited non-zero, or was killed by SIGTERM. Reported at the innermost failed step only. |
| `incomplete` | warn | The step never recorded an end. |
| `failed-producer` | warn | An input was written by a failed or incomplete step. |
| `undeclared-read` | warn | The step opened a file it did not declare. Files written by nested steps are exempt. |
| `missing-input` | warn | A declared input did not exist. |
| `ambiguous-input` | warn | An input's content matches outputs of unrelated steps; it is not linked. Info level when the content is under 64 bytes. |
| `superseded-input` | warn | An input was later rewritten (with different content) at the path it came from, e.g. by a re-run. |
| `mixed-lineage` | warn | A step's inputs descend from different versions of the same file. It is reported where the versions first meet. |
| `untracked-workers` | warn | The step started worker processes; their file access is only known from declarations. |
| `subprocess` | info | The step ran another program; its file access is only known from declarations. |
| `undeclared-write` | info | The step wrote a file it did not declare. |
| `changed-on-disk` | info | An output on disk no longer matches what the step wrote. |

## Known gaps

- Hashes are cached per process only. Large checkpoints are re-hashed by every step that
  reads them. A persistent `(path, size, mtime)` cache is the obvious fix, but where to keep
  it on a cluster (NFS homes, many concurrent jobs) needs its own decision.
- `changed-on-disk` only checks records made on the current host. Paths from other hosts are
  not mapped to local copies.
- Worker processes are flagged, not followed: what a multiprocessing pool reads is only known
  from declarations.
- Runs of one step with different parameters can feed the same result (a parameter mix-up, or
  a sweep). Nothing flags that, as the two cannot be told apart.
- `chronex.track()` cannot see `sys.exit(1)` from inside the process. `chronex run` can, and
  marks the record failed.
- `chronex run` passes SIGTERM to the command it started, not to that command's own children:
  `kill` on `chronex run -- sh -c '…; sleep 60'` ends `sh` and leaves `sleep` running. Slurm
  signals every process of a job, so a time limit is not affected.
- `chronex run` uses a `sitecustomize` module. That shadows any existing `sitecustomize` in
  the environment.
- In a container, chronex must be installed in the image. That makes it a grimoire concern.
