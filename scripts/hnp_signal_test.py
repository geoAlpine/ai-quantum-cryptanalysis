"""
HNP signal-gap test: does ``hnp_score_search`` discriminate ``d_true``
at larger ``n`` than n=7?

Runs noiseless Aer at a chosen (m, t), parses the shots, and reports:
  - Collective vote test (no-side-channel, our reference diagnostic).
  - HNP score search (exhaustive ``d`` enumeration via the relation
    ``n·(j + d·k) - r·M ≡ 0 (mod n·M)``).

The interesting metric for "true world record" planning is the
score-gap-ratio at noiseless: if it stays around the 1.6% we saw at
n=7, the relation needs more work; if it widens significantly with
larger n, the methodology is sound and the next move is finding
where hardware noise still preserves the gap.

Usage:
    python scripts/hnp_signal_test.py --bits 8 --t 3 --shots 8192
    python scripts/hnp_signal_test.py --bits 8 --t 4 --shots 8192
    python scripts/hnp_signal_test.py --bits 9 --t 4 --shots 8192
"""
from __future__ import annotations

import argparse
import math
import time

import numpy as np
from qiskit import transpile
from qiskit_aer import AerSimulator

from cf_lift import cf_lift_v3
from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import hnp_score, hnp_score_search
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)


def run_noiseless(bits: int, t: int, shots: int, oracle_kind: str):
    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    ind = SubgroupIndexer(curve, G, c.n)
    oracle = (
        DenseUnitaryOracle(ind) if oracle_kind == "dense" else RippleCarryOracle(ind)
    )
    solver = ShorECDLPSolver(curve, G, Q, c.n, oracle=oracle, num_counting=t)
    plan = solver.plan()
    qc = solver.build_circuit()
    print(f"  building & transpiling {plan.total_qubits}-qubit circuit...")
    sim = AerSimulator(method="automatic")
    qc_t = transpile(qc, sim, optimization_level=1)
    t0 = time.time()
    counts = sim.run(qc_t, shots=shots).result().get_counts()
    sim_time = time.time() - t0
    print(f"  done sim in {sim_time:.1f}s ({len(counts)} unique outcomes)")
    return c, solver, counts, sim_time


def parse_shots(counts: dict, t: int, pt_w: int, n: int):
    shots = []
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k = int(bs[:t], 2) % n
        j = int(bs[t:2 * t], 2) % n
        r = int(bs[2 * t:], 2) % n
        for _ in range(cnt):
            shots.append((j, k, r))
    return shots


def collective_vote(shots, n: int, t: int, d_true: int, window: int = 4):
    votes = np.zeros(n, dtype=np.int64)
    cf_cache: dict[int, list[int]] = {}

    def cf(x: int) -> list[int]:
        if x not in cf_cache:
            cf_cache[x] = cf_lift_v3(x, t, n, window=window)
        return cf_cache[x]

    for (j, k, r) in shots:
        a_list = cf(j)
        b_list = cf(k)
        b_invs = []
        for b in b_list:
            if b == 0 or math.gcd(b, n) != 1:
                continue
            b_invs.append((b, pow(b, -1, n)))
        d_set: set[int] = set()
        for a in a_list:
            r_minus_a = (r - a) % n
            for _, b_inv in b_invs:
                d_set.add((r_minus_a * b_inv) % n)
        for d in d_set:
            votes[d] += 1

    total = int(votes.sum())
    e_u = total / n
    std = math.sqrt(e_u * max(0, 1 - 1 / n))
    v = int(votes[d_true])
    rank = int((votes > v).sum() + 1)
    return {
        "votes_d_true": v,
        "ratio": v / e_u if e_u else 0.0,
        "z_score": (v - e_u) / std if std else 0.0,
        "rank": rank,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, required=True)
    ap.add_argument("--t", type=int, required=True)
    ap.add_argument("--shots", type=int, default=8192)
    ap.add_argument("--oracle", choices=["dense", "ripple"], default="ripple")
    ap.add_argument("--cv-window", type=int, default=4,
                    help="cf_window for collective vote (default narrow for small n)")
    args = ap.parse_args()

    c = get_challenge(args.bits)
    n = c.n
    d_true = c.expected_d
    m = (n - 1).bit_length()
    M = 1 << args.t

    print(f"=== HNP signal test ===")
    print(f"  bits={args.bits}  m={m}  n={n:,}  d_true={d_true}")
    print(f"  t={args.t}  M={M}  4^t/n={(M*M)/n:.2f}  oracle={args.oracle}")
    print(f"  shots={args.shots}")
    print()

    c_obj, solver, counts, sim_time = run_noiseless(
        args.bits, args.t, args.shots, args.oracle
    )
    pt_w = solver.oracle.point_register_width()
    shots = parse_shots(counts, args.t, pt_w, n)
    print(f"  parsed {len(shots):,} shots")
    print()

    # Collective vote
    print("=== Collective vote (no-side-channel) ===")
    cv = collective_vote(shots, n, args.t, d_true, window=args.cv_window)
    cv_argmax = "✓" if cv["rank"] == 1 else "✗"
    print(f"  d_true ratio  : {cv['ratio']:.3f}x uniform")
    print(f"  d_true z-score: {cv['z_score']:+.2f}σ")
    print(f"  d_true rank   : {cv['rank']} / {n}  [argmax={cv_argmax}]")
    print()

    # HNP score search
    print("=== HNP score search (exhaustive d in [0, n)) ===")
    t0 = time.time()
    result = hnp_score_search(shots, n, args.t, expected_d=d_true)
    elapsed = time.time() - t0
    print(f"  searched {n} candidate d's in {elapsed:.1f}s")
    print(f"  recovered d   : {result['d_recovered']}")
    print(f"  matches d_true: {result['matches_expected']}")
    print(f"  score gap     : {result['score_gap_ratio']:.4f} "
          f"(2nd/1st score ratio = {result['second_best_score']/max(1e-9, result['best_score']):.4f})")
    print(f"  top 5:")
    for d, s in result["top5"]:
        mark = "  <-- d_true" if d == d_true else ""
        print(f"    d={d:<5}  score={s:.2f}{mark}")
    # Where does d_true rank in HNP score?
    sorted_scores = sorted(
        ((d, hnp_score(d, shots, n, args.t)) for d in range(n)),
        key=lambda x: x[1],
    )
    d_true_rank = next(i for i, (d, _) in enumerate(sorted_scores) if d == d_true) + 1
    print(f"  d_true rank in HNP: {d_true_rank} / {n}")


if __name__ == "__main__":
    main()
