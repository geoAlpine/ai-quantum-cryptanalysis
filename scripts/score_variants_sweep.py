"""
Sweep HNP-score variants on saved noisy counts to find which variant
gives the cleanest d-class separation for hardware-noisy data.

Variants under test:
  1. L2 (current production): Σ d²
  2. L4: Σ d⁴ — sharper outlier penalty
  3. L1: Σ |d| — robust to occasional large residuals
  4. Median d² — most robust to outliers
  5. Trimmed mean d² (drop top 10%): outlier-resistant
  6. d² normalised by shot count (no-op for ranking but checks)
  7. r-grouped L2 (combine per-r scores)

For each variant we report d_true rank, score gap, and whether d-class
{d_true, n-d_true} is in top-3.

Usage:
    python scripts/score_variants_sweep.py --bits 4 --t 6 --oracle dense \\
        --backend ibm_kingston --shots 2048
"""
from __future__ import annotations

import argparse
import math
import statistics
import time
from collections import defaultdict

from challenges import get_challenge
from ecc import EllipticCurve
from quantum_ecc import load_token
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator
from qiskit_ibm_runtime import QiskitRuntimeService


def expected_peaks(n: int, M: int) -> list[int]:
    return sorted({(s * M + n // 2) // n % M for s in range(n)})


def centred_dist(v: int, peaks: list[int], M: int) -> int:
    half = M // 2
    best = M
    for e in peaks:
        diff = (v - e) % M
        diff = diff if diff <= half else diff - M
        if abs(diff) < best:
            best = abs(diff)
    return best


def score_L2(d, shots, n, t, peaks):
    M = 1 << t
    total = 0
    for (j, k, _r) in shots:
        v = (j + d * k) % M
        di = centred_dist(v, peaks, M)
        total += di * di
    return total / max(1, len(shots))


def score_L4(d, shots, n, t, peaks):
    M = 1 << t
    total = 0
    for (j, k, _r) in shots:
        v = (j + d * k) % M
        di = centred_dist(v, peaks, M)
        total += di ** 4
    return total / max(1, len(shots))


def score_L1(d, shots, n, t, peaks):
    M = 1 << t
    total = 0
    for (j, k, _r) in shots:
        v = (j + d * k) % M
        total += centred_dist(v, peaks, M)
    return total / max(1, len(shots))


def score_median(d, shots, n, t, peaks):
    M = 1 << t
    distances = []
    for (j, k, _r) in shots:
        v = (j + d * k) % M
        distances.append(centred_dist(v, peaks, M))
    return statistics.median(distances) if distances else 0.0


def score_trimmed_L2(d, shots, n, t, peaks, trim_frac=0.1):
    M = 1 << t
    distances_sq = []
    for (j, k, _r) in shots:
        v = (j + d * k) % M
        di = centred_dist(v, peaks, M)
        distances_sq.append(di * di)
    distances_sq.sort()
    n_keep = int(len(distances_sq) * (1 - trim_frac))
    return sum(distances_sq[:n_keep]) / max(1, n_keep)


def score_r_grouped(d, shots, n, t, peaks):
    """Group shots by r, compute per-r L2 score, sum across r-groups
    (each group's score is L2 over its own shots)."""
    M = 1 << t
    by_r = defaultdict(list)
    for shot in shots:
        by_r[shot[2]].append(shot)
    total = 0.0
    for r, group in by_r.items():
        for (j, k, _r) in group:
            v = (j + d * k) % M
            di = centred_dist(v, peaks, M)
            total += di * di
    return total / max(1, len(shots))


VARIANTS = [
    ("L2 (production)", score_L2),
    ("L4 (sharper)", score_L4),
    ("L1 (robust)", score_L1),
    ("median", score_median),
    ("trimmed L2 (90%)", score_trimmed_L2),
    ("r-grouped L2", score_r_grouped),
]


def rank_and_gap(scores_dict, d_true):
    sorted_scores = sorted(scores_dict.items(), key=lambda x: x[1])
    rank = next(i for i, (d, _) in enumerate(sorted_scores) if d == d_true) + 1
    best = sorted_scores[0][1]
    second = sorted_scores[1][1] if len(sorted_scores) > 1 else best
    gap = (second - best) / max(1e-9, second)
    return rank, gap, sorted_scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, default=4)
    ap.add_argument("--t", type=int, default=6)
    ap.add_argument("--oracle", choices=["dense", "ripple"], default="dense")
    ap.add_argument("--backend", default="ibm_kingston")
    ap.add_argument("--shots", type=int, default=2048)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    c = get_challenge(args.bits)
    n = c.n
    d_true = c.expected_d
    m = max(1, (n - 1).bit_length())
    M = 1 << args.t
    pt_w = m if args.oracle == "dense" else m + 1
    peaks = expected_peaks(n, M)

    print(f"=== Score variants sweep ===")
    print(f"  bits={args.bits} n={n} d_true={d_true} t={args.t} M={M}")
    print(f"  backend={args.backend} shots={args.shots} seed={args.seed}")
    print(f"  expected peaks: {peaks}")
    print()

    # Build and run the noisy sim
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    ind = SubgroupIndexer(curve, G, n)
    oracle = (DenseUnitaryOracle(ind) if args.oracle == "dense"
              else RippleCarryOracle(ind))
    solver = ShorECDLPSolver(curve, G, Q, n, oracle=oracle, num_counting=args.t)
    qc = solver.build_circuit()

    svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())
    backend = svc.backend(args.backend)
    sim = AerSimulator.from_backend(backend)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    qc_t = pm.run(qc)

    print(f"  running noisy sim...")
    t0 = time.time()
    counts = sim.run(qc_t, shots=args.shots, seed_simulator=args.seed).result().get_counts()
    print(f"    done in {time.time()-t0:.1f}s, {len(counts)} unique outcomes")

    shots = []
    for bs, cnt in counts.items():
        if len(bs) != 2 * args.t + pt_w:
            continue
        k = int(bs[:args.t], 2) % n
        j = int(bs[args.t:2 * args.t], 2) % n
        r = int(bs[2 * args.t:], 2) % n
        for _ in range(cnt):
            shots.append((j, k, r))
    print(f"  parsed {len(shots):,} shots")
    print()

    print(f"  {'variant':<22} {'d_true_rank':>11}  {'gap':>7}  "
          f"{'top-3':>20}  {'top-3 in d-class':>17}")
    print("  " + "-" * 90)

    d_class = {d_true, (n - d_true) % n}
    for name, scorer in VARIANTS:
        scores = {d: scorer(d, shots, n, args.t, peaks) for d in range(n)}
        rank, gap, sorted_s = rank_and_gap(scores, d_true)
        top3 = [d for d, _ in sorted_s[:3]]
        in_d_class = sum(1 for d in top3 if d in d_class)
        print(f"  {name:<22} {rank:>11}  {gap:>6.4f}  "
              f"{str(top3):>20}  {in_d_class}/3")


if __name__ == "__main__":
    main()
