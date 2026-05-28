"""Quantinuum H2 HQC cost estimator for our Shor-ECDLP circuits.

Quantinuum's billing formula (Azure Quantum docs):

    HQC = 5 + C × (N_1q + 10 × N_2q + 5 × N_m) / 5000

where:
  - N_1q = single-qubit gates per shot
  - N_2q = native two-qubit gates per shot
  - N_m  = state-prep + intermediate + final measurements per shot
  - C    = shot count

The exact $/HQC rate is not public (requires sales@quantinuum.com). We
print estimates across a $5/HQC to $50/HQC range so the user can scale
to whatever quote they get.

For each (m, t, oracle) config we build the circuit with the existing
ShorECDLPSolver / IterativeShorECDLPSolver, transpile to a Qiskit
basis (h, rz, cx, measure) as a proxy for Quantinuum native (the cx
count is roughly equal to N_2q since both are entangling-gate-count
dominated), and report the HQC.

Usage:
    python scripts/quantinuum_cost_estimator.py
    python scripts/quantinuum_cost_estimator.py --shots 4096
"""
from __future__ import annotations

import argparse

from challenges import get_challenge
from ecc import EllipticCurve
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)
from qiskit import transpile


def count_gates(qc) -> dict[str, int]:
    """Transpile to a basis approximating Quantinuum natives and count gates."""
    # Quantinuum natives are essentially {U3, ZZ, measure}. Our cx-based
    # decomposition is comparable: each cx ≈ 1 ZZ + a few 1q gates. Use
    # the Qiskit standard basis as a proxy; counts here are
    # within ~30% of true native counts after pytket compilation.
    isa = transpile(qc, basis_gates=["u3", "cx", "measure"], optimization_level=3)
    ops = isa.count_ops()
    n_1q = sum(v for k, v in ops.items() if k in ("u3", "u", "u1", "u2", "h", "rz", "rx", "ry", "x", "y", "z", "s", "sdg", "t", "tdg", "p", "sx"))
    n_2q = sum(v for k, v in ops.items() if k in ("cx", "ecr", "cz", "rzz", "zz"))
    n_m = sum(v for k, v in ops.items() if k in ("measure", "reset"))
    return {"n_1q": n_1q, "n_2q": n_2q, "n_m": n_m, "depth": isa.depth(),
            "total_ops": isa.size()}


def hqc_cost(gates: dict, shots: int) -> float:
    return 5 + shots * (gates["n_1q"] + 10 * gates["n_2q"] + 5 * gates["n_m"]) / 5000


def build_one(bits: int, t: int, oracle_kind: str, iterative: bool = False):
    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    n = c.n
    m = max(1, (n - 1).bit_length())
    ind = SubgroupIndexer(curve, G, n)
    if oracle_kind == "dense":
        if m > 6:
            return None
        oracle = DenseUnitaryOracle(ind)
    else:
        oracle = RippleCarryOracle(ind)

    if iterative:
        from shor_iterative import IterativeShorECDLPSolver
        if oracle_kind == "dense":
            return None  # iterative supports ripple only
        solver = IterativeShorECDLPSolver(
            curve, G, Q, n, oracle=oracle,
            num_counting=t, max_corrections=2,
        )
    else:
        solver = ShorECDLPSolver(curve, G, Q, n, oracle=oracle, num_counting=t)

    qc = solver.build_circuit()
    plan = solver.plan()
    return qc, plan, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", type=int, default=1024,
                    help="Shot count per configuration (default 1024)")
    args = ap.parse_args()

    # Configurations to estimate. (label, bits, t, oracle, iterative)
    # bits=4 m=3, bits=6 m=5, bits=7 m=7, bits=8 m=8, bits=10 m=10,
    # bits=12 m=12, bits=15 m=15
    configs = [
        ("Phase 1 baseline",     4,  6, "dense",  False),
        ("Phase 2 (m=5 dense)",  6,  8, "dense",  False),
        ("Phase 2 ripple",       6,  8, "ripple", False),
        ("m=7 ripple",           7,  9, "ripple", False),
        ("m=8 ripple",           8, 10, "ripple", False),
        ("m=8 iterative",        8, 10, "ripple", True),
        ("m=10 ripple",         10, 12, "ripple", False),
        ("m=10 iterative",      10, 12, "ripple", True),
        ("m=12 iterative",      12, 14, "ripple", True),
        ("m=15 iterative",      15, 17, "ripple", True),
    ]

    print(f"Shot count per config: {args.shots}\n")
    print(f"{'Config':<22} {'qbits':>5} {'n_1q':>7} {'n_2q':>7} {'n_m':>5} "
          f"{'HQC':>10}  est $ @ $5/$10/$50 per HQC")
    print("-" * 95)

    for label, bits, t, oracle_kind, iterative in configs:
        try:
            built = build_one(bits, t, oracle_kind, iterative)
            if built is None:
                print(f"  {label:<22}  -- skip (oracle not supported)")
                continue
            qc, plan, m = built
            gates = count_gates(qc)
            hqc = hqc_cost(gates, args.shots)
            usd_lo = hqc * 5
            usd_med = hqc * 10
            usd_hi = hqc * 50
            qbits = plan.total_qubits
            print(f"  {label:<22} {qbits:>5} {gates['n_1q']:>7} "
                  f"{gates['n_2q']:>7} {gates['n_m']:>5} {hqc:>10,.0f}  "
                  f"${usd_lo:>9,.0f} / ${usd_med:>9,.0f} / ${usd_hi:>10,.0f}")
        except Exception as e:
            print(f"  {label:<22}  ERROR {type(e).__name__}: {str(e)[:50]}")

    print()
    print("Notes:")
    print("- Standard (non-iterative) at m≥10 may need ripple oracle + 30+ qubits.")
    print("- Iterative QPE saves ~m+t-2 qubits via mid-circuit measure + recycle.")
    print("- $/HQC rate is non-public; estimates span a wide range. Confirm with")
    print("  sales@quantinuum.com before committing to runs at m≥8.")


if __name__ == "__main__":
    main()
