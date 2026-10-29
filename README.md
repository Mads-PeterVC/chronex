# chronex

Provenance records for computational research: what each step read, wrote and ran, linked
into a lineage you can check.

Experimental. Not on PyPI yet.

```python
import chronex
from chronex import In, Out


@chronex.step
def fit(data: In[Path], model: Out[Path], alpha: float = 1e-3) -> None: ...
```

Every step writes one JSON record to `.chronex/` next to where it ran. `chronex check <dirs>`
links the records by file hash and reports problems; `chronex report <figure> <dirs>` writes
an HTML page with the figure's full lineage.

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
