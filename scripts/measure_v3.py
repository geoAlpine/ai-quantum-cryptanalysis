"""Measure CF-lift v3 candidate density and hit rate on real IBM data."""
import argparse
import json
import math
import os
import sys
import time

from cf_lift import cf_lift_v3
from challenges import CHALLENGES


def parse_shots(counts: dict, t: int, pt_w: int, n: int):
    triples = []
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k = int(bs[:t], 2) % n
        j = int(bs[t:2*t], 2) % n
        r = int(bs[2*t:], 2) % n
        triples.append((j, k, r, cnt))
    return triples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", required=True)
    ap.add_argument("--bits", type=int, required=True)
    ap.add_argument("--pt-w", type=int, required=True,
                    help="point register width (m+1 for ripple oracle)")
    ap.add_argument("--window", type=int, default=64)
    ap.add_argument("--max-scale", type=int, default=4)
    ap.add_argument("--no-mirror", action="store_true")
    ap.add_argument("--no-bitflip", action="store_true")
    ap.add_argument("--max-cand", type=int, default=0,
                    help="cap candidates per axis (0=no cap)")
    ap.add_argument("--sample", type=int, default=0)
    args = ap.parse_args()

    blob = json.load(open(args.counts))
    counts = blob["counts"]
    meta = blob["meta"]
    t = meta["t"]
    print(f"Loaded {sum(counts.values())} shots, t={t}, bits={args.bits}")

    c = CHALLENGES[args.bits]
    d_true = c.expected_d
    n = c.n

    triples = parse_shots(counts, t, args.pt_w, n)
    if args.sample and args.sample < len(triples):
        import random; random.seed(42)
        triples = random.sample(triples, args.sample)
    print(f"Parsed {len(triples)} triples (n={n})")

    cap = args.max_cand if args.max_cand > 0 else None
    cf_cache: dict[int, list[int]] = {}
    def cf(x):
        if x in cf_cache:
            return cf_cache[x]
        v = cf_lift_v3(x, t, n,
                       window=args.window,
                       max_scale=args.max_scale,
                       include_bitflips=not args.no_bitflip,
                       include_mirror=not args.no_mirror,
                       max_candidates=cap)
        cf_cache[x] = v
        return v

    total_unique_d = 0
    shots_with_hit = 0
    a_sizes = []; b_sizes = []
    t0 = time.time()

    for idx, (j, k, r, cnt) in enumerate(triples):
        a_list = cf(j); b_list = cf(k)
        a_sizes.append(len(a_list)); b_sizes.append(len(b_list))

        d_set = set()
        for b in b_list:
            if b == 0 or math.gcd(b, n) != 1:
                continue
            b_inv = pow(b, -1, n)
            for a in a_list:
                d_cand = ((r - a) * b_inv) % n
                d_set.add(d_cand)

        total_unique_d += len(d_set)
        if d_true in d_set:
            shots_with_hit += cnt

        if (idx + 1) % 5000 == 0:
            print(f"  {idx+1}/{len(triples)} ({time.time()-t0:.1f}s) avg_C={total_unique_d/(idx+1):.0f}")

    n_triples = len(triples)
    n_shots = sum(cnt for _, _, _, cnt in triples)
    avg_C = total_unique_d / n_triples
    avg_a = sum(a_sizes) / len(a_sizes)
    avg_b = sum(b_sizes) / len(b_sizes)
    p_hit = avg_C / n
    expected = p_hit * n_shots

    print()
    print(f"=== v3 (window={args.window}, max_scale={args.max_scale}, mirror={not args.no_mirror}, bitflip={not args.no_bitflip}, cap={cap}) ===")
    print(f"shots: {n_shots}")
    print(f"avg a/axis: {avg_a:.2f}, avg b/axis: {avg_b:.2f}")
    print(f"avg C/shot: {avg_C:.1f}")
    print(f"P(hit/shot): {p_hit:.3e}")
    print(f"expected hits (uniform model): {expected:.2f}")
    print(f"actual hits: {shots_with_hit}")
    if expected > 0:
        print(f"actual/uniform: {shots_with_hit/expected:.2f}")

    print()
    print(f"=== 25-bit projection (n_25={16773667}) ===")
    p_25 = avg_C / 16773667
    for s in [10000, 20000, 30000, 50000, 100000]:
        e = p_25 * s
        p1 = 1 - math.exp(-e)
        print(f"  {s:>6} shots: expected={e:.2f}, P(>=1)={p1:.1%}")


if __name__ == "__main__":
    main()
