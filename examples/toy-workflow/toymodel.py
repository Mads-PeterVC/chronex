"""A miniature of the temper workflow: label configurations, fit a cluster expansion, run MC.

Configurations are rings of ``N_SITES`` spins (±1). The "oracle" energy has point, nearest
and next-nearest pair, triplet and a small nonlinear term; the surrogate cluster expansion only
has the point and pair terms. Metropolis Monte Carlo of the surrogate gives the energy and
heat capacity against temperature (k_B = 1).

The physics is shared by every variant of the workflow, so the variants differ only in how
they read, write and record files.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

N_SITES = 12


def generate(n: int, seed: int) -> np.ndarray:
    """``n`` distinct random configurations, as an (n, N_SITES) int8 array of ±1."""
    rng = np.random.default_rng(seed)
    configs = {tuple(rng.choice([-1, 1], N_SITES)) for _ in range(4 * n)}
    return np.array(sorted(configs)[:n], dtype=np.int8)


def _correlations(configs: np.ndarray) -> dict[str, np.ndarray]:
    s = configs.astype(float)
    right, right2 = np.roll(s, -1, axis=1), np.roll(s, -2, axis=1)
    return {
        "point": s.mean(axis=1),
        "nn": (s * right).mean(axis=1),
        "nnn": (s * right2).mean(axis=1),
        "triplet": (s * right * right2).mean(axis=1),
    }


def oracle_energy(configs: np.ndarray, params: dict[str, float]) -> np.ndarray:
    """Energy per site from the reference model (the expensive calculation in real life)."""
    c = _correlations(configs)
    return (
        params["h"] * c["point"]
        + params["J1"] * c["nn"]
        + params["J2"] * c["nnn"]
        + params["K"] * c["triplet"]
        + params["eps"] * c["nn"] ** 2
    )


def features(configs: np.ndarray) -> np.ndarray:
    c = _correlations(configs)
    return np.column_stack([np.ones(len(configs)), c["point"], c["nn"], c["nnn"]])


def fit_eci(configs: np.ndarray, energies: np.ndarray, alpha: float) -> dict[str, float]:
    """Ridge fit of the effective cluster interactions.

    If ``configs/prior.json`` exists, the fit is pulled towards it. Nothing in the signature
    says so: a hidden read of the kind provenance tooling has to catch.
    """
    X = features(configs)
    prior = np.zeros(X.shape[1])
    if Path("configs/prior.json").exists():
        prior = np.array(json.loads(Path("configs/prior.json").read_text())["eci"])
    A = X.T @ X + alpha * len(X) * np.eye(X.shape[1])
    eci = prior + np.linalg.solve(A, X.T @ (energies - X @ prior))
    rmse = float(np.sqrt(np.mean((X @ eci - energies) ** 2)))
    return {"eci": eci.tolist(), "rmse": rmse, "alpha": alpha, "n": len(X)}


def metropolis(
    eci: list[float],
    temperatures: list[float],
    sites: int = 48,
    sweeps: int = 300,
    equilibration: int = 100,
    seed: int = 0,
) -> list[dict[str, float]]:
    """Canonical-free (spin-flip) Metropolis of the surrogate; energy and C_v per site."""
    _, h, j1, j2 = eci
    rng = np.random.default_rng(seed)
    s = rng.choice([-1, 1], sites)
    rows = []
    for T in sorted(temperatures, reverse=True):
        energies = []
        for sweep in range(equilibration + sweeps):
            sites_order = rng.integers(0, sites, sites)
            accept = rng.random(sites)
            for i, u in zip(sites_order, accept, strict=True):
                local = (
                    h + j1 * (s[i - 1] + s[(i + 1) % sites]) + j2 * (s[i - 2] + s[(i + 2) % sites])
                )
                delta = -2.0 * s[i] * local
                if delta <= 0 or u < np.exp(-delta / T):
                    s[i] = -s[i]
            if sweep >= equilibration:
                total = (
                    h * s.sum() + j1 * (s * np.roll(s, -1)).sum() + j2 * (s * np.roll(s, -2)).sum()
                )
                energies.append(total)
        e = np.array(energies)
        rows.append(
            {
                "temperature": T,
                "energy": e.mean() / sites,
                "heat_capacity": e.var() / (T**2 * sites),
            }
        )
    return sorted(rows, key=lambda r: r["temperature"])


TEMPERATURES = [round(0.1 + 0.15 * i, 3) for i in range(16)]
