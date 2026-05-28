"""Min-shot recovery curve for the lattice HNP + verify pipeline.

For each (hardware fidelity, shot count) cell, simulates the Phase 1
circuit under a depolarising-noise model, then attempts recovery via
the production hnp_recover_with_verification flow. Repeats N trials
per cell and reports the success rate.

The minimum shot count for ≥90% recovery is the "recommended N" for
that hardware. Multiplied by HQC-per-shot it gives the real budget.

Usage:
    python scripts/min_shot_curve.py
    python scripts/min_shot_curve.py --trials 20  # tighter statistics
"""
from __future__ import annotations

import argparse
import time

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import hnp_recover_with_verification
from shor_ecdlp import DenseUnitaryOracle, ShorECDLPSolver, SubgroupIndexer

from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error, ReadoutError
from qiskit import transpile


def make_noise(p2: float, p1_ratio: float = 0.1) -> NoiseModel | None:
    if p2 <= 0:
        return None
    nm = NoiseModel()
    nm.add_all_qubit_quantum_error(depolarizing_error(p2, 2), ["cx", "ecr", "cz"])
    nm.add_all_qubit_quantum_error(
        depolarizing_error(p2 * p1_ratio, 1),
        ["u3", "u", "sx", "rz", "h", "p"],
    )
    nm.add_all_qubit_readout_error(ReadoutError([[1 - p2, p2], [p2, 1 - p2]]))
    return nm


def setup_phase1_circuit():
    c = get_challenge(4)
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    n, d_true = c.n, c.expected_d
    m = (n - 1).bit_length()
    ind = SubgroupIndexer(curve, G, n)
    solver = ShorECDLPSolver(
        curve, G, Q, n, oracle=DenseUnitaryOracle(ind), num_counting=6
    )
    qc = solver.build_circuit()
    isa = transpile(qc, basis_gates=["u3", "cx", "measure"], optimization_level=3)
    return c, curve, G, Q, n, d_true, m, isa


def run_one_trial(isa, n, t, m, d_true, verify, sim, shots: int) -> dict:
    """Returns metrics distinguishing signal regime from verification filter:

    - via_verify_topK : usual production flow (top-K + EC verify)
    - via_argmax      : d_true is HNP argmax (strict signal-regime test)
    - via_top3_argmax : d_true (or anti-d) is in HNP top-3 (relaxed)
    """
    from lattice_postprocess import hnp_score
    counts = sim.run(isa, shots=shots, seed_simulator=None).result().get_counts()
    pt_w = m
    shot_list = []
    for bs, cnt in counts.items():
        bs2 = bs.replace(" ", "")
        if len(bs2) != 2 * t + pt_w:
            continue
        k = int(bs2[:t], 2) % n
        j = int(bs2[t:2 * t], 2) % n
        r = int(bs2[2 * t:], 2) % n
        for _ in range(cnt):
            shot_list.append((j, k, r))
    if not shot_list:
        return {"verify": False, "argmax": False, "top3_dclass": False}
    rec = hnp_recover_with_verification(shot_list, n, t, verify, top_k=7)
    scores = sorted(((d, hnp_score(d, shot_list, n, t)) for d in range(n)),
                    key=lambda x: x[1])
    argmax = scores[0][0]
    top3 = {d for d, _ in scores[:3]}
    d_class = {d_true, (n - d_true) % n}
    return {
        "verify": rec["d_recovered"] == d_true,
        "argmax": argmax == d_true,
        "top3_dclass": bool(top3 & d_class),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=10,
                    help="Trials per (p2, shots) cell")
    args = ap.parse_args()

    c, curve, G, Q, n, d_true, m, isa = setup_phase1_circuit()
    cx_count = sum(v for k, v in isa.count_ops().items() if k == "cx")
    print(f"Phase 1 circuit: {cx_count} cx after basic-basis transpile")
    print(f"Target: d={d_true} (anti-d={(n-d_true)%n})\n")

    verify = lambda d: curve.scalar_mul(d, G) == Q

    hardware_levels = [
        ("noiseless",      0.0),
        ("Helios advert",  3e-4),
        ("Helios spec H2", 8e-4),
        ("H2 emulator",    3e-3),
        ("IBM Heron r2",   5e-3),
    ]
    shot_counts = [16, 32, 64, 128, 256, 512, 1024]

    print(f"Three success metrics tracked (higher bar each row):")
    print(f"  V: production verify-top-K (verification-filter friendly)")
    print(f"  T: d-class in HNP top-3 (intermediate)")
    print(f"  A: d_true == HNP argmax (strict signal regime)\n")

    print(f"{'Hardware':<20} {'p2':>8} {'est-fid':>9}  "
          + "".join(f"N={s:>5} " for s in shot_counts))
    print("-" * 130)

    for label, p2 in hardware_levels:
        est_fid = (1 - p2) ** cx_count if p2 > 0 else 1.0
        nm = make_noise(p2)
        sim = AerSimulator(noise_model=nm) if nm else AerSimulator()

        # Three rows per hardware level (V, T, A)
        rows = {"V": [], "T": [], "A": []}
        for N in shot_counts:
            tally = {"V": 0, "T": 0, "A": 0}
            for trial in range(args.trials):
                r = run_one_trial(isa, n, 6, m, d_true, verify, sim, N)
                if r["verify"]:      tally["V"] += 1
                if r["top3_dclass"]: tally["T"] += 1
                if r["argmax"]:      tally["A"] += 1
            rows["V"].append(f"{tally['V']}/{args.trials}")
            rows["T"].append(f"{tally['T']}/{args.trials}")
            rows["A"].append(f"{tally['A']}/{args.trials}")
        print(f"  {label:<18} {p2:>8.0e} {est_fid:>9.3f}  V: "
              + "".join(f"{r:>8}" for r in rows["V"]))
        print(f"  {'':<18} {'':>8} {'':>9}  T: "
              + "".join(f"{r:>8}" for r in rows["T"]))
        print(f"  {'':<18} {'':>8} {'':>9}  A: "
              + "".join(f"{r:>8}" for r in rows["A"]))


if __name__ == "__main__":
    main()
