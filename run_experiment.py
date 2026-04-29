"""
Main experiment runner.

Usage:
  # Dummy QPE circuit (baseline, takes secret k as input)
  python run_experiment.py --bits 15 --shots 4096

  # Grover ECDLP (oracle uses only G, Q)
  python run_experiment.py --grover --grover-bits 3 --shots 4096

  # Shor ECDLP — Q-Day Prize challenge curves (oracle uses only G, Q)
  python run_experiment.py --shor --shor-bits 6 --shots 4096
  python run_experiment.py --shor --shor-bits 8 --shots 4096 --ibm

  # Run on real IBM Quantum hardware (requires IBM_QUANTUM_TOKEN in .env)
  python run_experiment.py --grover --grover-bits 3 --shots 4096 --ibm
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from ecc import make_small_curve, bsgs_dlog, _PRESETS, EllipticCurve
from quantum_ecc import dummy_shor_circuit, run_on_simulator, run_on_ibm, run_on_ionq, zero_noise_extrapolation
from grover_ecdlp import grover_ecdlp_circuit, make_grover_instance
from shor_ecdlp import ShorECDLPSolver
from challenges import get_challenge, CHALLENGES
from analysis import quantum_advantage_report, classical_brute_force_timing, print_report


def run_shor(args):
    """Q-Day Prize style Shor ECDLP run on a challenge curve."""
    from shor_ecdlp import DenseUnitaryOracle, RippleCarryOracle
    from qiskit import transpile
    from qiskit_aer import AerSimulator

    c = get_challenge(args.shor_bits)
    print(f"\n[+] Shor ECDLP — challenge {c.bit_length}-bit")
    print(f"    Curve: y^2 = x^3 + 7  (mod {c.p})")
    print(f"    n = {c.n}  G = {c.G}  Q = {c.Q}")
    print(f"    Expected d = {c.expected_d}  (used only for post-run verification)")

    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)

    oracle = None
    if args.shor_oracle == "dense":
        from shor_ecdlp import SubgroupIndexer
        oracle = DenseUnitaryOracle(SubgroupIndexer(curve, G, c.n))
    elif args.shor_oracle == "ripple":
        from shor_ecdlp import SubgroupIndexer
        oracle = RippleCarryOracle(SubgroupIndexer(curve, G, c.n))

    solver = ShorECDLPSolver(curve, G, Q, c.n,
                             oracle=oracle, num_counting=args.shor_counting)
    plan = solver.plan()
    print(f"    Oracle: {plan.oracle_name}  qubits={plan.total_qubits}  "
          f"counting={plan.num_counting}  point={plan.point_width}  ancilla={plan.ancilla_widths}")

    print(f"\n[+] Building circuit...")
    qc = solver.build_circuit()
    print(f"    depth(pre-transpile) = {qc.depth()}, ops = {qc.size()}")

    if args.ibm:
        print(f"\n[+] Submitting to IBM Quantum (shots={args.shots})...")
        counts = run_on_ibm(qc, shots=args.shots)
    elif args.ionq:
        print(f"\n[+] Submitting to IonQ via AWS Braket (shots={args.shots})...")
        counts = run_on_ionq(qc, shots=args.shots)
    else:
        print(f"\n[+] Running on Aer (matrix_product_state, shots={args.shots})...")
        sim = AerSimulator(method="matrix_product_state")
        isa = transpile(qc, sim, optimization_level=1)
        print(f"    depth(transpiled) = {isa.depth()}")
        counts = sim.run(isa, shots=args.shots).result().get_counts()

    print(f"\n[+] Extracting d...")
    d = solver.extract(counts)
    success = (d == c.expected_d)
    print(f"    unique outcomes = {len(counts)}")
    print(f"    recovered d = {d}  (expected {c.expected_d})  -> {'OK' if success else 'FAIL'}")

    os.makedirs("results", exist_ok=True)
    out = {
        "mode": "shor",
        "bit_length": c.bit_length,
        "p": c.p, "n": c.n,
        "G": list(c.G), "Q": list(c.Q),
        "expected_d": c.expected_d,
        "recovered_d": d,
        "success": success,
        "shots": args.shots,
        "unique_outcomes": len(counts),
        "qubits": plan.total_qubits,
        "oracle": plan.oracle_name,
        "num_counting": plan.num_counting,
        "circuit_depth": qc.depth(),
    }
    backend_tag = "ibm" if args.ibm else ("ionq" if args.ionq else "sim")
    path = f"results/shor_{c.bit_length}bit_{args.shots}shots_{backend_tag}.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[+] Saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="Quantum ECDLP Experiment")
    parser.add_argument("--bits", type=int, default=15, help="Key size in bits (dummy mode)")
    parser.add_argument("--shots", type=int, default=4096, help="Number of quantum shots")
    parser.add_argument("--noise", type=float, default=0.0, help="Depolarizing noise level")
    parser.add_argument("--zne", action="store_true", help="Apply Zero-Noise Extrapolation")
    parser.add_argument("--ibm", action="store_true", help="Run on real IBM Quantum hardware")
    parser.add_argument("--ionq", action="store_true", help="Run on IonQ Aria via AWS Braket (~$6/run)")
    parser.add_argument("--grover", action="store_true",
                        help="Use real Grover ECDLP (circuit does NOT receive secret k)")
    parser.add_argument("--grover-bits", type=int, default=3,
                        help="Key bits for Grover search (default: 3)")
    parser.add_argument("--tiny", action="store_true",
                        help="Use p=11 curve (12 qubits) optimized for real hardware")
    parser.add_argument("--shor", action="store_true",
                        help="Use Shor ECDLP on Q-Day Prize challenge curves")
    parser.add_argument("--shor-bits", type=int, default=4,
                        help=f"Challenge bit length. Available: {sorted(CHALLENGES.keys())}")
    parser.add_argument("--shor-oracle", choices=["dense", "ripple"], default=None,
                        help="Force oracle strategy (default: auto: dense ≤6-bit, ripple ≥7-bit)")
    parser.add_argument("--shor-counting", type=int, default=None,
                        help="Counting-register width t. Default: ceil(log2(n))")
    parser.add_argument("--classical-only", action="store_true", help="Classical baseline only")
    args = parser.parse_args()

    if args.shor:
        run_shor(args)
        return

    if args.grover:
        k_bits = args.grover_bits
        tiny = args.tiny
        label = "tiny(p=11)" if tiny else "p=67"
        print(f"\n[+] REAL Grover ECDLP  (k_bits={k_bits}, {label}, search space={2**k_bits})")
        curve, G, secret_k, Q = make_grover_instance(k_bits, tiny=tiny)
        print(f"    Curve: y^2 = x^3 + {curve.a}x + {curve.b}  (mod {curve.p})")
        print(f"    G = {G}")
        print(f"    Q = k*G = {Q}  [circuit does NOT receive k]")
        print(f"    Secret k = {secret_k}  (hidden from circuit, used only for verification)")
        print(f"\n[+] Building Grover circuit...")
        circuit = grover_ecdlp_circuit(G, Q, curve, k_bits)
        n_bits = k_bits
        print(f"    Qubits: {circuit.num_qubits}, depth: {circuit.depth()}, gates: {circuit.size()}")
        suffix = "_tiny" if tiny else ""
        result_prefix = f"results/grover_{k_bits}bit{suffix}_{args.shots}shots"
    else:
        print(f"\n[+] Building {args.bits}-bit elliptic curve (dummy mode)...")
        curve, G, secret_k, Q = make_small_curve(args.bits)
        print(f"    Curve: y^2 = x^3 + {curve.a}x + {curve.b}  (mod {curve.p})")
        print(f"    G = {G},  Q = {Q},  k = {secret_k}")

        target = min(_PRESETS.keys(), key=lambda b: abs(b - args.bits))
        order = _PRESETS[target][5]
        print(f"\n[+] Classical baseline (BSGS)...")
        recovered_k, elapsed = classical_brute_force_timing(bsgs_dlog, G, Q, curve, order)
        print(f"    k = {recovered_k}  ({elapsed:.4f}s)")
        assert recovered_k == secret_k

        if args.classical_only:
            return

        print(f"\n[+] Building dummy circuit ({args.bits} qubits)...")
        circuit = dummy_shor_circuit(args.bits, secret_k)
        n_bits = args.bits
        print(f"    depth: {circuit.depth()}, gates: {circuit.size()}")
        result_prefix = f"results/experiment_{args.bits}bit_{args.shots}shots"

    if args.ionq:
        print(f"\n[+] Submitting to IonQ Aria via AWS Braket (shots={args.shots})...")
        counts = run_on_ionq(circuit, shots=args.shots)
    elif args.ibm:
        print(f"\n[+] Submitting to IBM Quantum real hardware (shots={args.shots})...")
        counts = run_on_ibm(circuit, shots=args.shots)
    elif args.zne:
        print(f"\n[+] Running with ZNE...")
        counts = zero_noise_extrapolation(
            circuit, shots=args.shots, noise_levels=[0.001, 0.005, 0.01]
        )
    else:
        print(f"\n[+] Running on Aer simulator (shots={args.shots})...")
        counts = run_on_simulator(circuit, shots=args.shots, noise_level=args.noise)

    print(f"\n[+] Analyzing quantum advantage...")
    report = quantum_advantage_report(counts, secret_k, n_bits, args.shots)
    print_report(report)

    os.makedirs("results", exist_ok=True)
    result_path = f"{result_prefix}.json"
    with open(result_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n[+] Saved to {result_path}")


if __name__ == "__main__":
    main()
