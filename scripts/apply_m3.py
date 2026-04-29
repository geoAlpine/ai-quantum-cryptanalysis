"""
Apply M3 (Matrix-free Measurement Mitigation) to existing IBM 4-bit Shor counts.

Compares raw vs mitigated success probability and unique-outcome distribution.
Uses the IBM backend that produced the original job to fetch its readout error matrix.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mthree
from challenges import get_challenge
from ecc import EllipticCurve
from quantum_ecc import load_token
from shor_ecdlp import ShorECDLPSolver
from qiskit_ibm_runtime import QiskitRuntimeService


def main():
    raw_path = "results/_ibm_4bit_counts.json"
    with open(raw_path) as f:
        data = json.load(f)
    counts = {k: v for k, v in data["counts"].items()}
    meta = data["meta"]
    print(f"Loaded {sum(counts.values())} shots from {raw_path}")
    print(f"Backend: {meta['backend']},  job_id: {meta['job_id']}")

    c = get_challenge(meta["bits"])
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    solver = ShorECDLPSolver(curve, G, Q, c.n)

    n_bits = len(next(iter(counts)))
    qubits = list(range(n_bits))

    svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())
    backend = svc.backend(meta["backend"])

    print("Calibrating M3 readout matrix on backend...")
    mit = mthree.M3Mitigation(backend)
    mit.cals_from_system(qubits)

    print("Applying M3 mitigation...")
    quasi = mit.apply_correction(counts, qubits)
    # Convert quasi-probabilities back to integer counts (clamp negatives, normalize)
    total = sum(counts.values())
    pos = {k: max(0.0, v) for k, v in quasi.items()}
    s = sum(pos.values()) or 1.0
    mitigated = {k: int(round(v / s * total)) for k, v in pos.items() if v > 0}

    print()
    print("=" * 60)
    print(f"  Raw counts  : {len(counts)} unique outcomes")
    d_raw = solver.extract(counts)
    print(f"    recovered d = {d_raw}  (expected {c.expected_d})")
    print(f"    success     : {'YES' if d_raw == c.expected_d else 'NO'}")
    print()
    print(f"  M3 mitigated: {len(mitigated)} unique outcomes")
    d_mit = solver.extract(mitigated)
    print(f"    recovered d = {d_mit}  (expected {c.expected_d})")
    print(f"    success     : {'YES' if d_mit == c.expected_d else 'NO'}")
    print("=" * 60)

    # Vote-strength comparison: how many shots support each candidate
    def candidate_support(cnts):
        votes = {}
        for bs, cnt in cnts.items():
            t = (len(bs) - 3) // 2  # 4-bit n=7 → m=3, pt_w=3
            if len(bs) != 2 * t + 3:
                continue
            k_b, j_b, pt_b = bs[:t], bs[t:2*t], bs[2*t:]
            j = int(j_b, 2) % c.n
            k = int(k_b, 2) % c.n
            r = int(pt_b, 2) % c.n
            if k == 0 or math.gcd(k, c.n) != 1:
                continue
            d_cand = ((r - j) * pow(k, -1, c.n)) % c.n
            if curve.scalar_mul(d_cand, G) == Q:
                votes[d_cand] = votes.get(d_cand, 0) + cnt
        return votes

    raw_votes = candidate_support(counts)
    mit_votes = candidate_support(mitigated)
    print(f"\n  Vote support for true d={c.expected_d}:")
    print(f"    raw : {raw_votes.get(c.expected_d, 0)} shots ({raw_votes.get(c.expected_d, 0)*100/total:.1f}%)")
    print(f"    M3  : {mit_votes.get(c.expected_d, 0)} shots ({mit_votes.get(c.expected_d, 0)*100/total:.1f}%)")
    print(f"  Total verified candidates:")
    print(f"    raw : {sum(raw_votes.values())} shots → {len(raw_votes)} unique d")
    print(f"    M3  : {sum(mit_votes.values())} shots → {len(mit_votes)} unique d")

    # Save mitigated result
    out_path = raw_path.replace("_pending_4bit_ibm.json", "shor_4bit_4096shots_ibm_m3.json").replace("_ibm_4bit_counts", "shor_4bit_4096shots_ibm_m3")
    with open(out_path, "w") as f:
        json.dump({
            "mode": "shor_m3", "bit_length": c.bit_length,
            "expected_d": c.expected_d,
            "raw": {"recovered_d": d_raw, "vote_support_correct": raw_votes.get(c.expected_d, 0),
                    "total_verified_shots": sum(raw_votes.values()), "n_unique_candidates": len(raw_votes)},
            "m3":  {"recovered_d": d_mit, "vote_support_correct": mit_votes.get(c.expected_d, 0),
                    "total_verified_shots": sum(mit_votes.values()), "n_unique_candidates": len(mit_votes)},
            "backend": meta["backend"], "job_id": meta["job_id"], "shots": total,
        }, f, indent=2)
    print(f"\n  Saved → {out_path}")


if __name__ == "__main__":
    main()
