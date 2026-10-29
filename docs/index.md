# chronex

chronex records what each step of a computational workflow read, wrote and ran, and links
those records into a lineage you can check. It is meant for research that is run partly by
agents, at scale, across machines: hundreds of Slurm jobs, files copied between clusters, and
a figure at the end that should be traceable back to its inputs.

```python
import chronex
from chronex import In, Out


@chronex.step
def fit(structures: In[Path], labels: In[list[Path]], model: Out[Path], alpha: float) -> None: ...
```

Each call writes one JSON record to `.chronex/` in the directory it ran in. Records travel
with the results (rsync, `hex remote pull`), and nothing needs a server.

```bash
chronex check results/            # link every record below results/ and list problems
chronex show results/cv.png       # the upstream lineage of a file, as a tree
chronex report results/cv.png -o lineage.html   # an interactive lineage page
chronex run -- python legacy.py   # record a script without changing it
```

## Ways to mark up code

| Style | Looks like | Best for |
|---|---|---|
| Decorator | `@chronex.step` with `In[...]` / `Out[...]` parameters | functions, shephex experiments |
| Block | `with chronex.step("fit") as s: np.load(s.input(p))` | notebook and Quarto cells |
| Script | `chronex.track()` then `chronex.input(p)` / `chronex.output(p)` | one-off scripts |
| Wrapper | `chronex run -- python script.py` | code you cannot or will not change |

All four write the same record. In every style an audit hook watches what the code actually
opens, so a file read without being declared is reported rather than silently missing.

See [the toy workflow](toy-workflow.md) for all four applied to the same pipeline, and what
each one catches.
