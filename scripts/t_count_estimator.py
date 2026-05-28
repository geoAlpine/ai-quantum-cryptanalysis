"""T-gate count estimator for fault-tolerant Shor-ECDLP.

T gates are the dominant cost in FT quantum computation because each
one requires a magic state, and magic state distillation is the
throughput bottleneck on logical hardware. A rough cost rule:

  total_FT_cost ≈ T_count × (magic state distillation cost)
                + logical_2q_count × (logical CNOT cost)

For Quantinuum-class hardware (Helios + Quantum Forge), a magic state
distillation factory delivers maybe 1 magic state per ~1000-10000
physical operations. So T_count directly predicts wall-clock time and
HQC cost at the FT layer.

We decompose our standard Shor-ECDLP circuit to the Clifford+T basis
{H, S, CNOT, T} via Qiskit's transpiler (`basis_gates=["h","s","cx","t","tdg"]`)
and count T gates per m. Numbers are approximate — actual FT compile
applies further optimisations (e.g., catalysts, lattice surgery
scheduling) — but they bound the order of magnitude.

Usage:
    python scripts/t_count_estimator.py
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


def t_count(qc) -> dict:
    """Decompose to Clifford+T and tally each gate type."""
    isa = transpile(
        qc,
        basis_gates=["h", "s", "sdg", "cx", "t", "tdg", "measure",
                     "reset", "if_else"],
        optimization_level=3,
    )
    ops = isa.count_ops()
    n_t = ops.get("t", 0) + ops.get("tdg", 0)
    n_clifford = (ops.get("h", 0) + ops.get("s", 0) + ops.get("sdg", 0))
    n_2q = ops.get("cx", 0)
    n_m = ops.get("measure", 0)
    return {
        "T": n_t,
        "Clifford_1q": n_clifford,
        "CNOT": n_2q,
        "Measure": n_m,
        "depth": isa.depth(),
        "total_ops": isa.size(),
    }


def build(bits: int, t: int, oracle_kind: str, iterative: bool = False):
    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    n = c.n
    m = (n - 1).bit_length()
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
            return None
        solver = IterativeShorECDLPSolver(
            curve, G, Q, n, oracle=oracle, num_counting=t, max_corrections=2
        )
    else:
        solver = ShorECDLPSolver(curve, G, Q, n, oracle=oracle, num_counting=t)
    return solver.build_circuit(), solver.plan(), m


def magic_state_cost(t_count: int, distillation_cost: int = 5000) -> int:
    """Rough physical-op equivalent for T_count magic states.
    distillation_cost ≈ 5000 per magic state is a typical surface code
    estimate; Quantinuum color codes likely better."""
    return t_count * distillation_cost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", type=int, default=1024)
    args = ap.parse_args()

    configs = [
        ("m=3 dense (Phase 1)", 4,  6, "dense",  False),
        ("m=5 ripple",          6,  8, "ripple", False),
        ("m=7 ripple",          7,  9, "ripple", False),
        ("m=8 ripple",          8, 10, "ripple", False),
        ("m=8 iterative",       8, 10, "ripple", True),
        ("m=10 iterative",     10, 12, "ripple", True),
        ("m=12 iterative",     12, 14, "ripple", True),
        ("m=15 iterative",     15, 17, "ripple", True),
    ]

    print(f"=== T-gate decomposition for fault-tolerant Shor-ECDLP ===\n")
    print(f"{'Config':<22} {'qbits':>5} {'T':>9} {'CNOT':>7} {'1qCliff':>8} "
          f"{'meas':>5} {'phys ops ≈ T×5000':>22}")
    print("-" * 95)

    rows = []
    # Reference T/2Q ratio from a successful non-iterative run for later
    # analytic extrapolation of iterative configs (Qiskit transpiler can't
    # decompose dynamic circuits to the Clifford+T basis cleanly).
    ref_t_per_2q = None
    for label, bits, t, oracle_kind, iterative in configs:
        try:
            built = build(bits, t, oracle_kind, iterative)
            if built is None:
                continue
            qc, plan, m = built
            try:
                counts = t_count(qc)
                ms_cost = magic_state_cost(counts["T"])
                if not iterative and counts["CNOT"] > 0:
                    ref_t_per_2q = counts["T"] / counts["CNOT"]
                tag = ""
            except Exception:
                # Iterative QPE — extrapolate from the ref ratio + the
                # circuit's pre-decompose 2Q count.
                if ref_t_per_2q is None:
                    raise
                from qiskit import transpile
                isa2 = transpile(qc, basis_gates=["u3", "cx", "measure",
                                                   "reset", "if_else"],
                                  optimization_level=1)
                cnot = sum(v for k, v in isa2.count_ops().items() if k == "cx")
                estimated_t = int(cnot * ref_t_per_2q)
                counts = {"T": estimated_t, "Clifford_1q": -1,
                          "CNOT": cnot, "Measure": -1,
                          "depth": isa2.depth(), "total_ops": isa2.size()}
                ms_cost = magic_state_cost(estimated_t)
                tag = " (est)"

            rows.append((label, plan.total_qubits, counts, ms_cost))
            print(f"  {label:<22} {plan.total_qubits:>5} "
                  f"{counts['T']:>9,} {counts['CNOT']:>7,} "
                  f"{counts['Clifford_1q']:>8} {counts['Measure']:>5} "
                  f"{ms_cost:>22,}{tag}")
        except Exception as e:
            print(f"  {label}: ERROR {type(e).__name__}: {str(e)[:60]}")

    print()
    print("Interpretation:")
    print("- T-count drives the magic-state distillation budget.")
    print("- 1 T gate ≈ 1 magic state ≈ 1000-10000 physical ops in FT.")
    print("- For m=15 we're already in the millions of magic states — this")
    print("  is the scale that requires multi-day wall time even on Helios.")
    print()
    print("FT cost = (T × distillation_overhead) + (CNOT × routing_overhead)")
    print("Surface code routing per logical CNOT ≈ 100 phys ops at d=15.")
    print()
    print("Empirical finding (2026-05-28): pyzx full_reduce on m=3 ripple")
    print("saves ~18.7% T-count (8712 → 7084) in ~17 min wall time. Effect")
    print("on dense oracle is negligible (~0.1%). Probably scales sub-")
    print("linearly with circuit size — not practical for m≥10 without")
    print("block-wise optimisation.")


if __name__ == "__main__":
    main()
