"""
Submit 18-bit Shor ECDLP attempt to IBM Quantum.

Uses adaptive counting (t < m) to drastically reduce circuit depth and gate count
compared to the standard t=m approach (Lelli's baseline).

Usage:
    python scripts/submit_18bit.py --t 8 --shots 20000 --backend ibm_fez
    python scripts/submit_18bit.py --t 6 --shots 20000  # cheaper, less precision
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from challenges import get_challenge
from ecc import EllipticCurve
from quantum_ecc import load_token
from shor_ecdlp import ShorECDLPSolver, RippleCarryOracle, SubgroupIndexer
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager


def select_best_backend(svc, candidate_names: list[str], min_qubits: int) -> any:
    """Pick the backend with lowest median 2Q error (proxy for fidelity)."""
    best = None
    best_score = -1.0
    for name in candidate_names:
        try:
            b = svc.backend(name)
            if b.num_qubits < min_qubits:
                continue
            pending = b.status().pending_jobs
            # Get median 2Q error from backend properties
            props = b.properties() if hasattr(b, "properties") else None
            if props is None:
                err_2q = 0.005  # default assume IBM Heron r2 typical
            else:
                # ECR / CZ gate errors
                errs = []
                for g in props.gates:
                    if g.gate in ("ecr", "cz"):
                        for p in g.parameters:
                            if p.name == "gate_error":
                                errs.append(p.value)
                err_2q = sorted(errs)[len(errs)//2] if errs else 0.005
            # Composite score: prefer lower error, lower queue
            # Score = -log(error) - 0.1 * pending  (queue penalty mild)
            import math
            score = -math.log(err_2q + 1e-12) - 0.1 * pending
            print(f"  {name}: pending={pending}  median_2Q_err={err_2q:.4f}  score={score:.2f}")
            if score > best_score:
                best_score = score
                best = b
        except Exception as e:
            print(f"  {name}: skipped ({type(e).__name__}: {str(e)[:50]})")
    return best


def configure_sampler_options(sampler, enable_dd: bool = True) -> dict:
    """Configure SamplerV2 with error-mitigation options.

    Uses Sampler-level dynamical decoupling (cleaner than transpiler pass —
    handled by IBM Runtime which knows the backend's pulse alignment etc.).
    Returns a dict describing what was enabled, for logging.
    """
    enabled = {}
    try:
        if enable_dd:
            sampler.options.dynamical_decoupling.enable = True
            sampler.options.dynamical_decoupling.sequence_type = "XY4"
            enabled["dynamical_decoupling"] = "XY4"
    except Exception as e:
        enabled["dd_error"] = f"{type(e).__name__}: {str(e)[:60]}"
    try:
        # Pauli twirling for randomizing coherent errors
        sampler.options.twirling.enable_gates = True
        sampler.options.twirling.enable_measure = True
        enabled["twirling"] = "gates+measure"
    except Exception as e:
        enabled["twirl_error"] = f"{type(e).__name__}: {str(e)[:60]}"
    return enabled


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bits", type=int, default=18, help="Challenge bit length")
    p.add_argument("--t", type=int, default=8, help="Counting register width (adaptive)")
    p.add_argument("--shots", type=int, default=20000)
    p.add_argument("--backend", default="auto",
                   help="Backend name or 'auto' for best-fidelity selection")
    p.add_argument("--no-dd", action="store_true", help="Disable dynamical decoupling")
    p.add_argument("--dry-run", action="store_true",
                   help="Build & transpile only — do NOT submit (no QPU time used)")
    args = p.parse_args()

    c = get_challenge(args.bits)
    print(f"=== Shor ECDLP {args.bits}-bit attempt ===")
    print(f"Curve: y² = x³ + 7 (mod {c.p})")
    print(f"n = {c.n}  G = {c.G}  Q = {c.Q}  expected_d = {c.expected_d}")

    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    ind = SubgroupIndexer(curve, G, c.n)
    oracle = RippleCarryOracle(ind)
    solver = ShorECDLPSolver(curve, G, Q, c.n, oracle=oracle, num_counting=args.t)
    plan = solver.plan()
    print(f"\nPlan: oracle={plan.oracle_name}  qubits={plan.total_qubits}  "
          f"counting=t={plan.num_counting} (m={(c.n-1).bit_length()})")

    print(f"\nBuilding circuit...")
    qc = solver.build_circuit()
    print(f"  pre-transpile: depth={qc.depth()}  ops={qc.size()}")

    svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())

    if args.backend == "auto":
        print(f"\nSelecting best backend among Heron r2 candidates...")
        backend = select_best_backend(
            svc,
            ["ibm_fez", "ibm_kingston", "ibm_marrakesh"],
            min_qubits=plan.total_qubits,
        )
        if backend is None:
            print("  No suitable backend found.")
            return
        print(f"  Picked: {backend.name}")
    else:
        backend = svc.backend(args.backend)
        print(f"  backend: {backend.name}  pending_jobs={backend.status().pending_jobs}")

    print(f"\nTranspiling at opt-level=3...")
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    isa = pm.run(qc)
    cx = sum(v for k, v in isa.count_ops().items() if k in ("cx", "ecr", "cz"))
    fid = 0.995 ** cx
    print(f"  transpiled: depth={isa.depth()}  2Q-gates={cx}  est-fid={fid:.2e}")

    if args.dry_run:
        print("\n[DRY RUN] Skipping submission. Re-run without --dry-run to submit.")
        return

    print(f"\nSubmitting {args.shots} shots...")
    sampler = SamplerV2(mode=backend)
    if not args.no_dd:
        opts = configure_sampler_options(sampler, enable_dd=True)
        print(f"  Error mitigation enabled: {opts}")
    job = sampler.run([isa], shots=args.shots)
    print(f"  Job ID: {job.job_id()}  status={job.status()}")

    os.makedirs("results", exist_ok=True)
    pending_path = f"results/_pending_{args.bits}bit_t{args.t}_ibm.json"
    with open(pending_path, "w") as f:
        json.dump({
            "job_id": job.job_id(), "backend": args.backend, "bits": args.bits,
            "t": args.t, "shots": args.shots,
            "expected_d": c.expected_d, "qubits": plan.total_qubits,
            "transpiled_depth": isa.depth(), "transpiled_2Q": cx,
        }, f, indent=2)
    print(f"\nSaved metadata to {pending_path}")
    print(f"To poll & extract once done:")
    print(f"  python scripts/fetch_result.py {pending_path}")


if __name__ == "__main__":
    main()
