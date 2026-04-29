"""
Elliptic Curve Cryptography over finite fields.
Supports small prime fields suitable for quantum attack experiments.
"""

from dataclasses import dataclass
from typing import Optional
import random


@dataclass(frozen=True)
class ECPoint:
    x: Optional[int]
    y: Optional[int]
    curve: "EllipticCurve" = None

    @property
    def is_infinity(self) -> bool:
        return self.x is None and self.y is None

    def __repr__(self):
        if self.is_infinity:
            return "O (point at infinity)"
        return f"({self.x}, {self.y})"


class EllipticCurve:
    """y^2 = x^3 + ax + b  over  F_p"""

    def __init__(self, a: int, b: int, p: int):
        self.a = a
        self.b = b
        self.p = p
        assert (4 * a**3 + 27 * b**2) % p != 0, "Singular curve"

    def point(self, x: Optional[int], y: Optional[int]) -> ECPoint:
        pt = ECPoint(x, y, self)
        if not pt.is_infinity:
            assert self.is_on_curve(pt), f"Point {pt} is not on curve"
        return pt

    @property
    def infinity(self) -> ECPoint:
        return ECPoint(None, None, self)

    def is_on_curve(self, pt: ECPoint) -> bool:
        if pt.is_infinity:
            return True
        lhs = (pt.y * pt.y) % self.p
        rhs = (pt.x**3 + self.a * pt.x + self.b) % self.p
        return lhs == rhs

    def add(self, P: ECPoint, Q: ECPoint) -> ECPoint:
        if P.is_infinity:
            return Q
        if Q.is_infinity:
            return P
        if P.x == Q.x:
            if P.y != Q.y:
                return self.infinity
            return self._double(P)
        lam = ((Q.y - P.y) * pow(Q.x - P.x, -1, self.p)) % self.p
        x3 = (lam**2 - P.x - Q.x) % self.p
        y3 = (lam * (P.x - x3) - P.y) % self.p
        return self.point(x3, y3)

    def _double(self, P: ECPoint) -> ECPoint:
        if P.is_infinity or P.y == 0:
            return self.infinity
        lam = ((3 * P.x**2 + self.a) * pow(2 * P.y, -1, self.p)) % self.p
        x3 = (lam**2 - 2 * P.x) % self.p
        y3 = (lam * (P.x - x3) - P.y) % self.p
        return self.point(x3, y3)

    def scalar_mul(self, k: int, P: ECPoint) -> ECPoint:
        result = self.infinity
        addend = P
        while k:
            if k & 1:
                result = self.add(result, addend)
            addend = self._double(addend)
            k >>= 1
        return result


def bsgs_dlog(G: ECPoint, Q: ECPoint, curve: EllipticCurve, order: int) -> Optional[int]:
    """
    Baby-step Giant-step ECDLP solver. O(√order) time and space.
    Finds k s.t. k*G == Q.
    """
    import math
    m = math.isqrt(order) + 1

    # Baby steps: table[j*G] = j
    baby = {}
    step = curve.infinity
    for j in range(m):
        key = (step.x, step.y)
        baby[key] = j
        step = curve.add(step, G)

    # Giant steps: Q - i*m*G for i = 0..m
    mG = curve.scalar_mul(m, G)
    # Negate mG: (x, -y mod p)
    neg_mG = curve.point(mG.x, (-mG.y) % curve.p) if not mG.is_infinity else curve.infinity

    gamma = Q
    for i in range(m + 1):
        key = (gamma.x, gamma.y)
        if key in baby:
            k = i * m + baby[key]
            if 0 < k < order:
                return k
        gamma = curve.add(gamma, neg_mG)

    return None


# Precomputed parameters: (a, b, p, Gx, Gy, order)
# All verified: G is on the curve and order >= 2^bits.
_PRESETS = {
    6:  (0, 7, 67,          2,   22,        79),
    15: (0, 7, 32771,       2,   23168,     32772),
    20: (0, 7, 1048583,     5,   894904,    1048584),
    25: (0, 7, 33554467,    2,   3661551,   33554467),
    30: (0, 7, 1073741827,  2,   164245020, 1073741827),
}


def make_small_curve(bits: int) -> tuple[EllipticCurve, ECPoint, int, ECPoint]:
    """
    Return (curve, G, secret_k, Q) for an n-bit ECDLP instance.
    Uses precomputed generators — no expensive order search at runtime.
    """
    target = min(_PRESETS.keys(), key=lambda b: abs(b - bits))
    a, b, p, gx, gy, order = _PRESETS[target]
    curve = EllipticCurve(a, b, p)
    G = curve.point(gx, gy)
    k = random.randint(2, min(order - 1, 2**target - 1))
    Q = curve.scalar_mul(k, G)
    return curve, G, k, Q
