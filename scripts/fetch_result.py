"""Poll an IBM job until DONE and extract d using the Shor solver."""

import json
import os
import sys
import time

from challenges import get_challenge
from ecc import EllipticCurve
from quantum_ecc import load_token
from shor_ecdlp import ShorECDLPSolver, RippleCarryOracle, SubgroupIndexer
from qiskit_ibm_runtime import QiskitRuntimeService


def main(pending_path: str):
    with open(pending_path) as f:
        meta = json.load(f)
    print(f"Polling {meta['job_id']} on {meta['backend']}...")

    svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())
    job = svc.job(meta["job_id"])
    last = None
    while True:
        s = job.status()
        if s != last:
            print(f"  [{time.strftime('%H:%M:%S')}] status={s}")
            last = s
        if s in ("DONE", "CANCELLED", "ERROR"):
            break
        time.sleep(15)

    if s != "DONE":
        print(f"Job ended with status {s}.")
        return

    counts = job.result()[0].data.cr.get_counts()
    print(f"\nGot {sum(counts.values())} shots, {len(counts)} unique outcomes.")

    c = get_challenge(meta["bits"])
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    # Use lazy indexer for large subgroups (≥ ~10^6 elements would be slow to enumerate).
    lazy = c.n >= 5_000_000
    ind = SubgroupIndexer(curve, G, c.n, lazy=lazy)
    solver = ShorECDLPSolver(curve, G, Q, c.n,
                             oracle=RippleCarryOracle(ind),
                             num_counting=meta["t"],
                             lazy=lazy)

    cf_window = meta.get("cf_window", 32)
    d = solver.extract(counts, cf_window=cf_window)
    print(f"\nRecovered d = {d}  (expected {meta['expected_d']})  "
          f"-> {'OK' if d == meta['expected_d'] else 'FAIL'}  "
          f"[extractor cf_window={cf_window}]")

    out_path = f"results/shor_{meta['bits']}bit_t{meta['t']}_{meta['shots']}shots_ibm.json"
    with open(out_path, "w") as f:
        json.dump({
            **meta,
            "recovered_d": d,
            "success": d == meta["expected_d"],
            "unique_outcomes": len(counts),
            "counts": counts,
        }, f, indent=2)
    print(f"Saved → {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/fetch_result.py <pending_metadata.json>")
        sys.exit(1)
    main(sys.argv[1])
