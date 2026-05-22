"""
Offline decoder: run the same HNP+verify pipeline as ``fetch_result.py``
but on a counts file that's already on disk (no IBM polling).

Use to:
  - Re-decode a saved job's counts with different parameters.
  - End-to-end exercise the decode path without spending QPU.
  - Sanity-check a noisy-preview output.

Usage:
    python scripts/decode_offline.py \\
        --counts results/_ibm_4bit_counts.json \\
        --bits 4 --t 3 --oracle dense --extractor hnp --top-k 7
"""
from __future__ import annotations

import argparse
import json
import time

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import hnp_recover_with_verification, hnp_score
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)


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
                    help="counts file (saved IBM blob with 'counts' or raw dict)")
    ap.add_argument("--bits", type=int, required=True)
    ap.add_argument("--t", type=int, required=True)
    ap.add_argument("--oracle", choices=["dense", "ripple"], default="dense")
    ap.add_argument("--extractor", choices=["v3", "hnp"], default="hnp")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--cf-window", type=int, default=16,
                    help="v3 cf_window (only used when --extractor v3)")
    args = ap.parse_args()

    blob = json.load(open(args.counts))
    counts = blob.get("counts", blob)
    c = get_challenge(args.bits)
    n = c.n
    d_true = c.expected_d
    m = max(1, (n - 1).bit_length())
    pt_w = m if args.oracle == "dense" else m + 1

    print(f"=== offline decode ===")
    print(f"  file = {args.counts}")
    print(f"  bits = {args.bits}  n = {n}  d_true = {d_true}  t = {args.t}  "
          f"oracle = {args.oracle}  pt_w = {pt_w}")
    print(f"  extractor = {args.extractor}, top_k = {args.top_k}")
    print(f"  total shots = {sum(counts.values()):,}  unique = {len(counts):,}")
    print()

    if args.extractor == "hnp":
        shots = parse_shots(counts, args.t, pt_w, n)
        curve = EllipticCurve(0, 7, c.p)
        G = curve.point(*c.G)
        Q = curve.point(*c.Q)

        def verify(d):
            return curve.scalar_mul(d, G) == Q

        t0 = time.time()
        result = hnp_recover_with_verification(shots, n, args.t, verify,
                                                 top_k=args.top_k)
        elapsed = time.time() - t0

        print(f"=== HNP recovery ===")
        if result["d_recovered"] is not None:
            ok = result["d_recovered"] == d_true
            print(f"  ✓ recovered d = {result['d_recovered']}  "
                  f"(d_true = {d_true}, match = {ok})")
            print(f"    HNP rank   : {result['rank_in_hnp']}")
            print(f"    via anti-d : {result['verified_via_anti_d']}")
        else:
            print(f"  ✗ no candidate verified within top-{args.top_k}")
        print(f"  decode time   : {elapsed:.2f}s")
        print(f"  top-{min(args.top_k, n)} candidates:")
        for d, s in result["hnp_top_k"][:args.top_k]:
            mark = "  <-- d_true" if d == d_true else (
                "  (anti-d_true)" if d == (n - d_true) % n else ""
            )
            print(f"    d = {d:<6}  score = {s:.4f}{mark}")
    else:
        # v3 path: build full solver
        curve = EllipticCurve(0, 7, c.p)
        G = curve.point(*c.G)
        Q = curve.point(*c.Q)
        lazy = c.n >= 5_000_000
        ind = SubgroupIndexer(curve, G, c.n, lazy=lazy)
        oracle = (DenseUnitaryOracle(ind) if args.oracle == "dense"
                  else RippleCarryOracle(ind))
        solver = ShorECDLPSolver(curve, G, Q, c.n, oracle=oracle,
                                  num_counting=args.t, lazy=lazy)
        d = solver.extract(counts, cf_window=args.cf_window)
        ok = d == d_true
        print(f"=== v3 extract ===")
        print(f"  recovered d = {d}  (d_true = {d_true}, match = {ok})")


if __name__ == "__main__":
    main()
