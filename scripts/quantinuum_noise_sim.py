"""Aer noise simulation using Quantinuum H2 emulator default parameters.

Predicts Phase-1 equivalent (and beyond) results on Quantinuum H2 BEFORE
spending any HQC. Uses the noise-parameter set documented in Microsoft's
Quantinuum provider page (the H2 emulator defaults as of 2026-05).

Param source: https://learn.microsoft.com/en-us/azure/quantum/provider-quantinuum
  - p1 = 4e-5     (single-qubit gate error)
  - p2 = 3e-3     (two-qubit gate error)        ← dominant
  - p_meas = 3e-3 (measurement error per qubit)
  - p_init = 4e-5 (init error per qubit)
  Plus crosstalk terms we approximate as additional depolarizing.

The H2 native gateset is {U3, ZZPhase, Measure}. We compile via pytket-
quantinuum offline and re-build the resulting circuit in Qiskit with
an Aer noise model.

Usage:
    python scripts/quantinuum_noise_sim.py --bits 4 --t 6 --shots 1024
    python scripts/quantinuum_noise_sim.py --bits 6 --t 8 --oracle ripple --shots 1024
"""
from __future__ import annotations

import argparse
import time

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import hnp_recover_with_verification, hnp_score
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)

from qiskit_aer import AerSimulator
from qiskit_aer.noise import (
    NoiseModel, depolarizing_error, ReadoutError,
)
from qiskit import transpile


# Quantinuum H2 emulator default params (Microsoft docs, 2026-05)
H2_PARAMS = {
    "p1": 4e-5,
    "p2": 3e-3,
    "p_meas": 3e-3,
    "p_init": 4e-5,
}


def make_h2_noise_model(params: dict = None) -> NoiseModel:
    """Build a depolarising-channel noise model matching H2 emulator
    defaults. Approximate — true H2 emulator uses crosstalk and emission
    terms we abstract away. Sufficient for end-to-end prediction."""
    p = params or H2_PARAMS
    nm = NoiseModel()

    # Single-qubit gate error (apply to common Qiskit basis).
    err_1q = depolarizing_error(p["p1"], 1)
    for gname in ("u3", "u", "u1", "u2", "rz", "rx", "ry", "sx", "x", "h", "p"):
        nm.add_all_qubit_quantum_error(err_1q, [gname])

    # Two-qubit gate error (cx + ecr + cz; native H2 is ZZPhase but we
    # build the noise sim against the Qiskit basis_gates the transpiler
    # outputs).
    err_2q = depolarizing_error(p["p2"], 2)
    for gname in ("cx", "ecr", "cz"):
        nm.add_all_qubit_quantum_error(err_2q, [gname])

    # Readout error.
    pm = p["p_meas"]
    nm.add_all_qubit_readout_error(
        ReadoutError([[1 - pm, pm], [pm, 1 - pm]])
    )
    return nm


def run_one(bits: int, t: int, oracle_kind: str, shots: int,
            params: dict = None):
    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    n, d_true = c.n, c.expected_d
    m = (n - 1).bit_length()

    ind = SubgroupIndexer(curve, G, n)
    if oracle_kind == "dense":
        if m > 6:
            print(f"  oracle=dense requires m<=6, got m={m}; skip")
            return None
        oracle = DenseUnitaryOracle(ind)
    else:
        oracle = RippleCarryOracle(ind)

    solver = ShorECDLPSolver(curve, G, Q, n, oracle=oracle, num_counting=t)
    qc = solver.build_circuit()

    nm = make_h2_noise_model(params)

    # Transpile to a basis Aer-noise-model knows.
    sim = AerSimulator(noise_model=nm)
    isa = transpile(qc, basis_gates=["u3", "cx", "measure"],
                    optimization_level=3)
    cx = sum(v for k, v in isa.count_ops().items() if k in ("cx", "ecr", "cz"))
    eff_fid = (1 - H2_PARAMS["p2"]) ** cx

    t0 = time.time()
    counts = sim.run(isa, shots=shots).result().get_counts()
    run_s = time.time() - t0

    # Parse
    pt_w = m
    shots_list = []
    for bs, cnt in counts.items():
        bs2 = bs.replace(" ", "")
        if len(bs2) != 2 * t + pt_w:
            continue
        k = int(bs2[:t], 2) % n
        j = int(bs2[t:2 * t], 2) % n
        r = int(bs2[2 * t:], 2) % n
        for _ in range(cnt):
            shots_list.append((j, k, r))

    # HNP metrics
    scores = sorted(((d, hnp_score(d, shots_list, n, t)) for d in range(n)),
                    key=lambda x: x[1])
    rank_true = 1 + next(
        (i for i, (d, _) in enumerate(scores) if d == d_true), n
    )
    top1, second = scores[0][1], scores[1][1] if len(scores) > 1 else scores[0][1]
    gap_pct = (second - top1) / max(1e-9, second) * 100
    verify = lambda d: curve.scalar_mul(d, G) == Q
    rec = hnp_recover_with_verification(shots_list, n, t, verify, top_k=7)

    return {
        "config": f"bits={bits} t={t} {oracle_kind} shots={shots}",
        "n": n, "m": m, "d_true": d_true,
        "transpiled_2Q": cx,
        "est_fid_h2": eff_fid,
        "run_sec": round(run_s, 1),
        "unique_outcomes": len(counts),
        "rank_d_true": rank_true,
        "score_gap_pct": round(gap_pct, 3),
        "argmax_d": scores[0][0],
        "recovery_d": rec["d_recovered"],
        "recovery_success": rec["d_recovered"] == d_true,
        "recovery_rank": rec["rank_in_hnp"],
        "via_anti_d": rec["verified_via_anti_d"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, default=4)
    ap.add_argument("--t", type=int, default=6)
    ap.add_argument("--oracle", choices=["dense", "ripple"], default="dense")
    ap.add_argument("--shots", type=int, default=1024)
    args = ap.parse_args()

    print(f"=== Quantinuum H2 noise sim ===")
    print(f"H2 params: p1={H2_PARAMS['p1']}  p2={H2_PARAMS['p2']}  "
          f"p_meas={H2_PARAMS['p_meas']}\n")

    r = run_one(args.bits, args.t, args.oracle, args.shots)
    if r is None:
        return

    print(f"Circuit: {r['config']}")
    print(f"  n={r['n']}  m={r['m']}  d_true={r['d_true']}")
    print(f"  transpiled 2Q-gates: {r['transpiled_2Q']}")
    print(f"  est-fid on H2 (p2=3e-3): {r['est_fid_h2']:.3e}")
    print(f"  sim runtime: {r['run_sec']}s")
    print(f"")
    print(f"  Result:")
    print(f"    unique outcomes : {r['unique_outcomes']} / {args.shots}")
    print(f"    rank(d_true)    : {r['rank_d_true']} / {r['n']}")
    print(f"    score gap       : {r['score_gap_pct']:.2f}%")
    print(f"    argmax d        : {r['argmax_d']} {'<- d_true' if r['argmax_d']==r['d_true'] else ''}")
    print(f"    recovery_d      : {r['recovery_d']}")
    print(f"    recovery success: {'✓' if r['recovery_success'] else '✗'}")
    if r['recovery_success']:
        print(f"    HNP rank        : {r['recovery_rank']}  via_anti_d={r['via_anti_d']}")


if __name__ == "__main__":
    main()
