"""
Challenge curves for Q-Day Prize / ECDLP ladder.

All curves use y^2 = x^3 + 7 (a=0, b=7) on F_p, secp256k1 family.
Bit lengths 4 through 30 are derived via the strict-check generator
(p > 3, p != 7, p ≡ 1 mod 3, cofactor h ≤ 2, seed=536) so they
match the public Q-Day Prize input set, enabling cross-comparison.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Challenge:
    bit_length: int
    p: int
    n: int                            # subgroup order
    G: tuple[int, int]
    Q: tuple[int, int]
    expected_d: Optional[int] = None  # only for known-answer tests

    @property
    def n_bits(self) -> int:
        return max(1, (self.n - 1).bit_length())


_DATA: list[tuple] = [
    # (bits, p,        n,        Gx, Gy,       Qx, Qy,       d)
    ( 4,        13,        7,    11,      5,    11,      8,        6),
    ( 6,        43,       31,    34,      3,    21,     25,       18),
    ( 7,        67,       79,    48,     60,    52,      7,       56),
    ( 8,       163,      139,   112,     53,   122,    144,      103),
    ( 9,       349,      313,    22,    191,   138,    315,      135),
    (10,       547,      547,   386,    359,   286,    462,      165),
    (11,      1051,     1093,   471,    914,   179,     86,      756),
    (12,      2089,     2143,  1417,     50,  1043,   1795,     1384),
    (13,      4159,     4243,  3390,   2980,  3457,   3962,      820),
    (14,      8209,     8293,  5566,      7,  2144,   2381,      137),
    (15,     16477,    16693, 15429,  10667,  6884,  12671,    14794),
    (16,     32803,    32497, 14333,  24084, 31890,   7753,    20248),
    (17,     65647,    65173, 12976,  52834,   477,  58220,     1441),
    (18,    131251,   130579, 66566, 127721,122895,  58382,    26320),
    (19,    262153,   262567, 44507, 141754,253977,  23539,    36124),
    (20,    525043,   524269,449655,  39077,417592, 204251,   493247),
    (21,   1048783,  1050337,231634, 106125,1047961,428633,   653735),
    (22,   2097211,  2098699,2096853,790051,184036,1283798,  1999171),
    (23,   4194523,  4197601,2548129,242548,777676,4075405,  2010097),
    (24,   8389039,  8387557,6669871,526268,2763960,7088533, 2988156),
    (25,  16777723, 16773667,2807739,5820947,8172715,5481321,14844862),
    (26,  33555391, 33544321,  56477,32422240,20621232,3308190,17221898),
    (27,  67109191, 67092871,25084870,56841289,520632,56822761,28380436),
    (28, 134217877,134203759,70956396,98753116,81461929,27204990,19818140),
    (29, 268435987,268414693,212781849,261826477,69848749,64403746,6537183),
    (30, 536871061,536824801,358930086,473817143,499393403,354360184,148511986),
]

CHALLENGES: dict[int, Challenge] = {
    bits: Challenge(bits, p, n, (gx, gy), (qx, qy), d)
    for (bits, p, n, gx, gy, qx, qy, d) in _DATA
}


def get_challenge(bit_length: int) -> Challenge:
    if bit_length not in CHALLENGES:
        available = sorted(CHALLENGES.keys())
        raise KeyError(f"No challenge for {bit_length}-bit. Available: {available}")
    return CHALLENGES[bit_length]


def verify_challenge(c: Challenge) -> bool:
    """Sanity-check: G, Q on curve; d*G == Q; n*G == O."""
    from ecc import EllipticCurve
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    if c.expected_d is not None:
        if curve.scalar_mul(c.expected_d, G) != Q:
            return False
    if not curve.scalar_mul(c.n, G).is_infinity:
        return False
    return True
