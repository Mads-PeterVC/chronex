"""Plot the heat capacity against temperature, one line per Monte Carlo seed."""

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import chronex
from chronex import In, Out


@chronex.step
def plot(table: In[Path], figure: Out[Path]) -> None:
    curves = defaultdict(list)
    with open(table) as stream:
        for row in csv.DictReader(stream):
            curves[row["seed"]].append((float(row["temperature"]), float(row["heat_capacity"])))

    fig, ax = plt.subplots(figsize=(5, 3.5))
    for seed, points in sorted(curves.items()):
        ax.plot(*zip(*sorted(points), strict=True), marker="o", label=f"seed {seed}")
    ax.set(xlabel="Temperature", ylabel="Heat capacity per site")
    ax.legend()
    fig.tight_layout()
    fig.savefig(figure, dpi=120)


plot(Path("results/curves.csv"), Path("results/cv.png"))
