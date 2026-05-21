"""
Measure CF-lift extractor candidate density (C/shot) on real IBM data.

For each shot (j, k, r), counts:
  - distinct a_candidates from CF-lift on j
  - distinct b_candidates from CF-lift on k
  - distinct d_candidates = (r - a) * b^-1 mod n  (verified-form, deduped)
  - whether d_true is among them (hit indicator)

Compares hit rate to uniform-noise prediction (C * shots / n).
"""
import argparse
import json
import math
import os
import sys
import time

from challenges import CHALLENGES
from ecc import EllipticCurve
from shor_ecdlp import ShorECDLPSolver, RippleCarryOracle, SubgroupIndexer


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
    ap.add_argument("--candidates-target", type=int, default=25)
    ap.add_argument("--sample", type=int, default=0,
                    help="sample N shots for speed (0=all)")
    args = ap.parse_args()

    blob = json.load(open(args.counts))
    counts = blob["counts"]
    meta = blob["meta"]
    t = meta["t"]
    print(f"Loaded {sum(counts.values())} shots, t={t}, bits={args.bits}")

    c = CHALLENGES[args.bits]
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    d_true = c.expected_d

    # Build solver only enough to get oracle.point_register_width and use _cf_lift.
    # SubgroupIndexer enumerate(n) is too slow for 25-bit but for ≤22-bit it's fine.
    print(f"Building SubgroupIndexer (n={c.n})... ", end="", flush=True)
    t0 = time.time()
    solver = ShorECDLPSolver(curve, G, Q, c.n, num_counting=t)
    print(f"done ({time.time()-t0:.1f}s)")

    pt_w = solver.oracle.point_register_width()
    triples = parse_shots(counts, t, pt_w, c.n)
    if args.sample and args.sample < len(triples):
        import random
        random.seed(42)
        triples = random.sample(triples, args.sample)
    print(f"Parsed {len(triples)} triples (pt_w={pt_w})")

    # Hijack candidates_target by re-calling _cf_lift directly with that arg.
    cf_cache: dict[tuple[int, int], list[int]] = {}
    def cf_lift(x):
        key = (x, args.candidates_target)
        if key not in cf_cache:
            cf_cache[key] = solver._cf_lift(x, t, c.n,
                                             candidates_target=args.candidates_target)
        return cf_cache[key]

    total_d_candidates = 0
    total_unique_d = 0
    shots_with_hit = 0
    a_sizes = []
    b_sizes = []

    t0 = time.time()
    for idx, (j, k, r, cnt) in enumerate(triples):
        a_list = cf_lift(j)
        b_list = cf_lift(k)
        a_sizes.append(len(a_list))
        b_sizes.append(len(b_list))

        d_set = set()
        for b in b_list:
            if b == 0 or math.gcd(b, c.n) != 1:
                continue
            b_inv = pow(b, -1, c.n)
            for a in a_list:
                d_cand = ((r - a) * b_inv) % c.n
                d_set.add(d_cand)

        total_d_candidates += len(d_set) * cnt  # weighted by shot multiplicity
        total_unique_d += len(d_set)            # per-distinct-triple
        if d_true in d_set:
            shots_with_hit += cnt

        if (idx + 1) % 5000 == 0:
            elapsed = time.time() - t0
            print(f"  {idx+1}/{len(triples)} ({elapsed:.1f}s), avg d_cand={total_unique_d/(idx+1):.1f}")

    n_triples = len(triples)
    n_shots = sum(cnt for _, _, _, cnt in triples)
    avg_d_per_shot = total_unique_d / n_triples
    avg_a = sum(a_sizes) / len(a_sizes)
    avg_b = sum(b_sizes) / len(b_sizes)

    # Uniform-noise prediction: P(hit per shot) = avg_d_per_shot / n
    p_hit_uniform = avg_d_per_shot / c.n
    expected_hits_uniform = p_hit_uniform * n_shots

    print()
    print(f"=== Results (bits={args.bits}, t={t}, candidates_target={args.candidates_target}) ===")
    print(f"shots: {n_shots}")
    print(f"distinct triples: {n_triples}")
    print(f"avg a_candidates/shot: {avg_a:.2f}")
    print(f"avg b_candidates/shot: {avg_b:.2f}")
    print(f"avg distinct d_candidates/shot (C): {avg_d_per_shot:.2f}")
    print(f"n: {c.n}")
    print(f"P(hit per shot) uniform-noise model: {p_hit_uniform:.6e}")
    print(f"expected hits (uniform model): {expected_hits_uniform:.3f}")
    print(f"actual hits: {shots_with_hit}")
    if expected_hits_uniform > 0:
        ratio = shots_with_hit / expected_hits_uniform
        print(f"actual / uniform-prediction: {ratio:.2f}")


if __name__ == "__main__":
    main()
