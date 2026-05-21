"""
Inspect the noiseless statevector of the Shor circuit at a small ``m``.

The collective-vote test on the 22-bit headline data showed *zero* quantum
signal, and even at *noiseless* m=4 the direct-extraction signal-to-noise
sits ~5× below textbook Shor expectations. Before pushing on more
algorithms, we need to know **what the circuit actually outputs** as
amplitudes — not just shot statistics, which can hide structure.

This script:
  1. Builds the full Shor circuit at the given ``m`` (no shots, no noise).
  2. Computes the exact statevector via Qiskit's ``Statevector``.
  3. Marginalises over the ancillas and tabulates the dominant
     ``(j, k, r)`` tuples by probability.
  4. For each top tuple, tries every candidate ``(j, k, r) → d`` formula
     and reports which (if any) yields ``d_true``.

The output exposes both:
  * Where the QFT peaks actually land (without shot noise).
  * Which extraction relation, if any, agrees with the textbook
    ``j + d·k ≡ r (mod n)`` or its variants.

Usage:
    python scripts/inspect_statevector.py --bits 4 --top 16
    python scripts/inspect_statevector.py --bits 4 --top 32 --reverse-bits
"""
from __future__ import annotations

import argparse
import math
import sys
from typing import Iterator

import numpy as np
from qiskit.quantum_info import Statevector

from challenges import get_challenge
from ecc import EllipticCurve
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)


def _build_solver(bits: int, t: int, oracle_kind: str) -> ShorECDLPSolver:
    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    ind = SubgroupIndexer(curve, G, c.n)
    oracle = DenseUnitaryOracle(ind) if oracle_kind == "dense" else RippleCarryOracle(ind)
    return ShorECDLPSolver(curve, G, Q, c.n, oracle=oracle, num_counting=t)


def _decompose_state_index(idx: int, num_qubits: int, t: int, pt_w: int,
                             reverse: bool) -> tuple[int, int, int, int]:
    """Decompose a statevector basis-state index into (j, k, r, anc).

    Qubit layout in this circuit (from ``build_circuit``):
      qubits [0..t-1]            = j_reg  (qubit 0 = LSB of j)
      qubits [t..2t-1]           = k_reg
      qubits [2t..2t+pt_w-1]     = pt_reg
      qubits [2t+pt_w..]         = ancilla

    Qiskit basis-state convention: qubit 0 = LSB of ``idx`` → corresponds
    to the rightmost character of ``format(idx, 'Nb')``.
    """
    bits = format(idx, f"0{num_qubits}b")  # MSB-first, qubit[N-1] first
    if reverse:
        bits = bits[::-1]
    # bits[-1] = qubit 0 = LSB of j_reg, so j_bits are the RIGHTMOST t chars.
    j = int(bits[-t:], 2)
    k = int(bits[-2 * t:-t], 2)
    r = int(bits[-2 * t - pt_w:-2 * t], 2)
    anc_chars = bits[:-2 * t - pt_w] if 2 * t + pt_w < num_qubits else ""
    anc = int(anc_chars, 2) if anc_chars else 0
    return j, k, r, anc


def _enumerate_formulas(j: int, k: int, r: int, t: int, n: int) -> Iterator[tuple[str, int]]:
    """Yield ``(formula_name, d_candidate)`` over every formula worth trying."""
    M = 1 << t

    # Helper to test invertibility.
    def inv(x: int) -> int | None:
        if x % n == 0:
            return None
        try:
            return pow(x % n, -1, n)
        except ValueError:
            return None

    # F1: textbook two-register Shor — a, b are direct rounding of j, k.
    a = (j * n + M // 2) // M
    b = (k * n + M // 2) // M
    binv = inv(b)
    if binv is not None:
        yield "scaled (r - a)/b", ((r - a) * binv) % n
    ainv = inv(a)
    if ainv is not None:
        yield "scaled (r - b)/a", ((r - b) * ainv) % n
    if binv is not None:
        yield "scaled (a - r)/b", ((a - r) * binv) % n

    # F2: raw j, k (no scaling) — used by extract() Pass 1.
    kinv = inv(k)
    if kinv is not None:
        yield "raw (r - j)/k", ((r - j) * kinv) % n
        yield "raw (j - r)/k", ((j - r) * kinv) % n
    jinv = inv(j)
    if jinv is not None:
        yield "raw (r - k)/j", ((r - k) * jinv) % n

    # F3: Negative slope — Shor often uses j - dk ≡ r, not j + dk.
    if binv is not None:
        yield "scaled -(r + a)/b", ((-(r + a)) * binv) % n
    if kinv is not None:
        yield "raw -(r + j)/k", ((-(r + j)) * kinv) % n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, default=4)
    ap.add_argument("--t", type=int, default=None,
                    help="counting register width (default: m, full precision)")
    ap.add_argument("--oracle", choices=["dense", "ripple"], default="ripple")
    ap.add_argument("--top", type=int, default=16,
                    help="number of top-amplitude basis states to inspect")
    ap.add_argument("--reverse-bits", action="store_true",
                    help="whole-bitstring reversal of the statevector index")
    args = ap.parse_args()

    c = get_challenge(args.bits)
    n = c.n
    d_true = c.expected_d
    m = (n - 1).bit_length()
    t = args.t if args.t is not None else m

    solver = _build_solver(args.bits, t, args.oracle)
    plan = solver.plan()
    pt_w = solver.oracle.point_register_width()
    qc = solver.build_circuit()
    qc.remove_final_measurements(inplace=True)  # statevector needs unmeasured qubits

    print(f"=== Statevector inspection ===")
    print(f"  challenge bits = {args.bits}, n = {n}, m = {m}, d_true = {d_true}")
    print(f"  oracle = {args.oracle}, t = {t}, total qubits = {plan.total_qubits}")
    print(f"  reverse-bits = {args.reverse_bits}")
    print()

    if plan.total_qubits > 20:
        print(f"  WARNING: {plan.total_qubits} qubits → 2^{plan.total_qubits} = "
              f"{2 ** plan.total_qubits:,} amplitudes.")

    print("  computing statevector ...")
    sv = Statevector.from_instruction(qc)
    probs = np.abs(sv.data) ** 2
    nq = qc.num_qubits

    # Identify top-K basis states.
    top_idx = np.argsort(probs)[::-1][:args.top]
    print()
    print(f"  top-{args.top} basis states by probability (sum p = {probs.sum():.6f}):")
    print(f"  {'idx':<8} {'p':<12} {'j':<4} {'k':<4} {'r':<4} {'anc':<6}  decoded relations passing d_true:")

    counter: dict[str, int] = {}
    for idx in top_idx:
        p = float(probs[idx])
        j, k, r, anc = _decompose_state_index(int(idx), nq, t, pt_w,
                                                reverse=args.reverse_bits)
        # Test every formula; count which (if any) yields d_true.
        passes: list[str] = []
        for name, d_cand in _enumerate_formulas(j, k, r, t, n):
            if d_cand == d_true:
                passes.append(name)
                counter[name] = counter.get(name, 0) + 1
        passes_str = ", ".join(passes) if passes else "(none)"
        print(f"  {int(idx):<8} {p:<12.6f} {j:<4} {k:<4} {r % n:<4} {anc:<6}  {passes_str}")

    print()
    print(f"  formula hit counts (out of {args.top} top states):")
    for name, cnt in sorted(counter.items(), key=lambda x: -x[1]):
        print(f"    {cnt:>3} / {args.top}  :  {name}")
    if not counter:
        print(f"    *** NO formula reproduces d_true on any of the top-{args.top} states ***")


if __name__ == "__main__":
    sys.exit(main())
