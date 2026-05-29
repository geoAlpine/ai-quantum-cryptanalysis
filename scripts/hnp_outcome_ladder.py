"""Outcome-level signal ladder — noise tolerance of the d-class signal vs m.

Companion to scripts/hnp_signal_ladder.py. That tool injects GATE-level
depolarizing noise, which requires a per-shot stochastic simulation — fine at
m=3 (702 cx) but impractical at m=5 (16,200 cx; dense oracle is O(4^m)). This
tool instead applies OUTCOME-level noise: simulate the dense circuit noiselessly
ONCE, then replace a fraction f of the measured (j,k) shots with uniform-random
values (decoherence-to-maximally-mixed). That is cheap, runs at high shot count,
and sweeps the effective-fidelity axis (eff fid ≈ 1−f) — so it gives a clean,
cross-m-COMPARABLE ladder where the gate-level one cannot.

Cross-m result (4096 shots, same outcome-level model, verified 2026-05-30):
    m=3 (n=7,  d-class 2/7) : signal survives to f≈0.9  (eff fid ≈10%)
    m=5 (n=31, d-class 2/31): signal survives to f≈0.5  (eff fid ≈50%)
The noise tolerance TIGHTENS sharply with m: a larger n dilutes the d-class
(2/n) among more competitors, so less decoherence is tolerable. Combined with
the gate-count blowup (m=5 dense = 23× m=3's cx) and the higher shot count m=5
needs for power, this quantifies the three-axis cost of scaling toward the
large-m genuine-signal goal.

Statistic = squared-residual best-dc z (robust cross-m; the likelihood booster
is m=3-specific — see hnp_score_matrix._nll_scores_np). Null = shuffle k vs j.
Permutation p averaged over several independent corruption seeds.

CAVEAT: outcome-level (replace-with-uniform) is a coarse, device-agnostic noise
model — it answers "how much decoherence the signal tolerates", not a specific
device's behaviour. The authoritative per-platform verdicts remain the real-data
permutation tests in hnp_score_matrix.py.

Usage:
    PYTHONPATH=src python scripts/hnp_outcome_ladder.py            # m=3
    PYTHONPATH=src python scripts/hnp_outcome_ladder.py 6 8 4096   # m=5
    # args: bits  t  shots
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/
from hnp_score_matrix import parse_shots  # noqa: E402

CORRUPT_SEEDS = [1, 7, 42, 123]
PERM_SEED = 20260529
N_PERM = 800
ALPHA = 0.05
F_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def make_scorer(n, t):
    """Vectorised best-dc z over all d at once (fast enough for n=31 ×
    thousands of shots × hundreds of permutations)."""
    M = 1 << t
    peaks = np.array(sorted({(s * M + n // 2) // n % M for s in range(n)}))
    half = M // 2
    darr = np.arange(n)

    def best_dc_z(j, k, dc):
        v = (j[None, :] + darr[:, None] * k[None, :]) % M     # (n, S)
        diff = (v[:, :, None] - peaks[None, None, :]) % M      # (n, S, P)
        diff = np.where(diff <= half, diff, diff - M)
        sc = (np.abs(diff).min(axis=2).astype(float) ** 2).mean(axis=1)
        z = (sc - sc.mean()) / (sc.std() or 1.0)
        return min(z[d] for d in dc)
    return best_dc_z


def main():
    bits = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    t = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    shots = int(sys.argv[3]) if len(sys.argv) > 3 else 4096

    from challenges import get_challenge
    from ecc import EllipticCurve
    from shor_ecdlp import (ShorECDLPSolver, SubgroupIndexer,
                            DenseUnitaryOracle)
    from qiskit import transpile
    from qiskit_aer import AerSimulator

    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    n, d_true = c.n, c.expected_d
    m = max(1, (n - 1).bit_length())
    dc = sorted({d_true, (n - d_true) % n})
    best_dc_z = make_scorer(n, t)

    def ptest(j, k, seed):
        rng = np.random.default_rng(seed)
        obs = best_dc_z(j, k, dc)
        null = np.array([best_dc_z(j, rng.permutation(k), dc)
                         for _ in range(N_PERM)])
        return obs, (1 + int(np.count_nonzero(null <= obs))) / (1 + N_PERM)

    print(f"Outcome-level signal ladder — m={m} dense (n={n}, t={t}), "
          f"{shots} shots, d-class={dc}")
    t0 = time.time()
    solver = ShorECDLPSolver(curve, G, Q, n,
                             oracle=DenseUnitaryOracle(SubgroupIndexer(curve, G, n)),
                             num_counting=t)
    sim = AerSimulator(method="statevector")
    counts = sim.run(transpile(solver.build_circuit(), sim,
                               optimization_level=1),
                     shots=shots, seed_simulator=1).result().get_counts()
    sh = parse_shots(counts, t, m, n)
    J0 = np.array([s[0] for s in sh])
    K0 = np.array([s[1] for s in sh])
    N = len(J0)
    print(f"  noiseless sim {time.time()-t0:.0f}s, N={N} shots parsed\n")
    print(f"  {'f_rand':>7} {'eff_fid':>8} {'mean_p':>8} {'power':>6}  signal?")
    print("-" * 48)

    crossed = None
    prev = True
    for f in F_GRID:
        ps = []
        for cs in CORRUPT_SEEDS:
            rng = np.random.default_rng(cs)
            j, k = J0.copy(), K0.copy()
            nc = int(f * N)
            corr = rng.choice(N, nc, replace=False)
            j[corr] = rng.integers(0, n, nc)
            k[corr] = rng.integers(0, n, nc)
            _, p = ptest(j, k, seed=int(rng.integers(1_000_000_000)))
            ps.append(p)
        mp = float(np.mean(ps))
        pw = float(np.mean([p < ALPHA for p in ps]))
        sig = mp < ALPHA
        if prev and not sig and crossed is None:
            crossed = f
        prev = sig
        print(f"  {f:>7.2f} {1-f:>8.2f} {mp:>8.4f} {pw:>5.0%}  "
              f"{'sig' if sig else 'none'}")

    print()
    if crossed is not None:
        print(f"  → m={m} signal cliff: f_rand≈{crossed:.2f} "
              f"(eff fid ≈{1-crossed:.0%})")
    else:
        print(f"  → m={m}: signal significant across the whole grid "
              f"(survives to eff fid ≈{1-F_GRID[-1]:.0%}).")
    print(f"\n  Cross-m (4096 shots, same model): m=3 survives to ~10% fid; "
          f"m=5 to ~50% fid.\n  Larger n dilutes the d-class (2/n) → noise "
          f"tolerance tightens with m.")
    print("  CAVEAT: outcome-level (replace-with-uniform) noise is coarse and "
          "device-agnostic;\n  authoritative per-platform verdicts are the "
          "real-data tests in hnp_score_matrix.py.")


if __name__ == "__main__":
    main()
