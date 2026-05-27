"""
Signal-vs-noise boundary scan — 2026-05-27 edition.

Generates the paper Figure data: for each (m, noise) combination, run the
full ShorECDLPSolver circuit on Aer (noiseless or with backend noise
model), then evaluate HNP signal under the *new* q-ary lattice extractor
+ likelihood filter.

Output: results/boundary_scan_2026-05-27.json (tabular signal metrics)
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import (
    hnp_recover_with_verification,
    hnp_score,
)
from shor_ecdlp import (
    DenseUnitaryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)
from quantum_ecc import load_token
from qiskit_aer import AerSimulator
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService


_BACKEND_CACHE: dict[str, tuple] = {}


def get_noisy(name: str):
    if name not in _BACKEND_CACHE:
        svc = QiskitRuntimeService(channel="ibm_quantum_platform",
                                    token=load_token())
        backend = svc.backend(name)
        sim = AerSimulator.from_backend(backend)
        pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
        _BACKEND_CACHE[name] = (sim, pm)
    return _BACKEND_CACHE[name]


def run_one(bits: int, t: int, noise: str | None, shots: int) -> dict:
    """Run one (m, noise) cell of the boundary scan."""
    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    n = c.n
    d_true = c.expected_d
    m = max(1, (n - 1).bit_length())

    ind = SubgroupIndexer(curve, G, n)
    oracle = DenseUnitaryOracle(ind)
    solver = ShorECDLPSolver(curve, G, Q, n, oracle=oracle, num_counting=t)
    qc = solver.build_circuit()

    t0 = time.time()
    if noise is None:
        sim = AerSimulator()
        from qiskit import transpile
        isa = transpile(qc, sim, optimization_level=1)
    else:
        sim, pm = get_noisy(noise)
        isa = pm.run(qc)
    transpile_s = time.time() - t0

    cx = sum(v for k, v in isa.count_ops().items()
             if k in ("cx", "ecr", "cz"))
    fid = 0.995 ** cx if cx else 1.0

    t1 = time.time()
    job = sim.run(isa, shots=shots)
    counts = job.result().get_counts()
    run_s = time.time() - t1

    # Parse shots
    pt_w = m
    shots_list = []
    for bs, cnt in counts.items():
        bs_clean = bs.replace(" ", "")
        if len(bs_clean) != 2 * t + pt_w:
            continue
        k = int(bs_clean[:t], 2) % n
        j = int(bs_clean[t:2 * t], 2) % n
        r = int(bs_clean[2 * t:], 2) % n
        for _ in range(cnt):
            shots_list.append((j, k, r))

    # HNP signal metrics
    M_ = 1 << t
    score_true = hnp_score(d_true, shots_list, n, t)
    scores = sorted(
        ((d, hnp_score(d, shots_list, n, t)) for d in range(n)),
        key=lambda x: x[1],
    )
    rank_true = 1 + next((i for i, (d, _) in enumerate(scores) if d == d_true), n)
    top1_score = scores[0][1]
    second_score = scores[1][1]
    gap = (second_score - top1_score) / max(1e-9, second_score) * 100  # %

    verify = lambda d: curve.scalar_mul(d, G) == Q
    result = hnp_recover_with_verification(shots_list, n, t, verify, top_k=7)

    return {
        "bits": bits, "n": n, "m": m, "t": t, "d_true": d_true,
        "noise": noise or "noiseless",
        "shots": shots,
        "M_over_n": M_ / n,
        "transpiled_2Q_gates": cx,
        "est_fidelity": fid,
        "transpile_sec": round(transpile_s, 2),
        "run_sec": round(run_s, 2),
        "rank_d_true": rank_true,
        "score_gap_pct": round(gap, 3),
        "argmax_d": scores[0][0],
        "argmax_score": round(top1_score, 4),
        "d_true_score": round(score_true, 4),
        "top5": [(d, round(s, 4)) for d, s in scores[:5]],
        "recovery_d": result["d_recovered"],
        "recovery_success": result["d_recovered"] == d_true,
        "recovery_rank": result["rank_in_hnp"],
        "via_anti_d": result["verified_via_anti_d"],
    }


def main():
    cells = [
        # (bits, t, noise, shots)
        (4, 6, None,             4096),  # m=3 noiseless
        (4, 6, "ibm_kingston",   2048),  # m=3 ibm_kingston
        (6, 8, None,             2048),  # m=5 noiseless
        (6, 8, "ibm_kingston",   1024),  # m=5 ibm_kingston (predict: no signal)
    ]

    results = []
    for bits, t, noise, shots in cells:
        label = f"m={(get_challenge(bits).n-1).bit_length()} {noise or 'noiseless'} shots={shots}"
        print(f"\n=== {label} ===")
        try:
            r = run_one(bits, t, noise, shots)
            print(f"  2Q-gates={r['transpiled_2Q_gates']}  "
                  f"est-fid={r['est_fidelity']:.2e}  "
                  f"run={r['run_sec']:.1f}s")
            print(f"  rank(d_true)={r['rank_d_true']}/{r['n']}  "
                  f"gap={r['score_gap_pct']:.2f}%  "
                  f"recovery={'✓' if r['recovery_success'] else '✗'} "
                  f"(rank {r['recovery_rank']}, anti_d={r['via_anti_d']})")
            results.append(r)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            results.append({"bits": bits, "t": t, "noise": noise, "error": str(e)})

    out_path = "results/boundary_scan_2026-05-27.json"
    os.makedirs("results", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"generated_at": "2026-05-27", "cells": results}, f, indent=2)
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
