"""
Tensor-network simulation of small-scale Shor ECDLP via Quimb.

Cross-validation tool for our Qiskit Aer + IBM Quantum results. Produces an
independent third reference point on circuit correctness, particularly useful
because Quimb uses tensor-network contraction (not full statevector) and so
provides a sanity check via a different computational pathway.

Limited to dense oracle for n_bits ≤ 6 due to 2^(m+1)×2^(m+1) matrix size in
the controlled-add unitary. Larger problems would require porting our ripple-carry
oracle to Quimb directly (open work item).

Usage:
    python scripts/quimb_simulate.py --bits 4 --t 3 --shots 4096
    python scripts/quimb_simulate.py --bits 6 --t 5 --shots 2048
"""

import argparse
import math
import os
import sys

import numpy as np
import quimb.tensor as qtn

from challenges import get_challenge
from ecc import EllipticCurve


def build_subgroup_index(curve, G_pt, n):
    elements = [curve.infinity]
    cur = G_pt
    for _ in range(1, n):
        elements.append(cur)
        cur = curve.add(cur, G_pt)

    def idx_of(P):
        if P.is_infinity:
            return 0
        for i, E in enumerate(elements):
            if not E.is_infinity and (E.x, E.y) == (P.x, P.y):
                return i
        return 0

    return idx_of


def build_dense_controlled_add(c_val: int, n: int, m: int) -> np.ndarray:
    """Build (m+1)-qubit controlled-add gate as a 2*N × 2*N matrix.

    Quimb apply_gate_raw convention: qubit at index 0 is MSB of basis index.
    State index = ctrl * 2^m + pt_value.
    Returns matrix reshaped to a (2,)*(2*(m+1)) tensor.
    """
    dim = 1 << m
    perm = np.arange(dim)
    for i in range(n):
        perm[i] = (i + c_val) % n
    total = 2 * dim
    U = np.zeros((total, total), dtype=complex)
    for pt in range(dim):
        U[pt, pt] = 1.0  # ctrl=0 → identity
        U[dim + perm[pt], dim + pt] = 1.0  # ctrl=1 → permute
    return U.reshape([2] * (2 * (m + 1)))


def inverse_qft(qc: qtn.Circuit, qubits: list[int]) -> None:
    """Standard inverse QFT on the given qubits, MSB convention."""
    nq_ = len(qubits)
    for i in range(nq_ // 2):
        qc.swap(qubits[i], qubits[nq_ - 1 - i])
    for j in range(nq_):
        for k in range(j):
            qc.cu1(-math.pi / (2 ** (j - k)), qubits[k], qubits[j])
        qc.h(qubits[j])


def build_shor_circuit(curve, G_pt, Q_pt, n: int, t: int) -> qtn.Circuit:
    m = max(1, (n - 1).bit_length())
    idx_of = build_subgroup_index(curve, G_pt, n)
    pt_qubits = list(range(2 * t, 2 * t + m))

    qc = qtn.Circuit(2 * t + m)
    for i in range(t):
        qc.h(i)
        qc.h(t + i)

    G_pow = G_pt
    for i in range(t):
        if not G_pow.is_infinity:
            idx = idx_of(G_pow)
            if idx != 0:
                gate = build_dense_controlled_add(idx, n, m)
                qc.apply_gate_raw(gate, [i] + pt_qubits)
        G_pow = curve.add(G_pow, G_pow)

    Q_pow = Q_pt
    for i in range(t):
        if not Q_pow.is_infinity:
            idx = idx_of(Q_pow)
            if idx != 0:
                gate = build_dense_controlled_add(idx, n, m)
                qc.apply_gate_raw(gate, [t + i] + pt_qubits)
        Q_pow = curve.add(Q_pow, Q_pow)

    inverse_qft(qc, list(range(t)))
    inverse_qft(qc, list(range(t, 2 * t)))
    return qc


def extract_d(qc: qtn.Circuit, n: int, t: int, m: int, curve, G_pt, Q_pt,
              shots: int):
    hits = 0
    candidates: dict[int, int] = {}
    for sample in qc.sample(shots):
        bs = "".join(str(int(b)) for b in sample)
        j = int(bs[0:t], 2)
        k = int(bs[t:2 * t], 2)
        r = int(bs[2 * t:], 2) % n
        if k == 0 or math.gcd(k, n) != 1:
            continue
        d_cand = ((r - j) * pow(k, -1, n)) % n
        if curve.scalar_mul(d_cand, G_pt) == Q_pt:
            hits += 1
            candidates[d_cand] = candidates.get(d_cand, 0) + 1
    return hits, candidates


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bits", type=int, default=4)
    p.add_argument("--t", type=int, default=None,
                   help="Counting register width (default: m)")
    p.add_argument("--shots", type=int, default=4096)
    args = p.parse_args()

    c = get_challenge(args.bits)
    curve = EllipticCurve(0, 7, c.p)
    G_pt = curve.point(*c.G)
    Q_pt = curve.point(*c.Q)
    n = c.n
    m = max(1, (n - 1).bit_length())
    t = args.t if args.t is not None else m

    if m > 6:
        print(f"WARNING: dense oracle becomes very large for m={m}.")
        print(f"This script supports n_bits ≤ 6 cleanly. Try smaller --bits.")
        return

    print(f"=== Quimb Shor (tensor-network, noiseless) ===")
    print(f"  challenge bits = {args.bits}, n = {n}, m = {m}, t = {t}")
    print(f"  expected d = {c.expected_d}")

    qc = build_shor_circuit(curve, G_pt, Q_pt, n, t)
    print(f"  circuit: {qc.N} qubits, {qc.num_gates} gates")

    print(f"\n  sampling {args.shots} shots...")
    hits, candidates = extract_d(qc, n, t, m, curve, G_pt, Q_pt, args.shots)

    print(f"\n  verified hits: {hits}/{args.shots} ({100 * hits / args.shots:.1f}%)")
    if candidates:
        top = max(candidates.items(), key=lambda x: x[1])
        ok = "✓" if top[0] == c.expected_d else "✗"
        print(f"  recovered d = {top[0]} ({top[1]} votes) {ok}")
    else:
        print(f"  no verified candidates")


if __name__ == "__main__":
    main()
