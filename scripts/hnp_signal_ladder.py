"""HNP Signal Ladder — the noise threshold where genuine d-class signal dies.

The project's strategic moat (see memory three-year-genuine-record-strategy):
draw the signal-vs-noise boundary for collective HNP recovery, so that a real
hardware datapoint can be *placed* on a first-principles curve rather than
asserted in isolation.

This tool is fully OFFLINE and FREE — no QPU/emulator quota. It takes the exact
m=3 dense Phase 1 circuit, injects a two-qubit depolarizing error at a grid of
rates, simulates 230 shots (matching the real H2-1E run), and runs the SAME
permutation test as hnp_score_matrix.py (statistic = best-dc z; null = shuffle
k vs j). The output is the noise level at which p crosses 0.05 — i.e. where a
genuine collective signal stops being detectable.

It brackets the real measurements (noiseless = strong signal positive control;
real H2-1E 230sh p≈0.019 = signal; real IBM 4096sh p≈0.61 = none) and shows the
SHAPE of the signal-vs-noise boundary as a function of END-TO-END circuit
fidelity.

IMPORTANT (learned 2026-05-29): pure depolarizing noise is BENIGN — the
collective signal survives to ~3-12% end-to-end circuit fidelity, i.e. even at
IBM's *nominal* 2q error (~0.2%) a depolarizing-only model still shows signal.
So a platform is NOT placed on this ladder by its nominal per-gate rate but by
its EFFECTIVE circuit fidelity. IBM's effective fidelity (~2e-3) is crushed far
past the cliff by SWAP overhead (limited connectivity inflates 643→~1243 2q
gates) plus coherent/readout/crosstalk noise; Quantinuum's all-to-all
connectivity (no SWAPs) keeps its effective fidelity before the cliff. THAT —
end-to-end fidelity, not nominal 2q rate — is why H2 carries the signal and IBM
does not.

CAVEAT: a single depolarizing channel on cx is illustrative of the boundary
SHAPE only; it is far kinder than real device noise, so do NOT read platform
placement off the nominal-err column. The authoritative per-platform verdicts
remain the real-data permutation tests in hnp_score_matrix.py.

Usage:
    PYTHONPATH=src python scripts/hnp_signal_ladder.py
    PYTHONPATH=src python scripts/hnp_signal_ladder.py 2000   # n_perm
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/
from hnp_score_matrix import (  # noqa: E402
    _scores_np, _best_dc_z_from_scores, parse_shots,
)

SHOTS = 230            # match the real H2-1E genuine-signal run
SIM_SEEDS = [1, 7, 42, 123, 2026]  # average over independent noisy runs
PERM_SEED = 20260529
ALPHA = 0.05
# Two-qubit depolarizing rates to sweep. 0 = noiseless positive control;
# ~0.001 ≈ high-fidelity trapped-ion class; ~0.002+ ≈ IBM superconducting class.
ERR_GRID = [0.0, 0.0003, 0.0006, 0.001, 0.0015, 0.002, 0.003, 0.005, 0.01]


def build_circuit_basis():
    from challenges import get_challenge
    from ecc import EllipticCurve
    from shor_ecdlp import (ShorECDLPSolver, SubgroupIndexer,
                            DenseUnitaryOracle)
    from qiskit import transpile
    c = get_challenge(4)
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    n, d_true, t = c.n, c.expected_d, 6
    ind = SubgroupIndexer(curve, G, n)
    solver = ShorECDLPSolver(curve, G, Q, n,
                             oracle=DenseUnitaryOracle(ind), num_counting=t)
    qc = transpile(solver.build_circuit(), basis_gates=["u3", "cx"],
                   optimization_level=1)
    return qc, n, t, d_true


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
    from qiskit import transpile
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel, depolarizing_error

    qc, n, t, d_true = build_circuit_basis()
    n2q = qc.count_ops().get("cx", 0)
    dc = {d_true, (n - d_true) % n}
    print(f"HNP Signal Ladder — m=3 dense, {SHOTS} shots, {n2q} cx gates, "
          f"n_perm={n_perm}")
    print(f"(2q depolarizing sweep; statistic best-dc z; null shuffles k vs j; "
          f"α={ALPHA})\n")
    print(f"  (each row averages {len(SIM_SEEDS)} independent noisy runs)\n")
    print(f"  {'2q_err':>8} {'circ_fid≈':>10} {'mean_z':>8} {'mean_p':>8} "
          f"{'power':>6}  signal?   note")
    print("-" * 78)

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
                # light 1q term so it isn't purely 2q-dominated
                nm.add_all_qubit_quantum_error(depolarizing_error(err / 10, 1),
                                               ["u3"])
                sim = AerSimulator(noise_model=nm)
            counts = sim.run(transpile(qc, sim), shots=SHOTS,
                             seed_simulator=s_seed).result().get_counts()
            shots = parse_shots(counts, t, 3, n)
            j = np.array([s[0] for s in shots])
            k = np.array([s[1] for s in shots])
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
        print(f"  → signal cliff: genuine d-class signal dies around "
              f"2q_err ≈ {crossed:.4f}  (end-to-end circuit fidelity ≈ "
              f"{fid_cliff:.1%})")

    print("\n  HOW TO READ THIS (important, honest):")
    print("  The right axis is END-TO-END circuit fidelity, NOT the nominal")
    print("  per-gate rate. Pure depolarizing noise is BENIGN — the signal here")
    print("  survives to ~3-12% circuit fidelity. So a device's nominal 2q")
    print("  error does NOT place it on this ladder; its *effective* fidelity")
    print("  (after SWAP overhead + coherent/readout/crosstalk noise) does.")
    print()
    print("  Placing the REAL measurements by effective fidelity:")
    print("    • Quantinuum H2-1E : all-to-all (~702 native 2q, no SWAP), high")
    print("      per-gate fidelity → effective fid lands BEFORE the cliff →")
    print("      p≈0.019 measured (signal). Matches the ~0.25-0.5-fid rows here.")
    print("    • IBM ibm_kingston : limited connectivity inflates 643→~1243 2q")
    print("      via SWAPs, plus non-depolarizing noise → real est-fid ≈ 2e-3,")
    print("      FAR past the cliff → p≈0.61 measured (no signal).")
    print()
    print("  KEY INSIGHT: the IBM-vs-H2 gap is NOT the nominal 2q rate (at which")
    print("  depolarizing still shows signal) — it is END-TO-END fidelity, which")
    print("  SWAP overhead + real (non-depolarizing) noise crush on IBM. That is")
    print("  why a trapped-ion machine carries the collective signal and a")
    print("  superconducting one of similar nominal 2q error does not.")
    print()
    print("  CAVEAT: depolarizing-only is illustrative of the boundary SHAPE; it")
    print("  is benign vs real noise, so do not read platform placement off the")
    print("  nominal-err column. Authoritative per-platform verdicts are the")
    print("  real-data permutation tests in hnp_score_matrix.py (H2 p≈0.019,")
    print("  IBM p≈0.61).")


if __name__ == "__main__":
    main()
