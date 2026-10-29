# Phase 0: backfilling a real figure

**Date:** 2026-10-29

**Question:** Before writing any recording code, how much of a real result's lineage can be
rebuilt from what shephex and the repository already hold?

**Target:** `refined-curves.csv`, the refined heat-capacity curves in temper's 2026-10-27
synthetic-v2.5 post. Upstream of it are 666 Slurm jobs in five campaigns on two clusters,
copied between them by hand-written `--stage` and `--collect` steps, plus one export run as a
`python -c` one-liner.

**Method:** Hash every file in the chain, and treat equal hashes as one artifact. Reconstruct
each run's inputs from shephex's `options.json` and from path constants in its
`procedure.py`. Enter the unrecorded export as a claim taken from the post's prose, and verify
it by re-running it. The prototype is in `temper/experiments/provenance-backfill/`; it is
standard-library only and takes about 5 seconds.

**Result:**

- 841 input links matched by hash, including every copy step.
- 438 inputs have no recorded producer: configs, split manifests, templates and the
  foundation/oracle trajectories. These are where the trace stops.
- The export reproduced byte-for-byte.

It also found that the six training runs feeding the figure are marked `failed` in shephex.
Their models are fine; a reporting step that ran after training failed.

**What had to be guessed:** these became requirements.

| Count | Guess | Requirement |
|---:|---|---|
| 697 | which commit of the remote checkout ran | record git commit + diff hash at run time |
| 690 | that the local staged copy is what was sent | hash shared files where they are used |
| 360 | inputs that exist only as code constants | observe file access, not just parameters |
| 1 | a step with no record at all | make recording a local step trivial |

It also showed that "failed" needs to be per step, not per run: a failed run can still have
produced a valid artifact.
