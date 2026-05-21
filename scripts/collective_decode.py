"""
Collective candidate-frequency analysis on saved IBM Shor-ECDLP data.

The current ``ShorECDLPSolver.extract()`` short-circuits verification by
precomputing ``d_known`` via classical BSGS — it counts "does this shot's
candidate set contain ``d_known``" rather than "which ``d`` value emerges as
the argmax across all shots' candidate sets". The latter is the actual
quantum-signal-extraction test: if the true ``d`` appears disproportionately
often in the candidate vote tally (vs the uniform-noise baseline of ``Total
votes / n`` per cell), there is collective signal beyond what a brute-force
candidate generator + verification filter can explain.

For each shot ``(j, k, r)``:
  1. Generate ``v3`` candidates ``A = cf_lift_v3(j)``, ``B = cf_lift_v3(k)``.
  2. For each ``(a, b)`` with ``gcd(b, n) == 1``, compute
     ``d_cand = (r - a) * b^{-1} mod n``.
  3. Increment ``votes[d_cand]`` by the shot multiplicity.

Output:
  * Top-K candidates by votes.
  * Uniform-noise expected vote per cell, with z-score of ``d_true``.
  * Rank of ``d_true`` in the vote distribution.

Decision rule for "signal present": ``votes[d_true] / E[uniform]`` must be
significantly above 1.0 (e.g. > 3σ) AND ``d_true`` must rank in the top
candidates (ideally rank 1).

Usage:
    python scripts/collective_decode.py --counts results/_ibm_22bit_t12_counts.json \\
        --bits 22 --pt-w 23 --window 16
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time

import numpy as np

from cf_lift import cf_lift_v3
from challenges import get_challenge


def parse_triples(counts: dict[str, int], t: int, pt_w: int, n: int):
    triples = []
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k = int(bs[:t], 2) % n
        j = int(bs[t:2 * t], 2) % n
        r = int(bs[2 * t:], 2) % n
        triples.append((j, k, r, cnt))
    return triples


def collective_vote(triples, n: int, t: int, window: int,
                    max_scale: int = 4, sample: int | None = None,
                    verbose: bool = True) -> np.ndarray:
    """Accumulate one vote per (shot multiplicity × (a, b) combination) into
    a length-n array indexed by ``d_cand``. Returns the dense vote vector."""
    if sample and sample < len(triples):
        import random
        random.seed(42)
        triples = random.sample(triples, sample)
        if verbose:
            print(f"  sampling {sample} of {len(triples)} triples (seed=42)")

    votes = np.zeros(n, dtype=np.int64)
    cf_cache: dict[int, list[int]] = {}

    def cf(x):
        if x in cf_cache:
            return cf_cache[x]
        v = cf_lift_v3(x, t, n, window=window, max_scale=max_scale)
        cf_cache[x] = v
        return v

    t0 = time.time()
    cumulative_pairs = 0
    for idx, (j, k, r, cnt) in enumerate(triples):
        a_list = cf(j)
        b_list = cf(k)
        b_invs: list[tuple[int, int]] = []
        for b in b_list:
            if b == 0 or math.gcd(b, n) != 1:
                continue
            b_invs.append((b, pow(b, -1, n)))

        # Build the per-shot d_cand set with dedup, then increment.
        d_set: set[int] = set()
        for a in a_list:
            r_minus_a = (r - a) % n
            for _, b_inv in b_invs:
                d_set.add((r_minus_a * b_inv) % n)
        for d_cand in d_set:
            votes[d_cand] += cnt
        cumulative_pairs += len(d_set)

        if verbose and (idx + 1) % 5000 == 0:
            elapsed = time.time() - t0
            print(f"  {idx + 1}/{len(triples)} shots processed "
                  f"({elapsed:.1f}s, ~{cumulative_pairs / (idx + 1):.0f} d-cand/shot)")

    if verbose:
        print(f"  done in {time.time() - t0:.1f}s; total votes={int(votes.sum())}")
    return votes


def report(votes: np.ndarray, n: int, d_true: int, top_k: int = 15):
    total = int(votes.sum())
    e_uniform = total / n
    std_uniform = math.sqrt(e_uniform * (1 - 1 / n))

    top_idx = np.argsort(votes)[::-1][:top_k]
    rank_d_true = int(np.sum(votes > votes[d_true]) + 1)  # 1-indexed
    v_d_true = int(votes[d_true])

    print()
    print(f"=== Collective vote distribution (n={n}) ===")
    print(f"  total votes          : {total:,}")
    print(f"  uniform-noise E[v]/d : {e_uniform:.2f}")
    print(f"  uniform-noise σ      : {std_uniform:.2f}")
    print()
    print(f"  d_true (expected)    : {d_true:,}")
    print(f"  votes(d_true)        : {v_d_true:,}")
    print(f"  ratio to uniform     : {v_d_true / e_uniform:.2f}×")
    z = (v_d_true - e_uniform) / max(std_uniform, 1e-9)
    print(f"  z-score              : {z:+.2f}σ")
    print(f"  rank of d_true       : {rank_d_true:,} / {n:,}")
    if rank_d_true == 1:
        print(f"  *** d_true is argmax of the vote distribution ***")
    elif rank_d_true <= top_k:
        print(f"  d_true is within top-{top_k} (good news)")
    else:
        pct = 100 * rank_d_true / n
        print(f"  d_true is at percentile {pct:.4f}% — no collective signal")
    print()
    print(f"  top-{top_k} candidates:")
    for i, idx in enumerate(top_idx, 1):
        marker = "  ← d_true" if int(idx) == d_true else ""
        print(f"    {i:>2}. d={int(idx):>10,}  votes={int(votes[idx]):>8,}"
              f"  ratio={votes[idx]/e_uniform:.2f}×{marker}")

    return {
        "votes_d_true": v_d_true,
        "rank_d_true": rank_d_true,
        "ratio_to_uniform": v_d_true / e_uniform if e_uniform else 0.0,
        "z_score": z,
        "argmax_is_d_true": rank_d_true == 1,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", required=True)
    ap.add_argument("--bits", type=int, required=True)
    ap.add_argument("--t", type=int, default=None,
                    help="counting register width (default: read from metadata)")
    ap.add_argument("--pt-w", type=int, default=None,
                    help="point register width (default: m+1 for ripple)")
    ap.add_argument("--window", type=int, default=16,
                    help="v3 cf_window (16 ≈ 22-bit calibration)")
    ap.add_argument("--max-scale", type=int, default=4)
    ap.add_argument("--sample", type=int, default=0,
                    help="randomly sample N triples (0 = all)")
    ap.add_argument("--top-k", type=int, default=15)
    args = ap.parse_args()

    blob = json.load(open(args.counts))
    counts = blob["counts"]
    meta = blob["meta"]
    c = get_challenge(args.bits)
    n = c.n
    m = max(1, (n - 1).bit_length())
    pt_w = args.pt_w if args.pt_w is not None else m + 1
    if args.t is not None:
        t = args.t
    elif "t" in meta:
        t = meta["t"]
    else:
        bs_len = len(next(iter(counts)))
        t = (bs_len - pt_w) // 2
        print(f"  inferred t={t} from bs_len={bs_len}, pt_w={pt_w}")

    print(f"=== Collective decoding on {os.path.basename(args.counts)} ===")
    print(f"  bits={args.bits} m={m} t={t} pt_w={pt_w} n={n:,}")
    print(f"  shots: {sum(counts.values()):,}, unique outcomes: {len(counts):,}")
    print(f"  d_true (per metadata): {c.expected_d:,}")
    print(f"  v3 cf_window={args.window}, max_scale={args.max_scale}")
    print()

    triples = parse_triples(counts, t, pt_w, n)
    print(f"Parsed {len(triples):,} triples")

    votes = collective_vote(triples, n, t,
                            window=args.window,
                            max_scale=args.max_scale,
                            sample=args.sample or None)
    report(votes, n, c.expected_d, top_k=args.top_k)


if __name__ == "__main__":
    main()
