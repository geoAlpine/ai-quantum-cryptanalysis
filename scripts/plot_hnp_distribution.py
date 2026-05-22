"""
Plot the HNP score distribution and shot (j, k) heatmap from a counts
file (saved IBM data or fresh Aer sim).

Three panels:
  1. ``HNP score per d`` — full bar chart over d ∈ [0, n) with
     d_true / anti-d highlighted. Lets us read off rank, gap, dispersion
     of competitors.
  2. ``shot (j, k) heatmap`` — 2D histogram with M-by-M bins. The
     expected Shor peak positions for d_true are overlaid; how cleanly
     shots cluster on those crosses is a direct visual signal-strength
     metric.
  3. ``residue (j + d·k) mod M histogram`` for both d_true and
     ``-d_true mod n``. Should overlap (Shor symmetry) and concentrate
     at the n expected peak positions.

This is the "look at the data" tool for analysing post-submission
results and tuning the next iteration's parameters.

Usage:
    python scripts/plot_hnp_distribution.py \\
        --counts results/shor_4bit_t6_1024shots_hnp_ibm.json \\
        --out results/shor_4bit_t6_diagnostics.png
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from challenges import get_challenge
from lattice_postprocess import hnp_score


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
    ap.add_argument("--counts", required=True,
                    help="JSON with {counts, meta} (saved IBM job) or {counts, bits, t, ...}")
    ap.add_argument("--out", default="hnp_diagnostics.png")
    ap.add_argument("--bits", type=int,
                    help="Override bits from metadata (for raw counts file)")
    ap.add_argument("--t", type=int, help="Override t from metadata")
    ap.add_argument("--pt-w", type=int, help="Override pt_w (m for dense, m+1 for ripple)")
    args = ap.parse_args()

    blob = json.load(open(args.counts))
    if "meta" in blob:
        meta = blob["meta"]
        counts = blob["counts"]
    else:
        meta = blob
        counts = blob.get("counts", blob)

    bits = args.bits or meta.get("bits")
    t = args.t or meta.get("t")
    if bits is None or t is None:
        raise SystemExit("need bits, t in metadata or via --bits / --t flags")

    c = get_challenge(bits)
    n = c.n
    d_true = c.expected_d
    m = max(1, (n - 1).bit_length())

    bs_len = len(next(iter(counts)))
    if args.pt_w is not None:
        pt_w = args.pt_w
    else:
        # Auto-detect.
        for try_pt_w in (m, m + 1):
            if bs_len == 2 * t + try_pt_w:
                pt_w = try_pt_w
                break
        else:
            raise SystemExit(f"can't auto-detect pt_w; bs_len={bs_len}, t={t}, m={m}")

    M = 1 << t
    shots = parse_shots(counts, t, pt_w, n)
    print(f"loaded {len(shots):,} shots, n={n}, M={M}, pt_w={pt_w}, d_true={d_true}")

    # Panel 1: HNP score per d
    scores = [(d, hnp_score(d, shots, n, t)) for d in range(n)]
    sorted_scores = sorted(scores, key=lambda x: x[1])
    rank_of_d_true = next(i for i, (d, _) in enumerate(sorted_scores) if d == d_true) + 1

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    ds, ss = zip(*scores)
    colors = []
    for d in ds:
        if d == d_true:
            colors.append("tab:green")
        elif d == (n - d_true) % n:
            colors.append("tab:orange")
        else:
            colors.append("tab:gray")
    axes[0].bar(ds, ss, color=colors)
    axes[0].set_xlabel("d candidate")
    axes[0].set_ylabel("HNP score (lower = better)")
    axes[0].set_title(f"HNP score per d  (d_true rank = {rank_of_d_true} / {n})")
    axes[0].set_xticks(list(range(n)))
    axes[0].axhline(min(ss), linestyle="--", linewidth=0.5, color="k", alpha=0.5)
    legend_elems = [
        plt.Rectangle((0, 0), 1, 1, fc="tab:green", label=f"d_true = {d_true}"),
        plt.Rectangle((0, 0), 1, 1, fc="tab:orange",
                       label=f"−d_true mod n = {(n - d_true) % n}"),
    ]
    axes[0].legend(handles=legend_elems, loc="upper right")

    # Panel 2: (j, k) heatmap
    jk_counter = Counter()
    for (j, k, _r) in shots:
        jk_counter[(j, k)] += 1
    # Bin by raw register value (mod M) instead of mod n
    bins = np.zeros((M, M), dtype=int)
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k_raw = int(bs[:t], 2)
        j_raw = int(bs[t:2 * t], 2)
        bins[j_raw, k_raw] += cnt
    axes[1].imshow(bins.T, origin="lower", aspect="auto", cmap="viridis")
    axes[1].set_xlabel("j_meas")
    axes[1].set_ylabel("k_meas")
    axes[1].set_title(f"(j, k) heatmap  (M = {M})")
    # Overlay expected peak crosses for d_true.
    expected = sorted({(s * M + n // 2) // n % M for s in range(n)})
    for s_a in range(n):
        a = (s_a * M + n // 2) // n
        for s_b in range(n):
            b = (s_b * M + n // 2) // n
            axes[1].plot(a, b, "rx", markersize=6, alpha=0.5)

    # Panel 3: residue (j + d·k) mod M for d_true and anti-d.
    residues_dtrue = [((j + d_true * k) % M) for (j, k, _r) in shots]
    residues_antid = [((j + (n - d_true) * k) % M) for (j, k, _r) in shots]
    axes[2].hist([residues_dtrue, residues_antid], bins=range(0, M + 1),
                  label=[f"d = d_true ({d_true})",
                         f"d = −d_true ({(n - d_true) % n})"],
                  color=["tab:green", "tab:orange"], alpha=0.7)
    for e in expected:
        axes[2].axvline(e, color="red", linestyle="--", linewidth=0.7, alpha=0.5)
    axes[2].set_xlabel("(j + d·k) mod M")
    axes[2].set_ylabel("count")
    axes[2].set_title(f"residue distribution  (peaks expected at {expected})")
    axes[2].legend()

    plt.tight_layout()
    plt.savefig(args.out, dpi=120)
    print(f"saved diagnostic plot to {args.out}")


if __name__ == "__main__":
    main()
