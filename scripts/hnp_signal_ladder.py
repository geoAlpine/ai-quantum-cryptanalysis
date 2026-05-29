"""HNP Signal Ladder — the noise threshold where genuine d-class signal dies.

The project's strategic moat (see memory three-year-genuine-record-strategy):
draw the signal-vs-noise boundary for collective HNP recovery, so that a real
hardware datapoint can be *placed* on a first-principles curve rather than
asserted in isolation. Now parameterised over m so the ladder can be drawn at
each rung of the roadmap (m=3 done on hardware; m=5+ explored here in sim).

Fully OFFLINE and FREE — no QPU/emulator quota. Takes the dense Phase-X circuit
for the chosen m, injects a 2q depolarizing error at a grid of rates, simulates
SHOTS shots (a few seeds averaged), and runs the SAME permutation test as
hnp_score_matrix.py (statistic = best-dc z; null = shuffle k vs j). Output: the
noise level at which p crosses 0.05 — where genuine collective signal dies.

STATISTIC: uses the squared-residual score (_scores_np), the robust cross-m
default. (The likelihood score is more powerful at m=3 but FAILS at m=5 — see
_nll_scores_np docstring — so it is deliberately not used for the ladder.)

CAVEATs:
  * A single depolarizing channel on cx is BENIGN vs real device noise — the
    signal survives to much lower *nominal* per-gate error than a real device
    would tolerate. Read the boundary by END-TO-END circuit fidelity, not the
    nominal 2q rate; place a platform by its EFFECTIVE fidelity (after SWAP
    overhead + coherent/readout/crosstalk noise). The m=3 rung calibrated this:
    real IBM (eff fid ≈2e-3) sits past the cliff (measured p≈0.61) while
    Quantinuum H2-1E (all-to-all, high eff fid) sits before it (measured
    p≈0.019). The ladder shows the boundary SHAPE; real-data permutation tests
    in hnp_score_matrix.py remain the authoritative per-platform verdicts.
  * t must be the sweet spot t≈m+3 (M/n≈8): too small starves the signal,
    too large hits the controlled-add wrap-around. m=3→t=6, m=5→t=8.

Usage:
    PYTHONPATH=src python scripts/hnp_signal_ladder.py                  # m=3
    PYTHONPATH=src python scripts/hnp_signal_ladder.py 1200 6 8 768     # m=5
    # args: n_perm  bits  t  shots
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/
from hnp_score_matrix import (  # noqa: E402
    _scores_np, _best_dc_z_from_scores, parse_shots,
)

SIM_SEEDS = [1, 7, 42, 123]   # average over independent noisy runs
PERM_SEED = 20260529
ALPHA = 0.05
ERR_GRID = [0.0, 0.0003, 0.0006, 0.001, 0.0015, 0.002, 0.003, 0.005, 0.01]


def build_circuit_basis(bits, t):
    """Transpile the dense circuit to [u3, cx] ONCE (expensive for larger m;
    reused across every noise level)."""
    from challenges import get_challenge
    from ecc import EllipticCurve
    from shor_ecdlp import (ShorECDLPSolver, SubgroupIndexer,
                            DenseUnitaryOracle)
    from qiskit import transpile
    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    n, d_true = c.n, c.expected_d
    m = max(1, (n - 1).bit_length())
    ind = SubgroupIndexer(curve, G, n)
    solver = ShorECDLPSolver(curve, G, Q, n,
                             oracle=DenseUnitaryOracle(ind), num_counting=t)
    qc = transpile(solver.build_circuit(), basis_gates=["u3", "cx"],
                   optimization_level=1)
    return qc, n, t, d_true, m


def perm_test(j, k, n, t, dc, n_perm, seed):
    rng = np.random.default_rng(seed)
    obs = _best_dc_z_from_scores(_scores_np(j, k, n, t), dc)
    null = np.array([_best_dc_z_from_scores(_scores_np(j, rng.permutation(k),
                                                       n, t), dc)
                     for _ in range(n_perm)])
    p = (1 + int(np.count_nonzero(null <= obs))) / (1 + n_perm)
    return obs, p


def main():
    n_perm = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    bits = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    t = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    shots = int(sys.argv[4]) if len(sys.argv) > 4 else 230

    from qiskit import transpile
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel, depolarizing_error

    print(f"building m circuit (bits={bits}, t={t}) — transpiling once...")
    t0 = time.time()
    qc, n, t, d_true, m = build_circuit_basis(bits, t)
    n2q = qc.count_ops().get("cx", 0)
    dc = {d_true, (n - d_true) % n}
    pt_w = m  # dense oracle
    print(f"  built in {time.time()-t0:.0f}s: m={m}, n={n}, d_true={d_true}, "
          f"d-class={sorted(dc)}, {qc.num_qubits} qubits, {n2q} cx, "
          f"M/n={(1<<t)/n:.1f}")
    print(f"\nHNP Signal Ladder — m={m} dense, {shots} shots, n_perm={n_perm}, "
          f"{len(SIM_SEEDS)} seeds/row")
    print(f"(2q depolarizing sweep; squared-residual best-dc z; "
          f"null shuffles k vs j; α={ALPHA})\n")
    print(f"  {'2q_err':>8} {'circ_fid≈':>10} {'mean_z':>8} {'mean_p':>8} "
          f"{'power':>6}  signal?   note")
    print("-" * 78)

    # pre-transpile to the simulator basis once (qc is already [u3,cx]; this is
    # cheap and lets every noisy run reuse the same compiled circuit)
    base_sim = AerSimulator()
    isa = transpile(qc, base_sim)

    crossed = None
    prev_sig = True
    for err in ERR_GRID:
        zs, ps = [], []
        for s_seed in SIM_SEEDS:
            if err == 0.0:
                sim = AerSimulator()
            else:
                nm = NoiseModel()
                nm.add_all_qubit_quantum_error(depolarizing_error(err, 2),
                                               ["cx"])
                nm.add_all_qubit_quantum_error(depolarizing_error(err / 10, 1),
                                               ["u3"])
                sim = AerSimulator(noise_model=nm)
            counts = sim.run(isa, shots=shots,
                             seed_simulator=s_seed).result().get_counts()
            sh = parse_shots(counts, t, pt_w, n)
            j = np.array([s[0] for s in sh])
            k = np.array([s[1] for s in sh])
            obs, p = perm_test(j, k, n, t, dc, n_perm, PERM_SEED)
            zs.append(obs)
            ps.append(p)
        mean_z = float(np.mean(zs))
        mean_p = float(np.mean(ps))
        power = float(np.mean([p < ALPHA for p in ps]))
        fid = (1 - err) ** n2q if err else 1.0
        sig = mean_p < ALPHA
        verdict = "✓ signal" if sig else "✗ none"
        note = "noiseless (positive control)" if err == 0.0 else ""
        if prev_sig and not sig and crossed is None:
            crossed = err
        prev_sig = sig
        print(f"  {err:>8.4f} {fid:>10.2e} {mean_z:>8.2f} {mean_p:>8.4f} "
              f"{power:>6.0%}  {verdict:<9} {note}")

    print()
    if crossed:
        fid_cliff = (1 - crossed) ** n2q
        print(f"  → m={m} signal cliff: genuine d-class signal dies around "
              f"2q_err ≈ {crossed:.4f}  (end-to-end circuit fidelity ≈ "
              f"{fid_cliff:.1%})")
    else:
        print(f"  → m={m}: signal present (or absent) across the whole grid — "
              f"no clean crossing found; widen ERR_GRID.")

    print("\n  HOW TO READ (honest): pure depolarizing is BENIGN, so the cliff")
    print("  in NOMINAL 2q error is far kinder than a real device. Place a")
    print("  platform by its EFFECTIVE end-to-end fidelity (SWAP overhead + real")
    print("  noise), not its nominal 2q rate. The m=3 rung was calibrated to")
    print("  real data: IBM (eff fid ≈2e-3) past the cliff (p≈0.61), Quantinuum")
    print("  H2-1E (all-to-all, high eff fid) before it (p≈0.019).")
    if m >= 5:
        print(f"\n  m={m} READ-OUT: this extends the ladder one roadmap rung up.")
        print(f"  The end-to-end fidelity at this cliff is the TARGET a real m={m}")
        print(f"  device must beat to carry genuine signal — directly sizing the")
        print(f"  fidelity/qubit/shot budget for the next paid hardware run.")
    print("\n  CAVEAT: depolarizing shows boundary SHAPE only. Authoritative")
    print("  per-platform verdicts are real-data permutation tests in")
    print("  hnp_score_matrix.py.")


if __name__ == "__main__":
    main()
