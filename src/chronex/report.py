"""A self-contained HTML page explaining one result: every step upstream of it, and every flag."""

from __future__ import annotations

import datetime as dt
import json
import os
from collections import Counter, defaultdict
from html import escape
from importlib import resources
from pathlib import Path
from typing import Any

from chronex.graph import Graph


def _compact(value: Any) -> Any:
    if isinstance(value, list) and len(value) > 6:
        if all(isinstance(v, (int, float)) for v in value):
            return f"{min(value):g} to {max(value):g} ({len(value)} values)"
        return f"{len(value)} items"
    return value


def report_data(graph: Graph, target: Path, title: str | None = None) -> dict[str, Any]:
    producers = graph.producers_of(target)
    if not producers:
        raise SystemExit(f"no recorded step wrote the current content of {target}")
    keep: set[str] = set(producers)
    for sid in producers:
        keep |= graph.ancestry(sid)
    records = {sid: graph.records[sid] for sid in keep}
    base = os.path.commonpath([r["cwd"] for r in records.values()])

    def rel(path: str) -> str:
        return os.path.relpath(path, base) if path.startswith(base) else path

    # Depth of each step from the target: the longest chain of links down to it.
    depth = {sid: 0 for sid in producers}
    for _ in range(len(keep)):
        changed = False
        for sid in list(depth):
            for link in graph.links[sid]:
                if link.producer in keep and depth.get(link.producer, -1) < depth[sid] + 1:
                    depth[link.producer] = depth[sid] + 1
                    changed = True
        if not changed:
            break

    index: dict[str, int] = {}
    arts: list[dict[str, Any]] = []

    def art(sha: str) -> int:
        if sha not in index:
            entry = graph.artifacts[sha]
            index[sha] = len(arts)
            arts.append(
                {
                    "sha": sha[:12],
                    "size": entry["size"],
                    "kind": entry["kind"],
                    "locs": sorted({(rel(loc["path"]), loc["role"]) for loc in entry["locations"]}),
                }
            )
        return index[sha]

    acts = {}
    for sid, r in records.items():
        links = graph.links[sid]
        acts[sid] = {
            "stage": r["name"],
            "kind": r["kind"],
            "status": r["status"],
            "error": r.get("error"),
            "params": {k: _compact(v) for k, v in r["params"].items()},
            "host": r["env"]["host"],
            "cwd": rel(r["cwd"]),
            "started": r["started"],
            "ended": r["ended"],
            "function": r.get("function"),
            "shephex": (r.get("shephex") or {}).get("identifier"),
            "slurm": r["env"]["variables"].get("SLURM_JOB_ID"),
            "container": r["env"]["variables"].get("APPTAINER_CONTAINER")
            or r["env"]["variables"].get("SINGULARITY_CONTAINER"),
            "python": r["env"]["python"],
            "packages": r["env"]["packages"],
            "code": {
                "entry": rel(r["code"]["entry"]) if r["code"]["entry"] else None,
                "files": {rel(p): sha[:12] for p, sha in r["code"]["files"].items()},
                "git": r["code"]["git"],
            },
            "flags": [f.to_dict() for f in graph.flags.get(sid, [])],
            "inputs": [
                {
                    "a": art(i["sha"]) if i["sha"] else None,
                    "param": i.get("param"),
                    "path": rel(i["path"]),
                    "how": i["how"],
                    "prod": link.producer if link.producer in keep else None,
                    "origin": link.origin,
                }
                for i, link in zip(r["inputs"], links, strict=True)
            ],
            "outputs": [art(o["sha"]) for o in r["outputs"] if o["sha"]],
            "depth": depth.get(sid, 0),
        }

    consumers: dict[str, list[str]] = defaultdict(list)
    for sid, a in acts.items():
        for i in a["inputs"]:
            if i["prod"]:
                consumers[i["prod"]].append(sid)

    stage_depth: dict[str, int] = {}
    for a in acts.values():
        stage_depth[a["stage"]] = max(stage_depth.get(a["stage"], 0), a["depth"])
    stages = [
        {
            "name": name,
            "depth": d,
            "runs": sorted(
                (sid for sid, a in acts.items() if a["stage"] == name),
                key=lambda s: acts[s]["started"],
            ),
            "hosts": sorted({a["host"] for a in acts.values() if a["stage"] == name}),
        }
        for name, d in sorted(stage_depth.items(), key=lambda x: (x[1], x[0]))
    ]
    edges: Counter[tuple[str, str]] = Counter()
    boundaries: dict[str, Counter[str]] = defaultdict(Counter)
    for a in acts.values():
        for i in a["inputs"]:
            if i["prod"]:
                edges[acts[i["prod"]]["stage"], a["stage"]] += 1
            elif i["origin"]:
                boundaries[a["stage"]][i["path"]] += 1
            else:
                boundaries[a["stage"]]["(unmatched) " + i["path"]] += 1

    return {
        "title": title or f"Lineage of {target.name}",
        "target": rel(str(target.resolve())),
        "target_steps": producers,
        "base": base,
        "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "stages": stages,
        "edges": [{"from": f, "to": t, "n": n} for (f, t), n in edges.items()],
        "boundaries": {k: dict(v) for k, v in boundaries.items()},
        "acts": acts,
        "consumers": consumers,
        "arts": arts,
    }


def write_report(graph: Graph, target: Path, output: Path, title: str | None = None) -> Path:
    data = report_data(graph, target, title)
    template = resources.files("chronex").joinpath("report.html").read_text()
    html = template.replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
    html = html.replace("<title>Lineage</title>", f"<title>{escape(data['title'])}</title>")
    output.write_text(html)
    return output
