# Phase 2: review, and an agent using chronex cold

**Date:** 2026-10-29

**Question:** Does the phase-1 implementation hold up outside the toy workflow, and can an
agent use it from the README alone?

**Method:** A code review with a probe script for each suspected bug, and an agent given only
the README and a new task: a five-step pipeline (simulate, fit, aggregate, a shell filter,
plot) in more than one markup style, followed by realistic mistakes. The agent did not see the
review.

**Found:**

The agent wrote correct markup in every style from the README and docstrings alone, without
opening the source. The checks caught its stale re-plot, its hand-edited table and its crashes,
with messages it understood. The problems were elsewhere:

| Problem | Effect |
|---|---|
| An input linked to any step that wrote the same bytes, even a later or unrelated one | false lineage, e.g. between two empty log files |
| `modified-after-write` counted writers that ran after the reader | false errors |
| Two copies linked into a cycle | `check` crashed with `RecursionError` |
| A step only wrote its record at the end | a Slurm time limit (SIGTERM) left no record at all |
| A file read and then rewritten in the same step was dropped | hidden inputs |
| `~/.cache` was ignored wholesale | model weights unobserved |
| Worker processes were invisible | parallel reads unflagged |
| A declared input that did not exist became an origin | typos unflagged |
| Large arguments were listed in full | a 1.6 MB record for one array |
| Generators and coroutines finished before their body ran | wrong status, false `missing-output` |
| `check` reported every record ever made | a mistake fixed by re-running failed `check` forever |
| `chronex run` ignored `--name`, and its children pointed at a parent record that was never written | confusing records |
| Python 3.15 clears `__main__.__file__` before `atexit` | `track()` and `chronex run` records had no code |
| `uv sync` needed a shephex checkout next to the repository | a fresh clone could not be set up |

**Changes:**

- Linking requires time order and prefers the same path; content with more than one original
  source, or under 64 bytes, is `ambiguous-input` instead of lineage. See
  [Linking](../design.md#linking).
- Records are written at start and finished on SIGTERM; leftovers are `incomplete`.
- New checks: `incomplete`, `missing-input`, `ambiguous-input`, `untracked-workers`. A
  failure is reported once, at the innermost step.
- `check` looks at current steps by default, with `--target`, `--history` and `--strict`.
  `ROOTS` defaults to `.`.
- `show` names each step's files and says why a file has no lineage. The report embeds the
  figure and lists undeclared reads.
- The README gained an install line, a worked example with real output, and the checks.

**Second round:** a fresh agent with the same brief ran against the changes. Every scenario
above now behaved, and `check` passed once a mistake was fixed by re-running. It found that
`show`, `check --target` and `report` still found a file's producers by hash alone, so an
identical re-run pulled old runs and their flags into the lineage, and a tiny file was
attributed to an unrelated step. They now look files up by the linking rules. It also found
that `chronex run` left its command running on SIGTERM, ran `--in a b`'s `b` as the command,
and recorded `python script.py` as two steps; that a named decorator dropped its parameters;
and that code piped to `python -` was silently not recorded. All are fixed.

**Third round:** a third agent, with the same brief, wrote correct markup in every style from
the README alone, and every earlier fix held. What it missed most was a way to retire a record:
a failed experiment or a mistaken command stayed current and warned for good, as did an old
run kept current by a one-off step that read its output, with advice to re-run a step already
re-run. `chronex forget` now moves records to `.chronex/forgotten/`, and a flag on an older run
names the steps keeping it current. `untracked-workers` could not be answered, so `--strict`
failed for good with a process pool; it is now a note once the step declares its inputs. A
block reading a file written by a step nested inside it did not link, as the nested step ended
after the block started; nested steps are now exempt from that order. Exit codes now agree
(2 when a file has no lineage), `chronex run` reports every step the same way and warns about
its options after `--`, and `check --json` has a summary. Origin versions and `chronex run`'s
grandchildren remain known gaps (see [Known gaps](../design.md#known-gaps)).

**Next:**

- A persistent hash cache, and where to keep it on a cluster.
- The shephex integration from phase 1, so `options.json` links up.
- Try chronex on temper's checkpoints.
