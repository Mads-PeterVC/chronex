"""Link records into a lineage graph and check it.

`load` reads the records below some directories and `build` links them by file hash
(`resolve`), then runs the checks (`checks`) on the resulting `Graph` (`model`).
"""

from chronex.graph.build import build
from chronex.graph.flags import LEVELS, Flag
from chronex.graph.model import Graph
from chronex.graph.records import Record, load
from chronex.graph.resolve import TRIVIAL_BYTES, Link

__all__ = ["LEVELS", "TRIVIAL_BYTES", "Flag", "Graph", "Link", "Record", "build", "load"]
