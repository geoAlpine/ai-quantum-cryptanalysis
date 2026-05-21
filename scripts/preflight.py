"""
Preflight resource estimator for any (bits, t, shots, backend) combination.

Builds the production circuit, transpiles against an IBM backend (free
metadata fetch — no QPU consumed), and prints qubits, depth, 2Q gate count,
crude fidelity estimate, and projected v3-extractor hit rate. Use this
before every real submission to avoid burning the 10-min monthly QPU budget
on a misconfigured run.

Two modes:
  - With --backend <name>  : transpile against real backend (needs IBM auth)
  - With --no-backend      : pre-transpile resource counts only (qubits +
                              raw circuit ops). Skips the slow transpile and
                              the IBM round-trip; useful for quick what-if
                              sweeps.

Usage:
    python scripts/preflight.py --bits 25 --t 12 --shots 20000
    python scripts/preflight.py --bits 22 --t 12 --shots 35000 --backend ibm_kingston
    python scripts/preflight.py --bits 18 --t 10 --shots 10000 --no-backend
    python scripts/preflight.py --bits 25 --scan-shots 10000 20000 30000 50000
"""

import argparse
import math
import os
import sys

from challenges import get_challenge
from cf_lift import CF_C_TABLE, estimate_c_per_shot
from ecc import EllipticCurve
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)


def fmt_int(x: int) -> str:
    return f"{x:,}"


def project_hits(c_per_shot: int, shots: int, n: int) -> dict:
    expected = c_per_shot * shots / n
    return {
        "C_per_shot": c_per_shot,
        "expected_hits": expected,
        "p_at_least_one": 1.0 - math.exp(-expected),
        "coverage_pct": 100 * c_per_shot / n,
    }


def build_solver(bits: int, t: int):
    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    lazy = c.n >= 5_000_000
    ind = SubgroupIndexer(curve, G, c.n, lazy=lazy)
    m = max(1, (c.n - 1).bit_length())
    oracle = DenseUnitaryOracle(ind) if m <= 6 else RippleCarryOracle(ind)
    solver = ShorECDLPSolver(curve, G, Q, c.n, oracle=oracle,
                             num_counting=t, lazy=lazy)
    return c, solver


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, required=True)
    ap.add_argument("--t", type=int, default=12)
    ap.add_argument("--shots", type=int, default=20000)
    ap.add_argument("--backend", default="ibm_fez",
                    help="IBM backend to transpile against (default ibm_fez)")
    ap.add_argument("--no-backend", action="store_true",
                    help="Skip backend transpile; report logical resources only")
    ap.add_argument("--cf-window", type=int, default=16,
                    help="v3 extractor window (8/16/32/64/128 calibrated)")
    ap.add_argument("--scan-shots", type=int, nargs="*",
                    help="Project expected hits at each shot count")
    args = ap.parse_args()

    c, solver = build_solver(args.bits, args.t)
    plan = solver.plan()

    print(f"=== Preflight: {args.bits}-bit Shor ECDLP ===")
    print(f"  curve   y² = x³ + 7 (mod {fmt_int(c.p)})")
    print(f"  n       = {fmt_int(c.n)}  (m = {(c.n-1).bit_length()})")
    print(f"  d_true  = {fmt_int(c.expected_d)}")
    print(f"  oracle  = {plan.oracle_name}, t = {plan.num_counting}")
    print(f"  4^t/n   = {4 ** args.t / c.n:.3f}")

    print(f"\n  logical qubits    = {plan.total_qubits}")
    print(f"    counting (j+k)  = {2 * plan.num_counting}")
    print(f"    point register  = {plan.point_width}")
    if plan.ancilla_widths:
        print(f"    ancillas        = {plan.ancilla_widths} "
              f"(total {sum(plan.ancilla_widths.values())})")

    if args.no_backend:
        print(f"\n  [--no-backend] Skipping circuit build / transpile.")
        cx_estimate = None
    else:
        print(f"\n  building circuit...")
        qc = solver.build_circuit()
        print(f"    pre-transpile: depth={qc.depth()}  ops={qc.size()}")

        from qiskit_ibm_runtime import QiskitRuntimeService
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
        from quantum_ecc import load_token

        print(f"\n  fetching backend metadata: {args.backend} (no QPU spent)...")
        svc = QiskitRuntimeService(channel="ibm_quantum_platform",
                                    token=load_token())
        backend = svc.backend(args.backend)
        print(f"    {backend.name}: n_qubits={backend.num_qubits}, "
              f"pending={backend.status().pending_jobs}")

        if plan.total_qubits > backend.num_qubits:
            print(f"  ERROR: circuit needs {plan.total_qubits} qubits, "
                  f"backend has {backend.num_qubits}.")
            return 1

        print(f"  transpiling at opt_level=3 (this is the slow step)...")
        pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
        isa = pm.run(qc)
        cx_estimate = sum(v for k, v in isa.count_ops().items()
                           if k in ("cx", "ecr", "cz"))
        fid = 0.995 ** cx_estimate
        print(f"    transpiled: depth={isa.depth()}  2Q={cx_estimate}  "
              f"est-fid={fid:.2e}")

    cw = args.cf_window
    c_per_shot = estimate_c_per_shot(cw)
    if cw in CF_C_TABLE:
        print(f"\n  v3 extractor: cf_window={cw} → ~{c_per_shot} C/shot "
              "(calibrated on 22-bit data)")
    else:
        print(f"\n  v3 extractor: cf_window={cw} (uncalibrated, "
              f"falling back to ~{c_per_shot} C/shot)")

    shot_list = args.scan_shots or [args.shots]
    print(f"\n  uniform-noise projection (n = {fmt_int(c.n)}):")
    print(f"    {'shots':>8}  {'E[hits]':>9}  {'P(≥1 hit)':>10}  "
          f"{'cov/shot':>9}")
    for s in shot_list:
        proj = project_hits(c_per_shot, s, c.n)
        print(f"    {s:>8}  {proj['expected_hits']:>9.2f}  "
              f"{proj['p_at_least_one']:>9.1%}   "
              f"{proj['coverage_pct']:>8.4f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
