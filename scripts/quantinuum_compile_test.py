"""Offline pytket-quantinuum compile test of our Shor-ECDLP circuits.

Builds the standard ShorECDLPSolver circuit, converts to pytket, then
compiles for Quantinuum H2 native gateset (ZZ-based, all-to-all
connectivity). Compares gate counts to the Qiskit-basis estimate used
in ``quantinuum_cost_estimator.py``.

This is the "free" validation step before paid HQC runs — confirms our
circuits are compatible with Quantinuum's stack and refines the cost
estimate.

Usage:
    python scripts/quantinuum_compile_test.py            # Phase 1 only
    python scripts/quantinuum_compile_test.py --all      # all configs
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

from pytket.extensions.qiskit import qiskit_to_tk
from pytket.extensions.quantinuum import QuantinuumBackend, QuantinuumAPIOffline


def build_qc(bits: int, t: int, oracle_kind: str, iterative: bool):
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
    qc = solver.build_circuit()
    return qc, solver.plan(), m


def qiskit_basis_counts(qc):
    """Reference: gate counts when transpiled to a generic basis (no Quantinuum knowledge)."""
    isa = transpile(qc, basis_gates=["u3", "cx", "measure"], optimization_level=3)
    ops = isa.count_ops()
    n_2q = sum(v for k, v in ops.items() if k in ("cx", "ecr", "cz"))
    n_1q = sum(v for k, v in ops.items()
               if k in ("u3", "u", "u1", "u2", "h", "rz", "rx", "ry", "x", "y", "z", "s", "sdg", "t", "tdg", "p", "sx"))
    n_m = sum(v for k, v in ops.items() if k in ("measure", "reset"))
    return {"n_1q": n_1q, "n_2q": n_2q, "n_m": n_m, "depth": isa.depth()}


def quantinuum_compile_counts(qc, device_name: str = "H2-1"):
    """Compile via pytket for Quantinuum H2 native gateset, count gates."""
    # pytket can't ingest custom multi-qubit unitaries directly (e.g. our
    # DenseUnitaryOracle's 4-qubit unitary). Decompose to a basic Qiskit
    # gateset first so qiskit_to_tk sees only 1- and 2-qubit primitives.
    qc_basic = transpile(qc, basis_gates=["u3", "cx", "measure"],
                          optimization_level=1)
    tkc = qiskit_to_tk(qc_basic)

    # Use the offline API so no credentials are needed.
    api = QuantinuumAPIOffline()
    backend = QuantinuumBackend(device_name=device_name, api_handler=api)

    # default_compilation_pass at the highest optimisation level
    compiled = backend.get_compiled_circuit(tkc, optimisation_level=2)

    # Count by iterating commands. pytket OpType is an enum; str(op_type)
    # gives names like "OpType.ZZPhase" so we slice the prefix off.
    op_counts: dict[str, int] = {}
    for cmd in compiled.get_commands():
        name = str(cmd.op.type).split(".")[-1]
        op_counts[name] = op_counts.get(name, 0) + 1
    def by_name(s: str) -> int:
        return op_counts.get(s, 0)
    n_2q = (by_name("ZZPhase") + by_name("ZZMax")
            + by_name("CX") + by_name("CZ") + by_name("ECR"))
    n_1q_keys = ("PhasedX", "Rz", "U1q", "U2q", "U3", "TK1",
                 "H", "X", "Y", "Z", "S", "T", "Sdg", "Tdg")
    n_1q = sum(by_name(k) for k in n_1q_keys)
    n_m = by_name("Measure") + by_name("Reset")
    return {
        "n_1q": n_1q,
        "n_2q": n_2q,
        "n_m": n_m,
        "depth": compiled.depth(),
        "raw_op_counts": op_counts,
    }


def hqc(g: dict, shots: int) -> float:
    return 5 + shots * (g["n_1q"] + 10 * g["n_2q"] + 5 * g["n_m"]) / 5000


def report_one(label, bits, t, oracle_kind, iterative, shots=1024):
    built = build_qc(bits, t, oracle_kind, iterative)
    if built is None:
        print(f"  {label}: oracle/iter combo unsupported, skipping")
        return
    qc, plan, m = built
    qref = qiskit_basis_counts(qc)
    try:
        qq = quantinuum_compile_counts(qc)
    except Exception as e:
        print(f"  {label}: pytket compile ERROR {type(e).__name__}: {str(e)[:80]}")
        return
    hqc_ref = hqc(qref, shots)
    hqc_q = hqc(qq, shots)
    saving = (1 - hqc_q / hqc_ref) * 100 if hqc_ref else 0
    print(f"  {label:<22} qbits={plan.total_qubits:<3} "
          f"Qiskit n_2q={qref['n_2q']:>5} → tket n_2q={qq['n_2q']:>5}  "
          f"HQC {hqc_ref:>7,.0f} → {hqc_q:>7,.0f}  (save {saving:+.1f}%)")
    return qq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="Run all configurations (default: Phase 1 only)")
    ap.add_argument("--shots", type=int, default=1024)
    args = ap.parse_args()

    print(f"=== Quantinuum H2 native compile vs Qiskit-basis estimate ===")
    print(f"shots={args.shots}\n")
    print(f"{'Config':<22} {'qbits':>3} {'gate counts and HQC comparison'}")
    print("-" * 100)

    configs = [
        ("Phase 1 (m=3 dense)",   4,  6, "dense",  False),
    ]
    if args.all:
        configs.extend([
            ("m=5 dense",            6,  8, "dense",  False),
            ("m=5 ripple",           6,  8, "ripple", False),
            ("m=7 ripple",           7,  9, "ripple", False),
            ("m=8 ripple",           8, 10, "ripple", False),
            ("m=8 iterative",        8, 10, "ripple", True),
            ("m=10 iterative",      10, 12, "ripple", True),
        ])

    for cfg in configs:
        report_one(*cfg, shots=args.shots)


if __name__ == "__main__":
    main()
