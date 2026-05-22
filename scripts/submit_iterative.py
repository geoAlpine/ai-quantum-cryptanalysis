"""
Submit iterative (semiclassical) Shor-ECDLP attempt to IBM Quantum.

Differences from ``scripts/submit_18bit.py``:

  - Uses :class:`shor_iterative.IterativeShorECDLPSolver` with 1 recycled
    qubit per counting register, dynamic phase corrections in place of
    the bulk inverse QFT. m=3 lands at ~13 logical qubits, vs ~23 for
    the standard layout.

  - Targets a backend with **dynamic circuits** enabled. IBM Heron r2
    backends (``ibm_fez``, ``ibm_kingston``, ``ibm_marrakesh``) all
    support mid-circuit measurement + classical feed-forward in 2026.

  - Saves an ``extractor: "iterative_hnp"`` marker into the pending
    metadata so ``fetch_result.py`` knows to run the
    HNP-score-search-with-verification post-processor rather than the
    legacy v3 cf_lift extractor.

This is the **Phase 1** submission of the "true world record" track —
the first hardware attempt that aims for collective signal recovery
without verification-filter shortcut. See
``docs/honest_framing_preprint_outline.md`` Section 5 for the framing.

Usage:
    # m=3 (n=7), t=6, max_corrections=2 — ~13 qubits, the noiseless
    # validation sweet spot.
    python scripts/submit_iterative.py --bits 4 --t 6 --shots 8192 --max-corr 2

    # Dry-run (build + transpile only, no QPU consumed).
    python scripts/submit_iterative.py --bits 4 --t 6 --dry-run
"""
from __future__ import annotations

import argparse
import json
import math
import os

from challenges import get_challenge
from ecc import EllipticCurve
from quantum_ecc import load_token
from shor_iterative import IterativeShorECDLPSolver
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2


def select_best_backend(svc, candidate_names: list[str], min_qubits: int):
    """Pick the backend with lowest median 2Q error, dynamic-circuits
    capable. Mirrors submit_18bit's selector with a dynamic-circuit
    capability check."""
    best, best_score = None, -1.0
    for name in candidate_names:
        try:
            b = svc.backend(name)
            if b.num_qubits < min_qubits:
                continue
            # Dynamic circuits check — Heron r2/r3 all support it, but
            # let's be defensive in case of future fleet changes.
            conf = b.configuration() if hasattr(b, "configuration") else None
            supports_dynamic = True
            if conf is not None:
                supports_dynamic = bool(getattr(conf, "dynamic_reprate_enabled", True))
            if not supports_dynamic:
                print(f"  {name}: skipped (no dynamic-circuit support)")
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
                err_2q = sorted(errs)[len(errs) // 2] if errs else 0.005
            score = -math.log(err_2q + 1e-12) - 0.1 * pending
            print(f"  {name}: pending={pending}  median_2Q_err={err_2q:.4f}  "
                  f"dynamic={supports_dynamic}  score={score:.2f}")
            if score > best_score:
                best_score = score
                best = b
        except Exception as e:
            print(f"  {name}: skipped ({type(e).__name__}: {str(e)[:60]})")
    return best


def configure_sampler_options(sampler, enable_dd: bool = True) -> dict:
    """Same DD + twirling config as the bulk solver — these are
    Sampler-level options independent of how the inverse QFT is built."""
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
    p.add_argument("--bits", type=int, default=4,
                   help="Challenge bit length (default 4 → n=7, the m=3 case)")
    p.add_argument("--t", type=int, default=6,
                   help="Effective counting bits per recycled register")
    p.add_argument("--max-corr", type=int, default=2,
                   help="Approximate-QFT truncation (Lelli's default 1, ours 2)")
    p.add_argument("--shots", type=int, default=8192)
    p.add_argument("--backend", default="auto",
                   help="Backend name or 'auto' for best-fidelity selection")
    p.add_argument("--no-dd", action="store_true",
                   help="Disable Sampler-level dynamical decoupling")
    p.add_argument("--dry-run", action="store_true",
                   help="Build & transpile only — no QPU consumed")
    args = p.parse_args()

    c = get_challenge(args.bits)
    print(f"=== Iterative Shor ECDLP {args.bits}-bit attempt ===")
    print(f"  curve: y² = x³ + 7 (mod {c.p})")
    print(f"  n = {c.n}  G = {c.G}  Q = {c.Q}  expected_d = {c.expected_d}")
    print(f"  4^t / n = {(1 << (2 * args.t)) / c.n:.2f}")

    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    solver = IterativeShorECDLPSolver(
        curve, G, Q, c.n,
        num_counting=args.t,
        max_corrections=args.max_corr,
    )
    plan = solver.plan()
    print(f"\n  iterative qubits: {plan.total_qubits} "
          f"(standard would be {plan.standard_total_qubits}, savings {plan.qubit_savings})")
    print(f"  t = {plan.t}, max_corrections = {args.max_corr}")

    print(f"\n  building circuit...")
    qc = solver.build_circuit()
    print(f"    pre-transpile: depth={qc.depth()}  ops={qc.size()}")

    svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())
    if args.backend == "auto":
        print(f"\n  selecting best dynamic-capable backend...")
        backend = select_best_backend(
            svc, ["ibm_fez", "ibm_kingston", "ibm_marrakesh"],
            min_qubits=plan.total_qubits,
        )
        if backend is None:
            print("  No suitable backend found.")
            return 1
        print(f"  picked: {backend.name}")
    else:
        backend = svc.backend(args.backend)
        print(f"  backend: {backend.name}  pending_jobs={backend.status().pending_jobs}")

    print(f"\n  transpiling at opt-level=3...")
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    isa = pm.run(qc)
    cx = sum(v for k, v in isa.count_ops().items() if k in ("cx", "ecr", "cz"))
    fid = 0.995 ** cx
    print(f"    transpiled: depth={isa.depth()}  2Q-gates={cx}  est-fid={fid:.2e}")

    if args.dry_run:
        print("\n[DRY RUN] skipping submission.")
        return 0

    print(f"\n  submitting {args.shots} shots...")
    sampler = SamplerV2(mode=backend)
    if not args.no_dd:
        opts = configure_sampler_options(sampler, enable_dd=True)
        print(f"    sampler options: {opts}")
    job = sampler.run([isa], shots=args.shots)
    print(f"    job id: {job.job_id()}  status={job.status()}")

    os.makedirs("results", exist_ok=True)
    pending_path = (
        f"results/_pending_iterative_{args.bits}bit_t{args.t}_"
        f"mc{args.max_corr}_ibm.json"
    )
    with open(pending_path, "w") as f:
        json.dump(
            {
                "job_id": job.job_id(),
                "backend": backend.name,
                "bits": args.bits,
                "t": args.t,
                "max_corrections": args.max_corr,
                "shots": args.shots,
                "expected_d": c.expected_d,
                "qubits": plan.total_qubits,
                "transpiled_depth": isa.depth(),
                "transpiled_2Q": cx,
                "extractor": "iterative_hnp",
                "solver": "shor_iterative.IterativeShorECDLPSolver",
            },
            f,
            indent=2,
        )
    print(f"\n  saved metadata to {pending_path}")
    print(f"  to poll & decode:")
    print(f"    python scripts/fetch_result.py {pending_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
