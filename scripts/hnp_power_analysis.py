"""Power analysis: how many shots does a genuine d-class signal need?

Companion to ``scripts/hnp_score_matrix.py``. That tool established (via a
permutation test) that the current data does NOT yet statistically support
a genuine d-class signal — IBM pooled p=0.61 (signal absent, confirmed),
H2-1E pooled p=0.16 (underpowered at 64 shots). This tool answers the
follow-up the project actually needs to plan the next hardware run:

    "How many shots must we collect for the d-class signal to reach
     statistical significance (p<0.05) with adequate power (≥0.8)?"

That number is the gating input to the Phase 2+ shot budget / cost plan.

Two estimates:

  METHOD A — noiseless subsample (OPTIMISTIC ceiling)
    Subsample the noiseless ground-truth shots at a grid of N, run the
    permutation test R times per N, report power = fraction with p<0.05.
    This is the best case: a perfect, noise-free signal. The N where
    power crosses 0.8 is the floor — hardware can only need MORE.

  METHOD B — H2-1E bootstrap (REALISTIC, conditional)
    Bootstrap-resample the 64 pooled H2-1E shots up to a grid of N, run
    the permutation test R times per N, report power. This projects
    "IF the per-shot d-class effect observed in the 64 H2-1E shots is real
    (not a 64-shot fluctuation), how many H2-1E-like shots are needed?"
    Conditional on the effect being real — bootstrap cannot manufacture a
    signal that isn't there, but it faithfully scales whatever effect the
    sample carries.

Both use the same null + statistic as hnp_score_matrix (shuffle k vs j;
best-dc z). Seeded for reproducibility.

Usage:
    PYTHONPATH=src python scripts/hnp_power_analysis.py
    PYTHONPATH=src python scripts/hnp_power_analysis.py 1200 60   # n_perm resamples
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/
from hnp_score_matrix import (  # noqa: E402
    noiseless_ground_truth, load_run, find_datasets,
    _scores_np, _best_dc_z_from_scores,
)

ALPHA = 0.05
TARGET_POWER = 0.8
N_GRID = [16, 32, 64, 128, 256, 512, 1024, 2048]
SEED = 20260529


def perm_pvalue(j, k, n, t, dc, n_perm, rng):
    """One permutation-test p-value (shuffle k vs j; best-dc z statistic)."""
    observed = _best_dc_z_from_scores(_scores_np(j, k, n, t), dc)
    null = np.empty(n_perm)
    for i in range(n_perm):
        null[i] = _best_dc_z_from_scores(_scores_np(j, rng.permutation(k), n, t), dc)
    return (1 + int(np.count_nonzero(null <= observed))) / (1 + n_perm)


def power_at_N(j_pool, k_pool, n, t, dc, N, *, mode, n_perm, n_resample, rng):
    """Estimate power at sample size N.

    mode='subsample' draws N without replacement (N ≤ len(pool));
    mode='bootstrap' draws N with replacement (any N).
    Returns fraction of resamples whose perm-test p < ALPHA.
    """
    pool = len(j_pool)
    hits = 0
    done = 0
    for _ in range(n_resample):
        if mode == "subsample":
            if N > pool:
                return None  # can't subsample more than we have
            idx = rng.choice(pool, size=N, replace=False)
        else:  # bootstrap
            idx = rng.choice(pool, size=N, replace=True)
        p = perm_pvalue(j_pool[idx], k_pool[idx], n, t, dc, n_perm, rng)
        hits += int(p < ALPHA)
        done += 1
    return hits / done if done else None


def run_curve(label, j, k, n, t, dc, *, mode, n_perm, n_resample):
    rng = np.random.default_rng(SEED)
    print(f"\n  {label}  (pool={len(j)} shots, mode={mode}, "
          f"n_perm={n_perm}, resample={n_resample}/N)")
    print(f"    {'N':>6}  {'power(p<0.05)':>14}")
    crossed = None
    for N in N_GRID:
        pw = power_at_N(j, k, n, t, dc, N, mode=mode,
                        n_perm=n_perm, n_resample=n_resample, rng=rng)
        if pw is None:
            continue
        flag = ""
        if crossed is None and pw >= TARGET_POWER:
            crossed = N
            flag = "  ← power ≥ 0.8"
        print(f"    {N:>6}  {pw:>13.2f}{flag}")
    if crossed:
        print(f"    → reaches power {TARGET_POWER:.0%} at N ≈ {crossed} shots")
    else:
        print(f"    → does NOT reach power {TARGET_POWER:.0%} within "
              f"N ≤ {N_GRID[-1]} (need more, or effect too weak)")
    return crossed


def main():
    n_perm = int(sys.argv[1]) if len(sys.argv) > 1 else 800
    n_resample = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    print("HNP d-class power analysis — shots needed for p<0.05 @ power 0.8")
    print(f"(permutation null: shuffle k vs j; statistic: best-dc z; "
          f"α={ALPHA}, seed={SEED})")

    # Noiseless ground truth (optimistic ceiling).
    gt = noiseless_ground_truth()
    gt_cross = None
    if gt:
        dc = {gt["d_true"], gt["anti_d"]}
        gt_cross = run_curve("METHOD A — noiseless GT (ceiling)",
                             gt["j"], gt["k"], gt["n"], gt["t"], dc,
                             mode="subsample", n_perm=n_perm,
                             n_resample=n_resample)

    # H2-1E pooled (realistic, conditional on the effect being real).
    runs = [load_run(*d) for d in find_datasets()]
    h2 = [r for r in runs if r["platform"] == "quantinuum_h2-1e"]
    h2_cross = None
    if h2:
        j = np.concatenate([r["j"] for r in h2])
        k = np.concatenate([r["k"] for r in h2])
        dc = {h2[0]["d_true"], h2[0]["anti_d"]}
        h2_cross = run_curve("METHOD B — H2-1E bootstrap (realistic, "
                            "conditional)",
                            j, k, h2[0]["n"], h2[0]["t"], dc,
                            mode="bootstrap", n_perm=n_perm,
                            n_resample=n_resample)

    print("\n" + "=" * 74)
    print("PLANNING READ-OUT")
    print("=" * 74)
    if gt_cross:
        print(f"  • Perfect-signal floor (noiseless): ~{gt_cross} shots to "
              f"reach p<0.05 @ 0.8 power.")
    if h2_cross:
        print(f"  • H2-1E projection (if the 64-shot effect is real): "
              f"~{h2_cross} shots.")
    elif h2:
        print(f"  • H2-1E: did not reach power 0.8 within N≤{N_GRID[-1]} — "
              f"either the per-shot\n    effect is weaker than the 64-shot "
              f"sample suggests (i.e. partly a\n    fluctuation), or the run "
              f"genuinely needs >{N_GRID[-1]} shots. Collect a\n    larger "
              f"H2-1E run and re-test before committing to a genuine-signal "
              f"claim.")
    print("\n  Caveat: bootstrap is conditional — it scales whatever effect "
          "the 64\n  shots carry; it cannot prove the effect is real. The "
          "definitive test is a\n  fresh, larger H2-1E run fed back through "
          "hnp_score_matrix.py.")


if __name__ == "__main__":
    main()
