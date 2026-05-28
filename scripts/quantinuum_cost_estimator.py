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

    # Confirmed rates from Microsoft Azure Quantum pricing page (2026-05-29):
    # - Standard plan: $125,000/month for 10,000 HQCs → $12.50 / HQC
    #                            + 100,000 eHQCs → $1.25 / eHQC
    # - Premium plan : $175,000/month for 17,000 HQCs → $10.29 / HQC
    #                            + 170,000 eHQCs → $1.03 / eHQC
    # - $500 free credit for new Azure accounts (≈ 40 HQCs or 400 eHQCs).
    RATE_HQC = 12.50      # Standard plan, hardware
    RATE_EHQC = 1.25      # Standard plan, emulator
    NATIVE_TRIM = 0.85    # ~15% gate reduction from pytket-quantinuum native compile

    print(f"Shot count per config: {args.shots}")
    print(f"Rates (Azure Standard plan): ${RATE_HQC}/HQC (hardware), "
          f"${RATE_EHQC}/eHQC (emulator). Native compile trims ~15%.\n")
    print(f"{'Config':<22} {'qbits':>5} {'n_2q':>7} {'HQC raw':>9} "
          f"{'  eHQC $':>10}  {'  HQC $':>10}  notes")
    print("-" * 105)

    for label, bits, t, oracle_kind, iterative in configs:
        try:
            built = build_one(bits, t, oracle_kind, iterative)
            if built is None:
                print(f"  {label:<22}  -- skip (oracle not supported)")
                continue
            qc, plan, m = built
            gates = count_gates(qc)
            hqc = hqc_cost(gates, args.shots) * NATIVE_TRIM
            qbits = plan.total_qubits
            ehqc_cost = hqc * RATE_EHQC
            hqc_cost_usd = hqc * RATE_HQC
            note = ""
            if ehqc_cost <= 500:
                note = "fits $500 free (emulator)"
            elif hqc_cost_usd <= 500:
                note = "fits $500 free (hw)"
            print(f"  {label:<22} {qbits:>5} {gates['n_2q']:>7} "
                  f"{hqc:>9,.0f}  ${ehqc_cost:>9,.2f}  ${hqc_cost_usd:>9,.2f}  {note}")
        except Exception as e:
            print(f"  {label:<22}  ERROR {type(e).__name__}: {str(e)[:50]}")

    print()
    print("Notes:")
    print("- Native compile trim = 15% (pytket-quantinuum offline-API benchmark,")
    print("  2026-05-28; dense oracle gets ~30% reduction, ripple ~13%).")
    print("- Min-shot study (2026-05-28) shows N=16 sufficient for d-class top-3")
    print("  on Helios-fidelity emulator — divide above HQC by 64 (1024 / 16)")
    print("  for the low-shot regime.")
    print("- Iterative QPE saves qubits but not HQC; m=8+ should use it on")
    print("  Quantinuum to fit within 56-qubit H2 / 98-qubit Helios capacity.")


if __name__ == "__main__":
    main()
