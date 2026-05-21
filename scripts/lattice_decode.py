"""
Run the HNP lattice post-processor (``src/lattice_postprocess``) on a saved
counts file. Reports the recovered ``d`` and compares to the expected value.

This is the D-1 driver. Validate first on noiseless small-``m`` Aer data
(where direct extraction already barely works), then push to the real-
hardware datasets to see if the lattice extracts signal that the per-shot
extractor misses.

Usage:
    python scripts/lattice_decode.py --counts results/_ibm_22bit_t12_counts.json --bits 22
    python scripts/lattice_decode.py --counts results/_ibm_19bit_t12_counts.json --bits 19 --max-shots 64
"""
from __future__ import annotations

import argparse
import json
import math

from challenges import get_challenge
from lattice_postprocess import hnp_recover


def parse_triples(counts: dict[str, int], t: int, pt_w: int, n: int):
    triples = []
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k = int(bs[:t], 2) % n
        j = int(bs[t:2 * t], 2) % n
        r = int(bs[2 * t:], 2) % n
        for _ in range(cnt):
            triples.append((j, k, r))
    return triples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", required=True)
    ap.add_argument("--bits", type=int, required=True)
    ap.add_argument("--pt-w", type=int, default=None)
    ap.add_argument("--max-shots", type=int, default=128)
    ap.add_argument("--block-size", type=int, default=20,
                    help="BKZ block size (2 = LLL only)")
    args = ap.parse_args()

    blob = json.load(open(args.counts))
    counts = blob["counts"]
    meta = blob["meta"]
    c = get_challenge(args.bits)
    n = c.n
    d_true = c.expected_d
    m = (n - 1).bit_length()
    t = meta.get("t") or (len(next(iter(counts))) - (m + 1)) // 2
    pt_w = args.pt_w if args.pt_w is not None else m + 1

    print(f"=== HNP lattice decode on {args.counts} ===")
    print(f"  bits={args.bits}  m={m}  n={n:,}  t={t}  pt_w={pt_w}")
    print(f"  d_true (per metadata): {d_true:,}")

    triples = parse_triples(counts, t, pt_w, n)
    print(f"  parsed {len(triples):,} shots (expanded with multiplicity)")

    result = hnp_recover(triples, n, t,
                          max_shots=args.max_shots,
                          block_size=args.block_size,
                          expected_d=d_true)

    print()
    print(f"  recovered d : {result.d_candidate:,}")
    print(f"  matches d_true: {'YES' if result.d_candidate == d_true else 'NO'}")
    print(f"  confidence  : {result.confidence:.3f}")
    print(f"  short ||v|| : {result.short_vector_norm:.3e}")
    print(f"  used shots  : {result.used_shots}")


if __name__ == "__main__":
    main()
