"""
Replay-mode regression benchmark for the d-extractor.

Runs the current ShorECDLPSolver.extract() against every saved IBM-hardware
counts file and reports pass/fail. Costs zero QPU — pure post-processing
over previously-collected shots.

Use as a fast sanity check after touching:
  - src/shor_ecdlp.py (extractor)
  - scripts/cflift_v3.py (CF-lift candidate generation)
  - the SubgroupIndexer or oracle width logic

Default scans results/_ibm_*_counts.json. Add new datasets by saving them
under that pattern with a `meta` block containing at least `bits` and
`expected_d`. `t` is inferred from bitstring length when missing.

Usage:
    python scripts/replay_benchmark.py
    python scripts/replay_benchmark.py --cf-window 32
    python scripts/replay_benchmark.py --only 22
    python scripts/replay_benchmark.py --files results/_ibm_22bit_t12_counts.json
"""

import argparse
import glob
import json
import os
import sys
import time

from challenges import get_challenge
from ecc import EllipticCurve
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)


def infer_t(bs_len: int, bits: int, oracle_kind: str) -> int:
    """t derives from bs_len = 2t + pt_w. Dense pt_w=m, ripple pt_w=m+1."""
    from challenges import get_challenge
    n = get_challenge(bits).n
    m = max(1, (n - 1).bit_length())
    pt_w = m if oracle_kind == "dense" else m + 1
    rem = bs_len - pt_w
    if rem <= 0 or rem % 2:
        raise ValueError(
            f"can't infer t for bits={bits} oracle={oracle_kind} bs_len={bs_len}"
        )
    return rem // 2


def detect_oracle(bs_len: int, bits: int) -> str:
    """Pick oracle by which pt_w (m or m+1) makes 2t+pt_w match bs_len."""
    from challenges import get_challenge
    n = get_challenge(bits).n
    m = max(1, (n - 1).bit_length())
    for kind, pt_w in (("ripple", m + 1), ("dense", m)):
        rem = bs_len - pt_w
        if rem > 0 and rem % 2 == 0:
            return kind
    raise ValueError(f"no oracle matches bs_len={bs_len} for bits={bits}")


def replay_one(path: str, cf_window: int, cf_version: str, sample: int = 0):
    blob = json.load(open(path))
    counts = blob["counts"]
    meta = blob["meta"]
    bits = meta["bits"]
    expected_d = meta["expected_d"]
    shots = meta.get("shots", sum(counts.values()))

    bs_len = len(next(iter(counts)))
    oracle_kind = detect_oracle(bs_len, bits)
    t = meta.get("t") or infer_t(bs_len, bits, oracle_kind)

    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    lazy = c.n >= 5_000_000
    ind = SubgroupIndexer(curve, G, c.n, lazy=lazy)
    oracle = (DenseUnitaryOracle(ind) if oracle_kind == "dense"
              else RippleCarryOracle(ind))
    solver = ShorECDLPSolver(curve, G, Q, c.n, oracle=oracle,
                             num_counting=t, lazy=lazy)

    if sample and sample < shots:
        # Down-sample shots proportionally for speed.
        import random
        random.seed(42)
        keep = sample
        flat = [(bs, c) for bs, c in counts.items() for _ in range(c)]
        random.shuffle(flat)
        sub: dict[str, int] = {}
        for bs, _ in flat[:keep]:
            sub[bs] = sub.get(bs, 0) + 1
        counts = sub

    t0 = time.time()
    d = solver.extract(counts, cf_window=cf_window, cf_version=cf_version)
    dt = time.time() - t0

    return {
        "file": os.path.basename(path),
        "bits": bits,
        "oracle": oracle_kind,
        "t": t,
        "shots": sum(counts.values()),
        "expected_d": expected_d,
        "recovered_d": d,
        "success": d == expected_d,
        "extract_sec": dt,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="+",
                    help="Specific counts files (default: results/_ibm_*_counts.json)")
    ap.add_argument("--only", type=int, default=0,
                    help="Filter to a single bit-size (e.g. 22)")
    ap.add_argument("--cf-window", type=int, default=16)
    ap.add_argument("--cf-version", default="v3", choices=["v2", "v3"])
    ap.add_argument("--sample", type=int, default=0,
                    help="Down-sample to N shots per file (0 = all)")
    args = ap.parse_args()

    if args.files:
        paths = args.files
    else:
        paths = sorted(glob.glob("results/_ibm_*_counts.json"))

    if args.only:
        paths = [p for p in paths if f"_{args.only}bit" in os.path.basename(p)]

    if not paths:
        print("No matching counts files.")
        return 1

    print(f"=== Extractor replay ({len(paths)} files, "
          f"cf_version={args.cf_version}, cf_window={args.cf_window}"
          f"{', sample=' + str(args.sample) if args.sample else ''}) ===\n")
    print(f"{'file':<38} {'bits':<5} {'oracle':<7} {'t':<3} "
          f"{'shots':<7} {'recovered':<12} {'expected':<12} {'sec':<6} ok")
    print("-" * 110)

    n_pass, n_fail = 0, 0
    for p in paths:
        try:
            r = replay_one(p, args.cf_window, args.cf_version, args.sample)
        except Exception as e:
            print(f"{os.path.basename(p):<38} ERROR: {type(e).__name__}: {e}")
            n_fail += 1
            continue
        flag = "OK" if r["success"] else "FAIL"
        n_pass += int(r["success"])
        n_fail += int(not r["success"])
        print(f"{r['file']:<38} {r['bits']:<5} {r['oracle']:<7} {r['t']:<3} "
              f"{r['shots']:<7} {str(r['recovered_d']):<12} "
              f"{str(r['expected_d']):<12} {r['extract_sec']:<6.1f} {flag}")

    print(f"\nResult: {n_pass}/{n_pass + n_fail} passed")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
