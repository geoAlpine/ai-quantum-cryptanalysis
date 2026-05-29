"""Submit a Shor-ECDLP circuit to Quantinuum via Azure Quantum.

Mirrors ``scripts/submit_18bit.py`` for IBM. Targets one of:

  - ``quantinuum.sim.h2-1sc`` : H2-1 Syntax Checker — FREE, validates
    that the circuit compiles on the H2-1 stack. No HQC cost. Run this
    FIRST before any paid submission.
  - ``quantinuum.sim.h2-1e``  : H2-1 Emulator — realistic noise model
    of H2-1 hardware. Charged in eHQC ($1.25 per eHQC at Standard plan
    rate). Recommended for noisy-prediction validation.
  - ``quantinuum.qpu.h2-1``   : H2-1 hardware. Charged in HQC ($12.50
    per HQC at Standard plan rate). The actual world record run.

Usage:
    # 1. FREE — verify circuit compiles on H2-1
    python scripts/azure_quantum_submit.py --bits 4 --t 6 --oracle dense \\
        --extractor hnp --target h2-1sc --shots 16

    # 2. Paid emulator (eHQC, very cheap)
    python scripts/azure_quantum_submit.py --bits 4 --t 6 --oracle dense \\
        --extractor hnp --target h2-1e --shots 16

    # 3. Real hardware (HQC, careful with budget)
    python scripts/azure_quantum_submit.py --bits 4 --t 6 --oracle dense \\
        --extractor hnp --target h2-1 --shots 16

Auth: run ``az login`` once in this shell before invocation.
"""
from __future__ import annotations

import argparse
import json
import os

from challenges import get_challenge
from ecc import EllipticCurve
from quantum_ecc import load_azure_credentials
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)
from qiskit import transpile

from azure.quantum import Workspace
from azure.quantum.qiskit import AzureQuantumProvider


TARGETS = {
    "h2-1sc": ("quantinuum.sim.h2-1sc", "syntax checker — FREE", 0.0),
    "h2-1e":  ("quantinuum.sim.h2-1e",  "H2-1 emulator (noise model)", 1.25),
    "h2-1":   ("quantinuum.qpu.h2-1",   "H2-1 hardware", 12.50),
    "h2-2sc": ("quantinuum.sim.h2-2sc", "H2-2 syntax checker — FREE", 0.0),
    "h2-2e":  ("quantinuum.sim.h2-2e",  "H2-2 emulator", 1.25),
    "h2-2":   ("quantinuum.qpu.h2-2",   "H2-2 hardware", 12.50),
}


def estimate_hqc(n_1q: int, n_2q: int, n_m: int, shots: int) -> float:
    return 5 + shots * (n_1q + 10 * n_2q + 5 * n_m) / 5000


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bits", type=int, default=4)
    p.add_argument("--t", type=int, default=6)
    p.add_argument("--oracle", choices=["dense", "ripple", "auto"], default="auto")
    p.add_argument("--extractor", choices=["v3", "hnp"], default="hnp")
    p.add_argument("--shots", type=int, default=16,
                   help="Default 16 — the min-shot study found this is "
                        "sufficient for d-class HNP top-3 on Helios-class fidelity")
    p.add_argument("--target", choices=list(TARGETS.keys()), default="h2-1sc",
                   help="Default h2-1sc (FREE syntax checker). Move up to "
                        "h2-1e (emulator) then h2-1 (hardware) only after "
                        "the syntax checker succeeds.")
    p.add_argument("--dry-run", action="store_true",
                   help="Build, transpile, and quote estimated HQC. "
                        "Do NOT submit, even to the free syntax checker.")
    args = p.parse_args()

    target_id, target_desc, rate_per_hqc = TARGETS[args.target]
    unit = "free" if rate_per_hqc == 0 else (
        "eHQC" if "sim" in target_id else "HQC"
    )

    # ------------------------------------------------------------------ build
    c = get_challenge(args.bits)
    print(f"=== Quantinuum {args.target} submission ===")
    print(f"target: {target_id} — {target_desc}")
    print(f"curve : y² = x³ + 7 (mod {c.p})")
    print(f"n = {c.n}  m = {(c.n-1).bit_length()}  expected_d = {c.expected_d}")

    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    m = max(1, (c.n - 1).bit_length())
    ind = SubgroupIndexer(curve, G, c.n)
    oracle_kind = args.oracle
    if oracle_kind == "auto":
        # Quantinuum prefers ripple at all m (T-count analysis 2026-05-28).
        oracle_kind = "ripple" if m >= 4 else "dense"
    elif oracle_kind == "dense" and m > 6:
        print(f"  ERROR: dense requires m<=6, got m={m}")
        return 1
    oracle = (DenseUnitaryOracle(ind) if oracle_kind == "dense"
              else RippleCarryOracle(ind))
    solver = ShorECDLPSolver(curve, G, Q, c.n, oracle=oracle,
                              num_counting=args.t)
    qc = solver.build_circuit()
    plan = solver.plan()
    print(f"oracle: {oracle_kind}  qubits: {plan.total_qubits}  t: {args.t}")

    # ------------------------------------------------------------------ cost
    # Use Qiskit basis_gates=["u3","cx"] as a proxy for pre-Quantinuum-compile
    # gate counts. The real native compile will trim ~12-30% per the
    # 2026-05-28 pytket-quantinuum offline measurement.
    isa = transpile(qc, basis_gates=["u3", "cx", "measure"],
                    optimization_level=3)
    ops = isa.count_ops()
    n_1q = sum(v for k, v in ops.items()
               if k in ("u3", "u", "rz", "sx", "x", "h", "p"))
    n_2q = sum(v for k, v in ops.items() if k in ("cx", "ecr", "cz"))
    n_m = sum(v for k, v in ops.items() if k in ("measure", "reset"))
    hqc = estimate_hqc(n_1q, n_2q, n_m, args.shots)
    hqc_native = hqc * 0.85  # ~15% trim from native compile (conservative)
    cost_high = hqc * rate_per_hqc
    cost_native = hqc_native * rate_per_hqc
    print(f"\nGate count (Qiskit-basis proxy):")
    print(f"  N_1q = {n_1q:>7}  N_2q = {n_2q:>5}  N_m = {n_m:>3}  shots = {args.shots}")
    print(f"  Estimated  {unit} (upper bound)  = {hqc:>9,.1f}  → cost ≈ ${cost_high:,.2f}")
    print(f"  Estimated  {unit} (native-compile)≈ {hqc_native:>9,.1f}  → cost ≈ ${cost_native:,.2f}")
    if rate_per_hqc == 0:
        print(f"  (syntax checker — no charge)")

    if args.dry_run:
        print("\n[DRY RUN] Skipping submission.")
        return 0

    # ------------------------------------------------------------------ submit
    print("\nConnecting to Azure Quantum Workspace...")
    creds = load_azure_credentials()
    workspace = Workspace(**creds)
    provider = AzureQuantumProvider(workspace=workspace)
    print(f"  workspace: {creds['resource_id'].split('/')[-1]}")
    print(f"  location : {creds['location']}")

    backend = provider.get_backend(target_id)
    print(f"\nSubmitting to {target_id}...")
    job = backend.run(qc, shots=args.shots)
    job_id = job.id() if hasattr(job, "id") else str(job)
    print(f"  Job ID: {job_id}")

    os.makedirs("results", exist_ok=True)
    # Use the FIRST 8 chars of the job_id — Azure Quantum job IDs end
    # with a workspace/region tag that is shared across all jobs from
    # the same workspace, so a last-N suffix collides. The first 8 are
    # the per-job UUID head and are guaranteed unique.
    jid_suffix = job_id[:8].replace("/", "_")
    pending_path = (
        f"results/_pending_azure_{args.bits}bit_t{args.t}_{oracle_kind}_"
        f"{args.extractor}_{args.target}_{jid_suffix}.json"
    )
    with open(pending_path, "w") as f:
        json.dump({
            "platform": "azure_quantum",
            "target": target_id,
            "job_id": job_id,
            "bits": args.bits, "t": args.t, "shots": args.shots,
            "expected_d": c.expected_d, "qubits": plan.total_qubits,
            "oracle": oracle_kind,
            "extractor": args.extractor,
            "estimated_hqc_upper": hqc,
            "estimated_cost_upper_usd": cost_high,
            "rate_per_unit_usd": rate_per_hqc,
            "unit": unit,
        }, f, indent=2)
    print(f"\nSaved metadata → {pending_path}")
    print(f"To poll & extract:")
    print(f"  python scripts/azure_quantum_fetch.py {pending_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
