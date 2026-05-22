"""
Noisy preview for the iterative (semiclassical) Shor variant.

Mirrors ``scripts/noisy_preview.py`` but uses
``IterativeShorECDLPSolver`` instead of the standard ``ShorECDLPSolver``.
Dense oracle isn't supported by the iterative path yet, so we always
use ripple — which means significantly more 2Q gates after transpile
(~8K vs ~1.2K for dense at m=3 t=6). This script tells us whether the
qubit savings of the iterative approach are worth the per-shot fidelity
cost on real hardware noise.

Usage:
    python scripts/noisy_preview_iterative.py --bits 4 --t 6 --max-corr 2 \\
        --backend ibm_kingston --shots 2048
"""
from __future__ import annotations

import argparse
import time

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import hnp_recover_with_verification, hnp_score
from quantum_ecc import load_token
from shor_iterative import IterativeShorECDLPSolver
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator
from qiskit_ibm_runtime import QiskitRuntimeService


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, default=4)
    ap.add_argument("--t", type=int, default=6)
    ap.add_argument("--max-corr", type=int, default=2)
    ap.add_argument("--backend", default="ibm_kingston")
    ap.add_argument("--shots", type=int, default=2048)
    ap.add_argument("--top-k", type=int, default=7)
    args = ap.parse_args()

    c = get_challenge(args.bits)
    n = c.n
    d_true = c.expected_d
    m = max(1, (n - 1).bit_length())

    print(f"=== Iterative noisy preview ===")
    print(f"  bits={args.bits} m={m} n={n} d_true={d_true} t={args.t} mc={args.max_corr}")
    print(f"  backend={args.backend}, shots={args.shots}")

    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    solver = IterativeShorECDLPSolver(curve, G, Q, n,
                                        num_counting=args.t,
                                        max_corrections=args.max_corr)
    plan = solver.plan()
    print(f"  iterative qubits: {plan.total_qubits} (savings {plan.qubit_savings})")
    pt_w = solver.oracle.point_register_width()

    svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())
    backend = svc.backend(args.backend)
    sim = AerSimulator.from_backend(backend)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    qc = solver.build_circuit()
    qc_t = pm.run(qc)
    cx = sum(v for k_, v in qc_t.count_ops().items() if k_ in ("cx", "ecr", "cz"))
    print(f"  transpiled: depth={qc_t.depth()}  2Q={cx}  est-fid={0.995**cx:.2e}")

    print(f"  running noisy sim...")
    t0 = time.time()
    counts = sim.run(qc_t, shots=args.shots).result().get_counts()
    print(f"    done in {time.time()-t0:.1f}s, {len(counts)} unique outcomes")

    t = args.t
    shots = []
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k = int(bs[:t], 2) % n
        j = int(bs[t:2 * t], 2) % n
        r = int(bs[2 * t:], 2) % n
        for _ in range(cnt):
            shots.append((j, k, r))
    print(f"  parsed {len(shots):,} shots")

    sorted_d = sorted(
        ((d, hnp_score(d, shots, n, t)) for d in range(n)),
        key=lambda x: x[1],
    )
    rank_dt = next(i for i, (d, _) in enumerate(sorted_d) if d == d_true) + 1
    print(f"  d_true HNP rank: {rank_dt} / {n}")
    print(f"  top {min(args.top_k, n)}:")
    for d, s in sorted_d[:args.top_k]:
        mark = "  <-- d_true" if d == d_true else (
            "  (anti-d_true)" if d == (n - d_true) % n else ""
        )
        print(f"    d={d}  score={s:.4f}{mark}")

    def verify(d):
        return curve.scalar_mul(d, G) == Q

    result = hnp_recover_with_verification(shots, n, t, verify, top_k=args.top_k)
    if result["d_recovered"] == d_true:
        print(f"  ✓ RECOVERED via HNP rank {result['rank_in_hnp']} "
              f"(anti-d: {result['verified_via_anti_d']})")
    else:
        print(f"  ✗ FAILED (recovered = {result['d_recovered']})")


if __name__ == "__main__":
    main()
