"""Poll an Azure Quantum (Quantinuum) job until DONE, then decode `d`.

Companion to ``scripts/azure_quantum_submit.py``. Mirrors the IBM
``fetch_result.py`` flow.
"""
from __future__ import annotations

import json
import os
import sys
import time

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import hnp_recover_with_verification
from quantum_ecc import load_azure_credentials
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)

from azure.quantum import Workspace
from azure.quantum.qiskit import AzureQuantumProvider


def _parse_shots(counts: dict[str, int], t: int, pt_w: int, n: int):
    triples = []
    for bs, cnt in counts.items():
        bs2 = bs.replace(" ", "")
        if len(bs2) != 2 * t + pt_w:
            continue
        k = int(bs2[:t], 2) % n
        j = int(bs2[t:2 * t], 2) % n
        r = int(bs2[2 * t:], 2) % n
        for _ in range(cnt):
            triples.append((j, k, r))
    return triples


def _decode_hnp(counts, c, meta):
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    t = meta["t"]
    m = max(1, (c.n - 1).bit_length())
    oracle_kind = meta.get("oracle", "ripple")
    pt_w = m if oracle_kind == "dense" else m + 1
    shots = _parse_shots(counts, t, pt_w, c.n)
    if not shots:
        return {"d_recovered": None, "rank_in_hnp": None,
                "verified_via_anti_d": None, "shots_parsed": 0}
    verify = lambda d: curve.scalar_mul(d, G) == Q
    res = hnp_recover_with_verification(shots, c.n, t, verify,
                                         top_k=meta.get("hnp_top_k", 10))
    return {
        "extractor": "hnp",
        "shots_parsed": len(shots),
        "recovered_d": res["d_recovered"],
        "success": res["d_recovered"] == meta["expected_d"],
        "rank_in_hnp": res["rank_in_hnp"],
        "verified_via_anti_d": res["verified_via_anti_d"],
        "hnp_top_k": res["hnp_top_k"],
    }


def main(pending_path: str) -> int:
    with open(pending_path) as f:
        meta = json.load(f)
    print(f"Polling Azure Quantinuum job {meta['job_id']} on {meta['target']}...")

    creds = load_azure_credentials()
    workspace = Workspace(**creds)
    provider = AzureQuantumProvider(workspace=workspace)
    backend = provider.get_backend(meta["target"])
    job = backend.retrieve_job(meta["job_id"])

    last = None
    while True:
        s = job.status()
        s_name = s.name if hasattr(s, "name") else str(s)
        if s_name != last:
            print(f"  [{time.strftime('%H:%M:%S')}] status={s_name}")
            last = s_name
        if s_name.upper() in ("DONE", "COMPLETED", "FAILED", "CANCELLED", "ERROR"):
            break
        time.sleep(15)

    if s_name.upper() not in ("DONE", "COMPLETED"):
        print(f"Job ended with status {s_name}.")
        return 1

    counts = job.result().get_counts()
    if isinstance(counts, list):  # some Azure backends return list of count dicts
        counts = counts[0]
    print(f"\nGot {sum(counts.values())} shots, {len(counts)} unique outcomes.")

    c = get_challenge(meta["bits"])
    out = _decode_hnp(counts, c, meta)
    flag = "OK" if out["success"] else "FAIL"
    print(f"\nRecovered d = {out['recovered_d']}  (expected {meta['expected_d']})  -> {flag}")
    if out["success"]:
        print(f"  rank_in_hnp        : {out['rank_in_hnp']}")
        print(f"  verified_via_anti_d: {out['verified_via_anti_d']}")

    os.makedirs("results", exist_ok=True)
    # First 8 chars of job_id are the per-job UUID head (unique).
    # See azure_quantum_submit.py for the same convention.
    jid_suffix = meta["job_id"][:8].replace("/", "_")
    out_path = (
        f"results/shor_azure_{meta['bits']}bit_t{meta['t']}_"
        f"{meta['shots']}shots_{meta['target']}_{jid_suffix}.json"
    )
    with open(out_path, "w") as f:
        json.dump({**meta, **out, "unique_outcomes": len(counts),
                   "counts": counts}, f, indent=2)
    print(f"Saved → {out_path}")
    return 0 if out["success"] else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/azure_quantum_fetch.py <pending_metadata.json>")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
