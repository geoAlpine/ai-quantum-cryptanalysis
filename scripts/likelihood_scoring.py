"""
Maximum-likelihood d-recovery via per-d-hypothesis noiseless calibration.

For each candidate d' ∈ [0, n), build the Shor circuit with ``Q' = d' · G``
in place of the true ``Q``, simulate noiselessly, and tabulate the
exact ideal-amplitude probability ``P_d'(j, k, r)`` for every outcome.

For a real hardware-noisy data set, compute total log-likelihood
``log L(d') = Σ_i log P_d'(j_i, k_i, r_i)`` and pick ``argmax_d' L(d')``.

This is the theoretically optimal estimator under the assumption that
hardware noise approximates the noiseless distribution. It's
computationally feasible only for small n (each d-hypothesis needs a
full noiseless simulation), but for the Phase 1 m=3 (n=7) target it
takes ~10 seconds and tells us whether the likelihood-based approach
gives a cleaner d-class top-1 than the HNP geometric score.

Usage:
    python scripts/likelihood_scoring.py --bits 4 --t 6 --oracle dense
    python scripts/likelihood_scoring.py --bits 4 --t 6 --noisy-from ibm_kingston \\
        --shots 2048
"""
from __future__ import annotations

import argparse
import math
import time
from collections import defaultdict
from typing import Optional

from challenges import get_challenge
from ecc import EllipticCurve, ECPoint
from quantum_ecc import load_token
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)
from qiskit import transpile
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator


def build_calibration_table(c, t: int, oracle_kind: str,
                              shots_per_d: int = 8192,
                              noisy_from: Optional[str] = None,
                              verbose: bool = True) -> tuple[dict, int]:
    """For each d' ∈ [1, n), build a Shor circuit with Q' = d'·G and
    simulate. Returns ``(table, pt_w)`` where ``table[d'][(j, k, r)] =
    P_d'(j, k, r)``."""
    n = c.n
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)

    # Optional noisy mode
    if noisy_from:
        from qiskit_ibm_runtime import QiskitRuntimeService
        svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())
        backend = svc.backend(noisy_from)
        sim = AerSimulator.from_backend(backend)
        pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    else:
        sim = AerSimulator()
        pm = None

    table: dict[int, dict] = {}
    pt_w = None
    for d_prime in range(1, n):
        # Build Q' = d_prime * G
        Q_prime = curve.scalar_mul(d_prime, G)
        if Q_prime.is_infinity:
            continue
        ind = SubgroupIndexer(curve, G, n)
        oracle = (DenseUnitaryOracle(ind) if oracle_kind == "dense"
                  else RippleCarryOracle(ind))
        solver = ShorECDLPSolver(curve, G, Q_prime, n, oracle=oracle, num_counting=t)
        if pt_w is None:
            pt_w = solver.oracle.point_register_width()
        qc = solver.build_circuit()
        if pm is not None:
            qc_run = pm.run(qc)
        else:
            qc_run = transpile(qc, sim, optimization_level=1)
        t0 = time.time()
        counts = sim.run(qc_run, shots=shots_per_d).result().get_counts()
        # Normalise to probabilities
        total = sum(counts.values())
        prob_table = {}
        for bs, cnt in counts.items():
            if len(bs) != 2 * t + pt_w:
                continue
            k = int(bs[:t], 2) % n
            j = int(bs[t:2 * t], 2) % n
            r = int(bs[2 * t:], 2) % n
            prob_table[(j, k, r)] = prob_table.get((j, k, r), 0.0) + cnt / total
        table[d_prime] = prob_table
        if verbose:
            print(f"  calibrated d'={d_prime}: {len(prob_table)} unique outcomes, "
                  f"sim {time.time()-t0:.1f}s")
    return table, pt_w


def log_likelihood(shots, table, d_prime: int, smoothing: float = 1e-9) -> float:
    p_table = table[d_prime]
    ll = 0.0
    for (j, k, r) in shots:
        p = p_table.get((j, k, r), smoothing)
        if p <= 0:
            p = smoothing
        ll += math.log(p)
    return ll / max(1, len(shots))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, default=4)
    ap.add_argument("--t", type=int, default=6)
    ap.add_argument("--oracle", choices=["dense", "ripple"], default="dense")
    ap.add_argument("--calib-shots", type=int, default=16384,
                    help="shots per d-hypothesis for the calibration table")
    ap.add_argument("--data-shots", type=int, default=2048)
    ap.add_argument("--data-noisy-from", default=None,
                    help="if set, use noisy-Aer for the EVALUATION data "
                         "(not the calibration — keep that noiseless)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    c = get_challenge(args.bits)
    n = c.n
    d_true = c.expected_d
    m = max(1, (n - 1).bit_length())
    pt_w_expected = m if args.oracle == "dense" else m + 1

    print(f"=== Likelihood-based d-recovery ===")
    print(f"  bits={args.bits} m={m} n={n} d_true={d_true} t={args.t}")
    print(f"  calibration: noiseless Aer × {n-1} d-hypotheses × {args.calib_shots} shots")
    print(f"  evaluation : {'noisy ('+args.data_noisy_from+')' if args.data_noisy_from else 'noiseless'} "
          f"× {args.data_shots} shots")
    print()

    # Calibration table — always noiseless (the "model")
    print(f"  building calibration table...")
    t0 = time.time()
    table, pt_w = build_calibration_table(
        c, args.t, args.oracle,
        shots_per_d=args.calib_shots,
        noisy_from=None,
        verbose=True,
    )
    print(f"  calibration done in {time.time()-t0:.1f}s")
    print()

    # Generate evaluation data
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    ind = SubgroupIndexer(curve, G, n)
    oracle = (DenseUnitaryOracle(ind) if args.oracle == "dense"
              else RippleCarryOracle(ind))
    solver = ShorECDLPSolver(curve, G, Q, n, oracle=oracle, num_counting=args.t)
    qc = solver.build_circuit()

    if args.data_noisy_from:
        from qiskit_ibm_runtime import QiskitRuntimeService
        svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())
        backend = svc.backend(args.data_noisy_from)
        sim = AerSimulator.from_backend(backend)
        pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
        qc_t = pm.run(qc)
    else:
        sim = AerSimulator()
        qc_t = transpile(qc, sim, optimization_level=1)

    print(f"  running evaluation sim...")
    t0 = time.time()
    counts = sim.run(qc_t, shots=args.data_shots, seed_simulator=args.seed).result().get_counts()
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

    # Score each d'
    scores = []
    for d_prime in range(1, n):
        ll = log_likelihood(shots, table, d_prime)
        scores.append((d_prime, ll))
    scores.sort(key=lambda x: -x[1])  # higher log-likelihood = better

    rank_d_true = next(i for i, (d, _) in enumerate(scores) if d == d_true) + 1
    print()
    print(f"  log-likelihood ranking (higher = better):")
    for rank, (d, ll) in enumerate(scores, 1):
        mark = "  <-- d_true" if d == d_true else (
            "  (anti-d_true)" if d == (n - d_true) % n else ""
        )
        print(f"    rank {rank}: d={d}, log L={ll:.4f}{mark}")
    print()
    print(f"  d_true rank: {rank_d_true} / {n-1}")
    best_d = scores[0][0]
    d_class = {d_true, (n - d_true) % n}
    print(f"  top-1 = d={best_d}  in d-class: {best_d in d_class}")


if __name__ == "__main__":
    main()
