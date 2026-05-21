"""
Submit 25-bit Shor ECDLP attempt to IBM Quantum.

Resource-aware design:
  - Lazy SubgroupIndexer (BSGS lookups, n=16.7M is too large to enumerate).
  - Adaptive counting t=12 (4^t/n ≈ 1.0, but margin is moot in NISQ regime —
    deeper t increases decoherence without helping recovery; see AGENT.md).
  - v3 CF-lift extractor (calibrated on 22-bit / 19-bit IBM data) lets us
    use far fewer shots than v2 to reach the same recovery probability.

Default plan: t=12, 20K shots, v3 cf_window=16, backend=ibm_fez.
This matches 22-bit's shots×C/n ratio (~9.85 expected hits at 25-bit, vs
9.24 for 22-bit) for direct statistical comparability with the prior
submission, while keeping per-shot d-space coverage at 0.049% (close to
22-bit's 0.026%).

Usage:
    python scripts/submit_25bit.py --dry-run
    python scripts/submit_25bit.py
"""

import argparse
import json
import os
import sys

from cf_lift import estimate_c_per_shot
from challenges import get_challenge
from ecc import EllipticCurve
from quantum_ecc import load_token
from shor_ecdlp import (
    ShorECDLPSolver,
    RippleCarryOracle,
    SubgroupIndexer,
)
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager


def select_best_backend(svc, candidate_names, min_qubits):
    """Pick the backend with lowest median 2Q error (proxy for fidelity)."""
    import math
    best, best_score = None, -1.0
    for name in candidate_names:
        try:
            b = svc.backend(name)
            if b.num_qubits < min_qubits:
                continue
            pending = b.status().pending_jobs
            props = b.properties() if hasattr(b, "properties") else None
            if props is None:
                err_2q = 0.005
            else:
                errs = []
                for g in props.gates:
                    if g.gate in ("ecr", "cz"):
                        for p in g.parameters:
                            if p.name == "gate_error":
                                errs.append(p.value)
                err_2q = sorted(errs)[len(errs)//2] if errs else 0.005
            score = -math.log(err_2q + 1e-12) - 0.1 * pending
            print(f"  {name}: pending={pending}  median_2Q_err={err_2q:.4f}  score={score:.2f}")
            if score > best_score:
                best_score = score; best = b
        except Exception as e:
            print(f"  {name}: skipped ({type(e).__name__}: {str(e)[:50]})")
    return best


def configure_sampler_options(sampler, enable_dd=True):
    enabled = {}
    try:
        if enable_dd:
            sampler.options.dynamical_decoupling.enable = True
            sampler.options.dynamical_decoupling.sequence_type = "XY4"
            enabled["dynamical_decoupling"] = "XY4"
    except Exception as e:
        enabled["dd_error"] = f"{type(e).__name__}: {str(e)[:60]}"
    try:
        sampler.options.twirling.enable_gates = True
        sampler.options.twirling.enable_measure = True
        enabled["twirling"] = "gates+measure"
    except Exception as e:
        enabled["twirl_error"] = f"{type(e).__name__}: {str(e)[:60]}"
    return enabled


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bits", type=int, default=25)
    p.add_argument("--t", type=int, default=12,
                   help="Counting register width (default 12: minimum-depth)")
    p.add_argument("--shots", type=int, default=20000)
    p.add_argument("--backend", default="ibm_fez",
                   help="Backend name (default ibm_fez for prior-run continuity, or 'auto')")
    p.add_argument("--cf-window", type=int, default=16,
                   help="v3 CF-lift window — controls candidate density "
                        "(16 ≈ 22-bit per-shot coverage)")
    p.add_argument("--no-dd", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    c = get_challenge(args.bits)
    print(f"=== Shor ECDLP {args.bits}-bit attempt ===")
    print(f"Curve: y² = x³ + 7 (mod {c.p})")
    print(f"n = {c.n}  G = {c.G}  Q = {c.Q}  expected_d = {c.expected_d}")
    print(f"4^t/n = {4**args.t / c.n:.3f}")

    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    ind = SubgroupIndexer(curve, G, c.n, lazy=True)
    oracle = RippleCarryOracle(ind)
    solver = ShorECDLPSolver(curve, G, Q, c.n, oracle=oracle,
                              num_counting=args.t, lazy=True)
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
            svc, ["ibm_fez", "ibm_kingston", "ibm_marrakesh"],
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

    # Project expected hits — C/shot from the calibrated table in src/cf_lift
    cw = args.cf_window
    C_per_shot = estimate_c_per_shot(cw)
    expected = C_per_shot * args.shots / c.n
    import math
    p_at_least_one = 1 - math.exp(-expected)
    coverage = C_per_shot / c.n
    print(f"\n  v3 extractor projection (cf_window={cw}, C≈{C_per_shot}/shot):")
    print(f"    expected hits: {expected:.2f}, P(>=1 hit) = {p_at_least_one:.4%}")
    print(f"    per-shot d-space coverage: {coverage:.3%}")

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
            "job_id": job.job_id(),
            "backend": backend.name,
            "bits": args.bits,
            "t": args.t,
            "shots": args.shots,
            "expected_d": c.expected_d,
            "qubits": plan.total_qubits,
            "transpiled_depth": isa.depth(),
            "transpiled_2Q": cx,
            "cf_window": args.cf_window,
            "extractor": f"v3 cf_window={args.cf_window}",
        }, f, indent=2)
    print(f"\nSaved metadata to {pending_path}")
    print(f"To poll & extract once done:")
    print(f"  python scripts/fetch_result.py {pending_path}")


if __name__ == "__main__":
    main()
