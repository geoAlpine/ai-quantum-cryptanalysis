"""
Noisy preview: predict what an IBM submission will deliver, **before**
spending QPU budget.

Loads the noise model from a real IBM backend (free metadata fetch — no
QPU consumed), runs the same circuit on Aer with that noise, and applies
the HNP-with-verification post-processor. Reports d_true rank, top-K
candidates, recovery success, and the breakdown by anti-d partner.

The expected workflow before any real submission:

  1. ``python scripts/preflight.py --bits 4 --t 6 --backend ibm_kingston``
     to confirm qubit/depth/fidelity look sane.
  2. ``python scripts/noisy_preview.py --bits 4 --t 6 --oracle dense \\
        --backend ibm_kingston --shots 8192``
     to confirm the HNP recovery still resolves d_true.
  3. Only if (2) passes, run ``submit_18bit.py`` for real.

Usage:
    python scripts/noisy_preview.py --bits 4 --t 6 --oracle dense \\
        --backend ibm_kingston --shots 8192
"""
from __future__ import annotations

import argparse
import time

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import (
    hnp_recover_with_verification,
    hnp_score,
    hnp_score_search,
)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, required=True)
    ap.add_argument("--t", type=int, required=True)
    ap.add_argument("--oracle", choices=["dense", "ripple"], default="dense")
    ap.add_argument("--backend", default="ibm_kingston",
                    help="IBM backend whose noise model to use (free metadata)")
    ap.add_argument("--shots", type=int, default=8192)
    ap.add_argument("--top-k", type=int, default=10)
    args = ap.parse_args()

    c = get_challenge(args.bits)
    n = c.n
    d_true = c.expected_d
    m = max(1, (n - 1).bit_length())

    print(f"=== Noisy preview ===")
    print(f"  bits={args.bits}  m={m}  n={n:,}  d_true={d_true}")
    print(f"  t={args.t}  oracle={args.oracle}  M/n={(1 << args.t) / n:.2f}")
    print(f"  backend (noise source) = {args.backend}, shots = {args.shots}")
    print()

    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    ind = SubgroupIndexer(curve, G, n)
    oracle = (
        DenseUnitaryOracle(ind) if args.oracle == "dense" else RippleCarryOracle(ind)
    )
    solver = ShorECDLPSolver(curve, G, Q, n, oracle=oracle, num_counting=args.t)
    plan = solver.plan()
    print(f"  circuit: {plan.total_qubits} qubits, t={plan.num_counting}")

    print(f"  fetching backend noise (no QPU spent)...")
    svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())
    backend = svc.backend(args.backend)
    sim = AerSimulator.from_backend(backend)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)

    qc = solver.build_circuit()
    print(f"  building circuit & transpiling...")
    qc_t = pm.run(qc)
    cx = sum(v for k, v in qc_t.count_ops().items() if k in ("cx", "ecr", "cz"))
    print(f"    transpiled: depth={qc_t.depth()}  2Q={cx}  est-fid={0.995**cx:.2e}")

    print(f"  running noisy sim ({args.shots} shots)...")
    t0 = time.time()
    counts = sim.run(qc_t, shots=args.shots).result().get_counts()
    sim_time = time.time() - t0
    print(f"    done in {sim_time:.1f}s, {len(counts)} unique outcomes")

    pt_w = oracle.point_register_width()
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
    print()

    # 1) HNP score search — diagnostic of signal strength.
    print(f"=== HNP score search ===")
    result = hnp_score_search(shots, n, t, expected_d=d_true)
    sorted_d = sorted(((d, hnp_score(d, shots, n, t)) for d in range(n)), key=lambda x: x[1])
    d_true_rank = next(i for i, (d, _) in enumerate(sorted_d) if d == d_true) + 1
    print(f"  recovered (top-1) : {result['d_recovered']} "
          f"(matches d_true: {result['matches_expected']})")
    print(f"  d_true rank       : {d_true_rank} / {n}")
    print(f"  score gap (1→2)   : {result['score_gap_ratio']:.4f}")
    print(f"  top-{min(args.top_k, n)}:")
    for d, s in result["top5"][:args.top_k]:
        mark = "  <-- d_true" if d == d_true else (
            "  (anti-d_true)" if (n - d) % n == d_true else ""
        )
        print(f"    d={d:<5}  score={s:.4f}{mark}")
    print()

    # 2) HNP + verification — production recovery flow.
    print(f"=== HNP + verify recovery (top-K={args.top_k}) ===")
    def verify(d: int) -> bool:
        return curve.scalar_mul(d, G) == Q

    recovered = hnp_recover_with_verification(
        shots, n, t, verify, top_k=args.top_k,
    )
    if recovered["d_recovered"] is not None:
        print(f"  ✓ RECOVERED d = {recovered['d_recovered']} "
              f"(d_true = {d_true}, match={recovered['d_recovered'] == d_true})")
        print(f"    via HNP rank {recovered['rank_in_hnp']} "
              f"(anti-d partner: {recovered['verified_via_anti_d']})")
        print(f"    verify time: {recovered['elapsed_seconds']:.2f}s")
    else:
        print(f"  ✗ FAILED — d_true not found within top-{args.top_k}")

    print()
    print(f"=== Prediction ===")
    if recovered["d_recovered"] == d_true:
        print(f"  HARDWARE RUN SHOULD SUCCEED — recovery via HNP top-K verify.")
        print(f"  Submission command:")
        print(f"    python scripts/submit_18bit.py --bits {args.bits} --t {args.t} \\")
        print(f"        --oracle {args.oracle} --extractor hnp \\")
        print(f"        --backend {args.backend} --shots {args.shots}")
    else:
        print(f"  HARDWARE RUN LIKELY TO FAIL — re-tune parameters first.")
        print(f"  Options: (a) try a different t, (b) try the iterative variant,")
        print(f"  (c) increase shots, (d) try a less noisy backend.")


if __name__ == "__main__":
    main()
