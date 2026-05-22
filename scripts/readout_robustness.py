"""
Readout-noise robustness check: inject independent bit flips on top of
noiseless Aer output and report how the HNP recovery degrades.

Hardware noise has two phases: (1) **gate** errors that distort the
output distribution mid-circuit, and (2) **readout** errors that flip
single measurement bits at the end. The full noise-model Aer
simulations capture both, but they're slow (~10 min per 2048-shot run).
This script captures the readout component alone by post-processing a
noiseless run, which is fast (< 1s per trial).

The pattern: at p_flip=0 the recovery is exactly noiseless; we ramp
p_flip and observe the d_true HNP rank degradation. If d_true rank
stays in top-K for p_flip up to ~0.05 (5% per-bit readout error,
roughly twice IBM's typical 2–3% measurement error), our recovery is
robust to the readout-error component of hardware noise.

Usage:
    python scripts/readout_robustness.py --bits 4 --t 6 --oracle dense \\
        --shots 2048 --p-flips 0.0 0.02 0.05 0.1 --trials 5
"""
from __future__ import annotations

import argparse
import random
import statistics

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import hnp_recover_with_verification, hnp_score
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)
from qiskit import transpile
from qiskit_aer import AerSimulator


def flip_bits(bs: str, p: float, rng: random.Random) -> str:
    out = []
    for ch in bs:
        if rng.random() < p:
            out.append("1" if ch == "0" else "0")
        else:
            out.append(ch)
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, default=4)
    ap.add_argument("--t", type=int, default=6)
    ap.add_argument("--oracle", choices=["dense", "ripple"], default="dense")
    ap.add_argument("--shots", type=int, default=2048)
    ap.add_argument("--top-k", type=int, default=7)
    ap.add_argument("--p-flips", type=float, nargs="+",
                    default=[0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15])
    ap.add_argument("--trials", type=int, default=5)
    args = ap.parse_args()

    c = get_challenge(args.bits)
    n = c.n
    d_true = c.expected_d
    m = max(1, (n - 1).bit_length())
    pt_w = m if args.oracle == "dense" else m + 1

    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    ind = SubgroupIndexer(curve, G, n)
    oracle = (DenseUnitaryOracle(ind) if args.oracle == "dense"
              else RippleCarryOracle(ind))
    solver = ShorECDLPSolver(curve, G, Q, n, oracle=oracle, num_counting=args.t)
    qc = solver.build_circuit()
    sim = AerSimulator()
    qc_t = transpile(qc, sim, optimization_level=1)
    print(f"=== Readout-flip robustness ===")
    print(f"  bits={args.bits} t={args.t} oracle={args.oracle} n={n} d_true={d_true}")
    print(f"  shots={args.shots}  trials per p_flip = {args.trials}")
    print()
    print(f"  building noiseless counts...")
    counts = sim.run(qc_t, shots=args.shots).result().get_counts()
    print(f"    {len(counts)} unique outcomes")

    def verify(d):
        return curve.scalar_mul(d, G) == Q

    print()
    print(f"  {'p_flip':>8}  {'mean rank':>9}  {'recovery':>9}  {'sample top':>20}")
    print("  " + "-" * 60)
    for p in args.p_flips:
        ranks = []
        successes = 0
        sample_top = None
        for trial in range(args.trials):
            rng = random.Random(trial * 37 + int(p * 1000))
            # Apply bit flips
            flipped_shots = []
            for bs, cnt in counts.items():
                for _ in range(cnt):
                    bs_flip = flip_bits(bs, p, rng) if p > 0 else bs
                    if len(bs_flip) != 2 * args.t + pt_w:
                        continue
                    k = int(bs_flip[:args.t], 2) % n
                    j = int(bs_flip[args.t:2 * args.t], 2) % n
                    r = int(bs_flip[2 * args.t:], 2) % n
                    flipped_shots.append((j, k, r))

            sorted_d = sorted(
                ((d, hnp_score(d, flipped_shots, n, args.t)) for d in range(n)),
                key=lambda x: x[1],
            )
            rank = next(i for i, (d, _) in enumerate(sorted_d) if d == d_true) + 1
            ranks.append(rank)
            if trial == 0:
                sample_top = [d for d, _ in sorted_d[:3]]
            r = hnp_recover_with_verification(flipped_shots, n, args.t, verify,
                                                top_k=args.top_k)
            if r["d_recovered"] == d_true:
                successes += 1
        print(f"  {p:>8.3f}  {statistics.mean(ranks):>9.2f}  "
              f"{successes}/{args.trials:<3}  {str(sample_top):>20}")


if __name__ == "__main__":
    main()
