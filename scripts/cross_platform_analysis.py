"""Cross-platform Phase 1 analysis: IBM ibm_kingston vs Quantinuum H2-1E.

Reads all available Phase 1 result JSONs (IBM kingston Phase 1 + 3 reps,
plus any Quantinuum H2-1E runs) and produces:

  - Per-run summary table (rank, gap, recovery path)
  - d-class top-K membership statistics across runs
  - HNP top-1 winner distribution (the kingston "d=4 always wins" question)
  - Score-gap distribution across platforms

Designed to be re-run as more datapoints arrive. Final output is
paper-quality cross-platform comparison.

Usage:
    python scripts/cross_platform_analysis.py
"""
from __future__ import annotations

import glob
import json
import os
from collections import Counter


def find_datasets():
    """Locate all Phase 1 result files across platforms."""
    out = []
    # IBM ibm_kingston Phase 1 series
    for label, path in [
        ("IBM Phase 1",     "results/shor_4bit_t6_1024shots_hnp_ibm_phase1.json"),
        ("IBM Rep 1",       "results/shor_4bit_t6_1024shots_hnp_ibm_rep1.json"),
        ("IBM Rep 2",       "results/shor_4bit_t6_1024shots_hnp_ibm_rep2.json"),
        ("IBM Rep 3",       "results/shor_4bit_t6_1024shots_hnp_ibm_rep3.json"),
    ]:
        if os.path.exists(path):
            out.append((label, "ibm_kingston", path))
    # Quantinuum H2-1E series — two filename formats coexist:
    #   shor_4bit_t6_16shots_hnp_h2-1e_<label>.json  (clean, post-2026-05-29)
    #   shor_azure_4bit_t6_*shots_quantinuum.sim.h2-1e_*.json  (legacy)
    for path in sorted(glob.glob("results/shor_4bit_t6_16shots_hnp_h2-1e_*.json")):
        label = path.split("_h2-1e_")[-1].replace(".json", "")
        out.append((f"H2 {label}", "quantinuum_h2-1e", path))
    return out


def parse_shots(counts, t, pt_w, n):
    shots = []
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k = int(bs[:t], 2) % n
        j = int(bs[t:2 * t], 2) % n
        r = int(bs[2 * t:], 2) % n
        for _ in range(cnt):
            shots.append((j, k, r))
    return shots


def analyze_dataset(label, platform, path):
    """Extract HNP analysis from a single result file."""
    from lattice_postprocess import hnp_score
    blob = json.load(open(path))
    n = blob.get("n", 7)
    t = blob.get("t", 6)
    d_true = blob.get("expected_d", 6)
    oracle = blob.get("oracle", "dense")
    pt_w = 3 if oracle == "dense" else 4  # m=3, ripple → m+1

    counts = blob["counts"]
    shots = parse_shots(counts, t, pt_w, n)
    scores = sorted(((d, hnp_score(d, shots, n, t)) for d in range(n)),
                    key=lambda x: x[1])
    rank_true = 1 + next(i for i, (d, _) in enumerate(scores) if d == d_true)
    top1_d, top1_s = scores[0]
    top2_d, top2_s = scores[1] if len(scores) > 1 else (None, top1_s)
    gap_pct = (top2_s - top1_s) / max(1e-9, top2_s) * 100
    d_class = {d_true, (n - d_true) % n}
    top3 = {d for d, _ in scores[:3]}
    top5 = {d for d, _ in scores[:5]}
    top7 = {d for d, _ in scores[:7]}

    return {
        "label": label,
        "platform": platform,
        "shots": sum(counts.values()),
        "unique": len(counts),
        "rank_d_true": rank_true,
        "argmax_d": top1_d,
        "gap_pct": gap_pct,
        "dclass_in_top3": bool(top3 & d_class),
        "dclass_in_top5": bool(top5 & d_class),
        "dclass_in_top7": bool(top7 & d_class),
        "recovered": blob.get("recovered_d") if blob.get("success") else blob.get("recovery_d"),
        "recovery_success": blob.get("success", False),
        "rank_in_hnp": blob.get("rank_in_hnp"),
        "via_anti_d": blob.get("verified_via_anti_d"),
        "top5_d": [d for d, _ in scores[:5]],
    }


def main():
    datasets = find_datasets()
    if not datasets:
        print("No Phase 1 datasets found")
        return

    print(f"=== Cross-platform Phase 1 analysis ({len(datasets)} runs) ===\n")
    results = []
    for label, platform, path in datasets:
        try:
            r = analyze_dataset(label, platform, path)
            results.append(r)
        except Exception as e:
            print(f"  {label}: ERROR {type(e).__name__}: {str(e)[:80]}")

    # Per-run table
    print(f"{'Run':<14} {'Platform':<18} {'shots':>5} {'uniq':>4} "
          f"{'rank':>4} {'top-1':>5} {'gap%':>6} {'recover':>7}")
    print("-" * 95)
    for r in results:
        plat_short = r["platform"].replace("ibm_", "ibm.").replace("quantinuum_", "q.")
        rec = ("✓ "+str(r["recovered"])
               if r["recovery_success"] else "✗ "+str(r["recovered"]))
        print(f"  {r['label']:<12} {plat_short:<18} {r['shots']:>5} "
              f"{r['unique']:>4} {r['rank_d_true']:>4} {r['argmax_d']:>5} "
              f"{r['gap_pct']:>5.2f}% {rec:>7}")

    # Cross-run stats
    print(f"\n=== Aggregate statistics ===")
    ibm_runs = [r for r in results if "ibm" in r["platform"]]
    qm_runs  = [r for r in results if "quantinuum" in r["platform"]]

    for batch_name, batch in [("IBM ibm_kingston", ibm_runs), ("Quantinuum H2-1E", qm_runs)]:
        if not batch:
            continue
        n = len(batch)
        recov = sum(1 for r in batch if r["recovery_success"])
        top1_counter = Counter(r["argmax_d"] for r in batch)
        top3_hit = sum(1 for r in batch if r["dclass_in_top3"])
        top5_hit = sum(1 for r in batch if r["dclass_in_top5"])
        top7_hit = sum(1 for r in batch if r["dclass_in_top7"])
        print(f"\n  {batch_name} ({n} runs):")
        print(f"    Recovery success     : {recov}/{n}")
        print(f"    d-class in HNP top-3 : {top3_hit}/{n}")
        print(f"    d-class in HNP top-5 : {top5_hit}/{n}")
        print(f"    d-class in HNP top-7 : {top7_hit}/{n}")
        # NOTE: the top-1 winner distribution is reported for the record
        # only — it is NOT a signal metric. The HNP score is symmetric
        # under d ↔ anti_d, and on noiseless ground truth anti_d (not
        # d_true) is the argmax (verified 2026-05-29). "d_true won argmax
        # k/n" is within-d-class noise. The defensible signal metric is
        # d-class separation vs the noise plateau — see
        # scripts/hnp_score_matrix.py.
        print(f"    HNP top-1 winner distribution (NOT a signal metric — "
              f"±d degenerate):")
        for d, cnt in top1_counter.most_common():
            print(f"      d={d}: {cnt}/{n}")


if __name__ == "__main__":
    main()
