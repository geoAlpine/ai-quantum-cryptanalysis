"""Submit the m=3 dense Shor-ECDLP circuit to IonQ (Azure Quantum).

Cross-platform companion to the Quantinuum runs. Goal: a second independent
trapped-ion datapoint — does the d-class signal survive IonQ's noise too?
(Quantinuum H2-1E showed p_LR≈0.0003; IBM showed p≈0.61.)

Two-step protocol (both on ionq.simulator, which is FREE — 0 AQT):
  1. IDEAL run (no noise) — POSITIVE CONTROL + bit-order calibration. IonQ may
     order measured bits differently from Quantinuum, so we try both the normal
     and reversed parse and lock whichever makes the noiseless d-class
     significant (a convention, not signal — calibrated on the known-signal
     ideal run, then applied unchanged to the noisy run).
  2. Aria-NOISE run — the actual cross-platform datapoint, parsed with the
     bit order locked in step 1.

Result is saved so hnp_score_matrix.py can pick it up, and the permutation test
(p_sq + p_LR, same as that tool) is printed inline.

Usage:
    PYTHONPATH=src python scripts/ionq_submit.py            # 1024 shots, aria-1
    PYTHONPATH=src python scripts/ionq_submit.py 2048 aria-1
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/
from hnp_score_matrix import (  # noqa: E402
    _scores_np, _nll_scores_np, _best_dc_z_from_scores,
)

PERM_SEED = 20260529
N_PERM = 3000


def build_circuit(t=6):
    from challenges import get_challenge
    from ecc import EllipticCurve
    from shor_ecdlp import (ShorECDLPSolver, SubgroupIndexer,
                            DenseUnitaryOracle)
    from qiskit import transpile
    c = get_challenge(4)
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    n, d_true = c.n, c.expected_d
    m = max(1, (n - 1).bit_length())
    solver = ShorECDLPSolver(curve, G, Q, n,
                             oracle=DenseUnitaryOracle(SubgroupIndexer(curve, G, n)),
                             num_counting=t)
    # transpile to a standard basis so the IonQ backend ingests it cleanly
    qc = transpile(solver.build_circuit(), basis_gates=["u3", "cx"],
                   optimization_level=1)
    return qc, n, t, d_true, m


def parse_counts(counts, t, pt_w, n, reverse):
    shots = []
    for bs, cnt in counts.items():
        b = bs.replace(" ", "")
        if reverse:
            b = b[::-1]
        if len(b) != 2 * t + pt_w:
            continue
        k = int(b[:t], 2) % n
        j = int(b[t:2 * t], 2) % n
        r = int(b[2 * t:], 2) % n
        shots.extend([(j, k, r)] * cnt)
    return shots


def perm_p(j, k, n, t, dc, score_fn):
    rng = np.random.default_rng(PERM_SEED)
    obs = _best_dc_z_from_scores(score_fn(j, k, n, t), dc)
    null = np.array([_best_dc_z_from_scores(score_fn(j, rng.permutation(k), n, t), dc)
                     for _ in range(N_PERM)])
    return obs, (1 + int(np.count_nonzero(null <= obs))) / (1 + N_PERM)


def run_ionq(noise_model, shots):
    from quantum_ecc import load_azure_credentials
    from azure.quantum import Workspace
    from azure.quantum.qiskit import AzureQuantumProvider
    ws = Workspace(**load_azure_credentials())
    be = AzureQuantumProvider(workspace=ws).get_backend("ionq.simulator")
    qc, n, t, d_true, m = build_circuit()
    if noise_model:
        be.options.update_options(noise={"model": noise_model})
    job = be.run(qc, shots=shots)
    counts = job.result().get_counts()
    return counts, n, t, d_true, m, job.id()


def analyze(counts, n, t, pt_w, dc, reverse):
    sh = parse_counts(counts, t, pt_w, n, reverse)
    if not sh:
        return None
    j = np.array([s[0] for s in sh])
    k = np.array([s[1] for s in sh])
    _, p_sq = perm_p(j, k, n, t, dc, _scores_np)
    _, p_lr = perm_p(j, k, n, t, dc, _nll_scores_np)
    return {"n_parsed": len(sh), "p_sq": p_sq, "p_lr": p_lr}


def main():
    shots = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
    noise = sys.argv[2] if len(sys.argv) > 2 else "aria-1"

    # --- Step 1: IDEAL run (positive control + bit-order calibration) ---
    print(f"=== IonQ ideal run (no noise), {shots} shots — bit-order "
          f"calibration ===")
    counts, n, t, d_true, m, jid = run_ionq(None, shots)
    dc = {d_true, (n - d_true) % n}
    print(f"  job {jid}: {sum(counts.values())} shots, {len(counts)} unique; "
          f"n={n}, d_true={d_true}, d-class={sorted(dc)}")
    best = None
    for rev in (False, True):
        a = analyze(counts, n, t, m, dc, rev)
        if a:
            print(f"  parse reverse={rev!s:5}: parsed={a['n_parsed']} "
                  f"p_sq={a['p_sq']:.4f} p_lr={a['p_lr']:.4f}")
            if best is None or a["p_lr"] < best[1]["p_lr"]:
                best = (rev, a)
    if best is None:
        print("  ERROR: no shots parsed in either bit order — circuit/width "
              "mismatch.")
        return 1
    reverse = best[0]
    if best[1]["p_lr"] > 0.05 and best[1]["p_sq"] > 0.05:
        print(f"  ⚠️ ideal run NOT significant in either bit order "
              f"(best p_lr={best[1]['p_lr']:.3f}). Aborting — parse/circuit "
              f"issue, not a noise question.")
        return 1
    print(f"  ✅ bit order locked: reverse={reverse} (ideal positive control "
          f"significant). Proceeding to noise.")

    # --- Step 2: Aria-NOISE run (the cross-platform datapoint) ---
    print(f"\n=== IonQ {noise} noise run, {shots} shots — cross-platform "
          f"datapoint ===")
    ncounts, n, t, d_true, m, njid = run_ionq(noise, shots)
    a = analyze(ncounts, n, t, m, dc, reverse)
    print(f"  job {njid}: {sum(ncounts.values())} shots, {len(ncounts)} unique")
    print(f"  parsed={a['n_parsed']}  p_sq={a['p_sq']:.4f}  p_lr={a['p_lr']:.4f}")
    sig = a["p_lr"] < 0.05 or a["p_sq"] < 0.05
    if sig:
        print(f"  ✅ GENUINE d-class signal on IonQ {noise} noise "
              f"(p_LR={a['p_lr']:.4f}). Second trapped-ion platform confirms "
              f"the H2-1E result.")
    else:
        print(f"  ❌ no significant signal on IonQ {noise} (p_LR={a['p_lr']:.4f}).")

    os.makedirs("results", exist_ok=True)
    out = f"results/shor_ionq_4bit_t6_{shots}shots_{noise}_{njid[:8]}.json"
    with open(out, "w") as f:
        json.dump({"platform": "ionq", "target": "ionq.simulator",
                   "noise_model": noise, "job_id": njid, "bits": 4, "t": t,
                   "n": n, "expected_d": d_true, "oracle": "dense",
                   "shots": shots, "bit_reverse": reverse,
                   "p_sq": a["p_sq"], "p_lr": a["p_lr"],
                   "counts": ncounts}, f, indent=2)
    print(f"  saved → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
