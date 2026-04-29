"""
Real Grover-based ECDLP quantum circuit.

Key property: the oracle uses only G and Q (public values), never the secret k.
The circuit finds k via quantum interference without being told the answer.

Algorithm:
  1. Prepare k_reg in uniform superposition
  2. Grover loop:
     a. QROM: |k>|0> -> |k>|k*G>  (uses classical table of G multiples)
     b. Phase kickback: mark k where k*G == Q
     c. Uncompute QROM
     d. Grover diffusion
  3. Measure k_reg
"""

import math
import sys
import os

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister

sys.path.insert(0, os.path.dirname(__file__))
from ecc import EllipticCurve, ECPoint, _PRESETS


def _coord_bits(p: int) -> int:
    return math.ceil(math.log2(p + 1))


def _build_lut(G: ECPoint, curve: EllipticCurve, k_bits: int) -> list[int]:
    """Classically compute k*G for k in 0..2^k_bits-1. Returns encoded integers."""
    coord_bits = _coord_bits(curve.p)
    lut = []
    for k in range(2**k_bits):
        pt = curve.scalar_mul(k, G)
        if pt.is_infinity:
            lut.append(0)
        else:
            lut.append((pt.x << coord_bits) | pt.y)
    return lut


def _apply_qrom(
    qc: QuantumCircuit,
    k_reg: QuantumRegister,
    ec_reg: QuantumRegister,
    lut: list[int],
    k_bits: int,
    ec_bits: int,
) -> None:
    """
    QROM: |k>|0> -> |k>|lut[k]>
    Self-inverse: applying twice restores ec_reg to |0>.
    """
    for k_val, enc in enumerate(lut):
        if enc == 0:
            continue
        # LSB-first: k_reg[0] = bit0 (2^0), matching Qiskit's measurement convention
        k_binary = format(k_val, f"0{k_bits}b")[::-1]
        zero_bits = [k_reg[i] for i, b in enumerate(k_binary) if b == "0"]
        for q in zero_bits:
            qc.x(q)
        for bit_pos in range(ec_bits):
            if (enc >> bit_pos) & 1:
                qc.mcx([k_reg[i] for i in range(k_bits)], ec_reg[bit_pos])
        for q in zero_bits:
            qc.x(q)


def _apply_phase_oracle(
    qc: QuantumCircuit,
    ec_reg: QuantumRegister,
    anc: QuantumRegister,
    Q_encoded: int,
    ec_bits: int,
) -> None:
    """
    Phase kickback: flip phase when ec_reg == Q_encoded.
    anc must be in |-> before the Grover loop begins.
    """
    zero_bits = [ec_reg[i] for i in range(ec_bits) if not ((Q_encoded >> i) & 1)]
    for q in zero_bits:
        qc.x(q)
    # CRITICAL: use register objects, not integer indices
    qc.mcx([ec_reg[i] for i in range(ec_bits)], anc[0])
    for q in zero_bits:
        qc.x(q)


def _apply_diffusion(qc: QuantumCircuit, k_reg: QuantumRegister, k_bits: int) -> None:
    """Grover diffusion: 2|ψ><ψ| - I on k_reg."""
    qc.h(k_reg)
    qc.x(k_reg)
    qc.h(k_reg[k_bits - 1])
    if k_bits > 1:
        qc.mcx([k_reg[i] for i in range(k_bits - 1)], k_reg[k_bits - 1])
    else:
        qc.x(k_reg[0])
    qc.h(k_reg[k_bits - 1])
    qc.x(k_reg)
    qc.h(k_reg)


def grover_ecdlp_circuit(
    G: ECPoint,
    Q: ECPoint,
    curve: EllipticCurve,
    k_bits: int,
) -> QuantumCircuit:
    """
    Build Grover ECDLP circuit that finds k s.t. Q = k*G.
    Inputs: G, Q (public EC points), curve, k_bits (key bit width)
    Does NOT take secret k as input.
    """
    coord_bits = _coord_bits(curve.p)
    ec_bits = 2 * coord_bits
    n_iters = max(1, int(math.pi / 4 * math.sqrt(2**k_bits)))

    k_reg = QuantumRegister(k_bits, "k")
    ec_reg = QuantumRegister(ec_bits, "ec")
    anc = QuantumRegister(1, "anc")
    c_k = ClassicalRegister(k_bits, "c_k")

    qc = QuantumCircuit(k_reg, ec_reg, anc, c_k)

    lut = _build_lut(G, curve, k_bits)
    Q_encoded = (Q.x << coord_bits) | Q.y

    # Uniform superposition over k
    qc.h(k_reg)

    # Initialize ancilla to |-> for phase kickback
    qc.x(anc[0])
    qc.h(anc[0])

    for _ in range(n_iters):
        _apply_qrom(qc, k_reg, ec_reg, lut, k_bits, ec_bits)
        _apply_phase_oracle(qc, ec_reg, anc, Q_encoded, ec_bits)
        _apply_qrom(qc, k_reg, ec_reg, lut, k_bits, ec_bits)  # uncompute
        _apply_diffusion(qc, k_reg, k_bits)

    qc.measure(k_reg, c_k)
    return qc


def make_grover_instance(
    k_bits: int = 3,
    tiny: bool = False,
) -> tuple[EllipticCurve, ECPoint, int, ECPoint]:
    """
    Build ECDLP instance with secret k in [1, 2^k_bits - 1].

    tiny=True uses p=11 (4-bit coords, 12 total qubits) — optimized for real hardware.
    tiny=False uses p=67 (7-bit coords, 18 total qubits) — larger field.
    """
    import random
    if tiny:
        # y^2 = x^3 + 7 mod 11, G=(4,4), order=12
        # 4-bit coordinates → 12 total qubits (vs 18 for p=67)
        curve = EllipticCurve(0, 7, 11)
        G = curve.point(4, 4)
        order = 12
    else:
        a, b, p, gx, gy, order = _PRESETS[6]
        curve = EllipticCurve(a, b, p)
        G = curve.point(gx, gy)
    k = random.randint(1, min(order - 1, 2**k_bits - 1))
    Q = curve.scalar_mul(k, G)
    return curve, G, k, Q
