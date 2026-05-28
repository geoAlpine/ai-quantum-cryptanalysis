"""Poll an IBM job until DONE, then decode ``d`` via the extractor named in
the pending-metadata file.

Two extraction modes:

  - ``extractor: "v3"`` (default for legacy submissions): the
    verification-filter CF-Lift pipeline implemented inside
    ``ShorECDLPSolver.extract``. Used for our 19-bit / 22-bit headline
    results — recovers ``d`` whenever it appears in any per-shot
    candidate set, which is dominated by uniform-noise statistics on
    NISQ hardware.

  - ``extractor: "hnp"``: collective-signal recovery via
    ``hnp_recover_with_verification`` from ``lattice_postprocess``.
    Scores every ``d ∈ [0, n)`` against the joint (j, k) Shor peak
    relation; the top-K (and each top candidate's anti-d partner
    ``(n - d) % n``) are verified directly. Returns the first ``d``
    that passes ``d · G == Q``. This is the production path for the
    "true world record" track and the iterative / dense low-m
    submissions where ``n`` is small enough for exhaustive HNP search.
"""
from __future__ import annotations

import json
import os
import sys
import time

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import hnp_recover_with_verification
from quantum_ecc import load_token
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)
from qiskit_ibm_runtime import QiskitRuntimeService


def _parse_shots(counts: dict[str, int], t: int, pt_w: int, n: int):
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


def _decode_v3(counts, c, meta):
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    lazy = c.n >= 5_000_000
    ind = SubgroupIndexer(curve, G, c.n, lazy=lazy)
    oracle_kind = meta.get("oracle", "ripple")
    oracle = DenseUnitaryOracle(ind) if oracle_kind == "dense" else RippleCarryOracle(ind)
    solver = ShorECDLPSolver(
        curve, G, Q, c.n,
        oracle=oracle,
        num_counting=meta["t"],
        lazy=lazy,
    )
    cf_window = meta.get("cf_window", 32)
    d = solver.extract(counts, cf_window=cf_window)
    return {
        "extractor": "v3",
        "cf_window": cf_window,
        "recovered_d": d,
        "success": d == meta["expected_d"],
    }


def _decode_hnp(counts, c, meta):
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    t = meta["t"]
    m = max(1, (c.n - 1).bit_length())
    oracle_kind = meta.get("oracle", "dense" if m <= 6 else "ripple")
    pt_w = m if oracle_kind == "dense" else m + 1
    shots = _parse_shots(counts, t, pt_w, c.n)

    def verify(d: int) -> bool:
        return curve.scalar_mul(d, G) == Q

    top_k = meta.get("hnp_top_k", 10)
    result = hnp_recover_with_verification(
        shots, c.n, t, verify, top_k=top_k,
    )
    return {
        "extractor": "hnp",
        "hnp_top_k": top_k,
        "hnp_top_k_scores": result["hnp_top_k"],
        "rank_in_hnp": result["rank_in_hnp"],
        "verified_via_anti_d": result["verified_via_anti_d"],
        "recovered_d": result["d_recovered"],
        "success": result["d_recovered"] == meta["expected_d"],
        "elapsed_seconds": result["elapsed_seconds"],
    }


def main(pending_path: str) -> int:
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
        return 1

    counts = job.result()[0].data.cr.get_counts()
    print(f"\nGot {sum(counts.values())} shots, {len(counts)} unique outcomes.")

    c = get_challenge(meta["bits"])
    extractor = meta.get("extractor", "v3")
    print(f"Decoding with extractor = {extractor!r}")
    if extractor == "hnp":
        out = _decode_hnp(counts, c, meta)
    else:
        out = _decode_v3(counts, c, meta)

    flag = "OK" if out["success"] else "FAIL"
    print(f"\nRecovered d = {out['recovered_d']}  (expected {meta['expected_d']})  -> {flag}")
    if extractor == "hnp":
        print(f"  rank in HNP top-K : {out['rank_in_hnp']}")
        print(f"  via anti-d partner: {out['verified_via_anti_d']}")
        print(f"  decode time       : {out['elapsed_seconds']:.1f}s")

    os.makedirs("results", exist_ok=True)
    # Include backend + job_id suffix so multiple trials of the same
    # (bits, t, shots, extractor) don't overwrite each other. Legacy
    # callers can pass --legacy-path to keep the old name.
    base = f"results/shor_{meta['bits']}bit_t{meta['t']}_{meta['shots']}shots"
    ext_suffix = "_hnp" if extractor == "hnp" else ""
    backend = meta.get("backend", "unknown")
    jid_suffix = meta["job_id"][-8:]
    out_path = f"{base}{ext_suffix}_{backend}_{jid_suffix}.json"
    with open(out_path, "w") as f:
        json.dump({
            **meta,
            **out,
            "unique_outcomes": len(counts),
            "counts": counts,
        }, f, indent=2)
    print(f"Saved → {out_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/fetch_result.py <pending_metadata.json>")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
