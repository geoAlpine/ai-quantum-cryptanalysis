"""
Noisy preview sweep: run the same Aer-with-IBM-noise circuit at multiple
shot counts and seeds, report d_true rank / gap / recovery-success
distribution.

The 2026-05-22 single noisy_preview run at m=3 t=6 dense ibm_kingston
2048 shots showed d_true rank 4 with a 0.6% score gap — slim margin
for hardware. This sweep nails down:

  - **How does rank improve with shots?** Cheap way to decide how many
    shots to budget on real QPU.
  - **How stable is recovery across trials?** Each trial uses a fresh
    Aer seed; if 9 out of 10 trials recover ``d_true`` via top-K verify
    we should ship; if 5 out of 10 we need to re-tune.
  - **Where does d_true land on average?** Tracks the typical HNP rank
    so we can size ``top_k`` correctly for the real submission.

Usage:
    python scripts/noisy_sweep.py --bits 4 --t 6 --oracle dense \\
        --backend ibm_kingston --shots-list 1024 2048 4096 \\
        --trials 3 --top-k 7
"""
from __future__ import annotations

import argparse
import statistics
import time

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import hnp_recover_with_verification, hnp_score
from quantum_ecc import load_token
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator
from qiskit_ibm_runtime import QiskitRuntimeService


def parse_shots(counts, t, pt_w, n):
    out = []
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k = int(bs[:t], 2) % n
        j = int(bs[t:2 * t], 2) % n
        r = int(bs[2 * t:], 2) % n
        for _ in range(cnt):
            out.append((j, k, r))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, required=True)
    ap.add_argument("--t", type=int, required=True)
    ap.add_argument("--oracle", choices=["dense", "ripple"], default="dense")
    ap.add_argument("--backend", default="ibm_kingston")
    ap.add_argument("--shots-list", type=int, nargs="+", default=[1024, 2048, 4096])
    ap.add_argument("--trials", type=int, default=3,
                    help="number of independent sim runs per shot count")
    ap.add_argument("--top-k", type=int, default=7)
    args = ap.parse_args()

    c = get_challenge(args.bits)
    n = c.n
    d_true = c.expected_d

    print(f"=== Noisy sweep ===")
    print(f"  bits={args.bits}  n={n}  d_true={d_true}  t={args.t}  oracle={args.oracle}")
    print(f"  backend (noise) = {args.backend}")
    print(f"  shots × trials = {args.shots_list} × {args.trials}")
    print(f"  top_k = {args.top_k}")
    print()

    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    ind = SubgroupIndexer(curve, G, n)
    oracle = (DenseUnitaryOracle(ind) if args.oracle == "dense"
              else RippleCarryOracle(ind))
    solver = ShorECDLPSolver(curve, G, Q, n, oracle=oracle, num_counting=args.t)
    pt_w = oracle.point_register_width()

    print(f"  fetching noise model from {args.backend} (no QPU spent)...")
    svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())
    backend = svc.backend(args.backend)
    sim = AerSimulator.from_backend(backend)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    qc = solver.build_circuit()
    qc_t = pm.run(qc)
    cx = sum(v for k_, v in qc_t.count_ops().items() if k_ in ("cx", "ecr", "cz"))
    print(f"  transpiled: depth={qc_t.depth()}  2Q={cx}  est-fid={0.995**cx:.2e}")
    print()

    def verify(d):
        return curve.scalar_mul(d, G) == Q

    # Header
    print(f"  {'shots':>6} {'trial':>5}  {'d_true_rank':>11}  {'gap':>7}  "
          f"{'recovered':>9}  {'via_anti':>8}  {'sim_s':>6}")
    print("  " + "-" * 76)

    summary: dict[int, dict] = {}
    for shots in args.shots_list:
        ranks: list[int] = []
        successes = 0
        anti_d_used = 0
        for trial in range(args.trials):
            t0 = time.time()
            counts = sim.run(qc_t, shots=shots, seed_simulator=trial).result().get_counts()
            shot_list = parse_shots(counts, args.t, pt_w, n)
            # Rank of d_true in HNP score
            sorted_d = sorted(
                ((d, hnp_score(d, shot_list, n, args.t)) for d in range(n)),
                key=lambda x: x[1],
            )
            d_true_rank = next(i for i, (d, _) in enumerate(sorted_d) if d == d_true) + 1
            best, second = sorted_d[0][1], sorted_d[1][1]
            gap = (second - best) / second if second > 0 else 0.0
            ranks.append(d_true_rank)
            # Recovery
            r = hnp_recover_with_verification(
                shot_list, n, args.t, verify, top_k=args.top_k,
            )
            success = r["d_recovered"] == d_true
            successes += int(success)
            if success and r["verified_via_anti_d"]:
                anti_d_used += 1
            elapsed = time.time() - t0
            print(f"  {shots:>6} {trial:>5}  {d_true_rank:>11}  {gap:>6.3f}  "
                  f"{'✓' if success else '✗':>9}  "
                  f"{'yes' if r.get('verified_via_anti_d') else 'no':>8}  "
                  f"{elapsed:>6.1f}")
        summary[shots] = {
            "ranks": ranks,
            "mean_rank": statistics.mean(ranks),
            "successes": successes,
            "anti_d_used": anti_d_used,
            "trials": args.trials,
        }

    print()
    print(f"=== Summary ===")
    print(f"  {'shots':>6}  {'mean_rank':>9}  {'recovery':>10}  {'anti_d_rate':>11}")
    for shots, s in summary.items():
        print(f"  {shots:>6}  {s['mean_rank']:>9.1f}  "
              f"{s['successes']}/{s['trials']:<3}  "
              f"{s['anti_d_used']}/{s['trials']:<3}")

    # Decision: which shot count gives 100% recovery?
    best = None
    for shots, s in summary.items():
        if s["successes"] == s["trials"]:
            best = shots
            break
    if best is not None:
        print()
        print(f"  ==> RECOMMENDED submit shots = {best} "
              f"({summary[best]['successes']}/{summary[best]['trials']} recovery, "
              f"{summary[best]['anti_d_used']}/{summary[best]['trials']} via anti-d)")
    else:
        print()
        print(f"  ==> No shot count achieved 100% recovery; consider re-tuning t/oracle")


if __name__ == "__main__":
    main()
