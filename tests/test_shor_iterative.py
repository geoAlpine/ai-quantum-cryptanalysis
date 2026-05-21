"""Smoke tests for the iterative (semiclassical) Shor-ECDLP solver.

The iterative variant trades multi-qubit counting registers for one
recycled qubit each plus mid-circuit measurement + classical feed-
forward. These tests pin the *structural* properties (qubit savings,
circuit construction does not error) and the noiseless-Aer *recovery*
property at the smallest feasible m.

The Aer-recovery test in particular pins the **2026-05-22 finding**:
at n=7 t=6 the iterative version recovers ``d_true`` as the HNP score
argmax (rank 1), whereas the standard two-register variant only
recovers ``-d_true`` at rank 1 and ``d_true`` at rank 2 — the
iterative + classical-feedback structure breaks the modular d ↔ -d
symmetry. If that property regresses, this test screams.
"""
from __future__ import annotations

import pytest

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import hnp_score_search
from shor_iterative import IterativeShorECDLPSolver


def test_iterative_solver_construction_4bit():
    """Building the m=3 iterative circuit must not error and must
    produce the documented qubit savings."""
    c = get_challenge(4)
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    solver = IterativeShorECDLPSolver(curve, G, Q, c.n,
                                        num_counting=6,
                                        max_corrections=None)
    plan = solver.plan()
    assert plan.m == 3
    assert plan.t == 6
    assert plan.total_qubits == 13
    assert plan.standard_total_qubits == 23
    assert plan.qubit_savings == 10
    qc = solver.build_circuit()
    # Sanity: 2 + pt_w + ancilla = 13.
    assert qc.num_qubits == 13
    # 2 * num_counting + pt_w bits to measure into.
    assert qc.num_clbits == 2 * 6 + plan.point_register_width


@pytest.mark.slow
def test_iterative_recovers_d_true_noiseless_4bit():
    """Pin the 2026-05-22 finding: n=7 t=6 iterative + HNP yields
    d_true rank 1 (not d_true=-rank as the standard variant does).

    Marked slow because the dynamic-circuit Aer sim is ~2 min."""
    from qiskit import transpile
    from qiskit_aer import AerSimulator

    c = get_challenge(4)
    n = c.n
    d_true = c.expected_d
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    solver = IterativeShorECDLPSolver(curve, G, Q, n,
                                        num_counting=6,
                                        max_corrections=None)
    qc = solver.build_circuit()
    sim = AerSimulator()
    qc_t = transpile(qc, sim, optimization_level=0)
    counts = sim.run(qc_t, shots=2048).result().get_counts()

    t = solver.num_counting
    pt_w = solver.oracle.point_register_width()
    shots: list[tuple[int, int, int]] = []
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k = int(bs[:t], 2) % n
        j = int(bs[t:2 * t], 2) % n
        r = int(bs[2 * t:], 2) % n
        for _ in range(cnt):
            shots.append((j, k, r))
    assert len(shots) > 1000

    result = hnp_score_search(shots, n, t, expected_d=d_true)
    # The major property: argmax IS d_true. If this regresses to
    # picking n - d_true, the iterative variant has lost the
    # symmetry-breaking property and we want to know immediately.
    assert result["d_recovered"] == d_true, (
        f"iterative+HNP recovered d={result['d_recovered']} "
        f"(expected {d_true}); regression in the symmetry-breaking "
        f"property — re-investigate."
    )
    # The score gap should be comfortably positive (well above noise).
    assert result["score_gap_ratio"] > 0.05
