"""
Unit tests for RippleCarryOracle controlled modular addition.

Verifies that `controlled_add(c)` implements:

    |ctrl⟩|acc⟩|0...0⟩  →  |ctrl⟩|(acc + c·ctrl) mod n⟩|0...0⟩

with all ancilla qubits (flag, anc, cout, helper) restored to |0⟩.

Run:
    python tests/test_ripple_oracle.py

Notes
-----
The 22-bit hardware recovery does NOT prove this oracle is correct: the
verification filter `d_cand·G == Q` will accept the right d as long as the
right (j, k, r) triples appear ANYWHERE in the count distribution, even
under a buggy oracle. So a direct correctness check on small instances
is the only way to validate the modular-add construction.
"""

from __future__ import annotations

import os
import random

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

from challenges import get_challenge
from ecc import EllipticCurve
from shor_ecdlp import RippleCarryOracle, SubgroupIndexer


def make_oracle(challenge_bits: int) -> RippleCarryOracle:
    c = get_challenge(challenge_bits)
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    return RippleCarryOracle(SubgroupIndexer(curve, G, c.n))


def expected_state_index(ctrl: int, acc: int) -> int:
    """All ancillas = 0 → state index = ctrl + 2·acc (Qiskit little-endian:
    qubit 0 = ctrl as basis-bit 0, qubits 1..m1 = acc as basis-bits 1..m1)."""
    return ctrl | (acc << 1)


def run_oracle(oracle: RippleCarryOracle, ctrl: int, acc: int, c_val: int) -> Statevector:
    m1 = oracle.m1
    nq = 2 * m1 + 4
    qc = QuantumCircuit(nq)
    if ctrl:
        qc.x(0)
    for i in range(m1):
        if (acc >> i) & 1:
            qc.x(1 + i)
    qc.append(oracle.controlled_add(c_val), range(nq))
    return Statevector.from_instruction(qc)


def assert_correct(oracle: RippleCarryOracle, ctrl: int, acc: int, c_val: int) -> None:
    n = oracle.n
    sv = run_oracle(oracle, ctrl, acc, c_val)
    expected_acc = (acc + c_val) % n if ctrl == 1 else acc
    expected_idx = expected_state_index(ctrl, expected_acc)
    probs = np.abs(sv.data) ** 2
    top_idx = int(np.argmax(probs))
    top_prob = float(probs[top_idx])
    if top_idx != expected_idx or top_prob < 0.999:
        nz = sorted(
            ((i, p) for i, p in enumerate(probs) if p > 1e-6),
            key=lambda x: -x[1],
        )
        raise AssertionError(
            f"ctrl={ctrl} acc={acc} c={c_val} (n={n}, m1={oracle.m1}):\n"
            f"  expected basis index {expected_idx} "
            f"(acc'={expected_acc}, all ancilla=0)\n"
            f"  got      basis index {top_idx}  prob={top_prob:.4f}\n"
            f"  top nonzero states: {nz[:6]}"
        )


def test_4bit_exhaustive() -> None:
    """n=7, m1=4 → 12 qubits. Full coverage: 2 × 7 × 7 = 98 trials."""
    oracle = make_oracle(4)
    n = oracle.n  # 7
    print(f"  test_4bit_exhaustive: n={n}, m1={oracle.m1}, qubits={2 * oracle.m1 + 4}")
    trials = 0
    for ctrl in (0, 1):
        for acc in range(n):
            for c_val in range(n):
                assert_correct(oracle, ctrl, acc, c_val)
                trials += 1
    print(f"    OK  {trials} trials passed")


def test_6bit_spot() -> None:
    """n=31, m1=6 → 16 qubits. Boundary + random sample (full would be ~2K trials)."""
    oracle = make_oracle(6)
    n = oracle.n  # 31
    print(f"  test_6bit_spot:       n={n}, m1={oracle.m1}, qubits={2 * oracle.m1 + 4}")
    boundaries = [
        (1, 0, 0),                # c=0 identity
        (1, 0, 1),                # +1
        (1, n - 1, 1),            # wrap exactly
        (1, n - 1, n - 1),        # large + large, wraps
        (1, n // 2, n // 2),      # middle
        (0, n - 1, n - 1),        # ctrl=0, large values, must be no-op
        (0, 0, n // 2),           # ctrl=0, c≠0, must be no-op
    ]
    rng = random.Random(0)
    samples = [
        (rng.randint(0, 1), rng.randint(0, n - 1), rng.randint(0, n - 1))
        for _ in range(40)
    ]
    trials = 0
    for ctrl, acc, c_val in boundaries + samples:
        assert_correct(oracle, ctrl, acc, c_val)
        trials += 1
    print(f"    OK  {trials} trials passed")


if __name__ == "__main__":
    print("RippleCarryOracle correctness tests")
    test_4bit_exhaustive()
    test_6bit_spot()
    print("\nAll tests passed.")
