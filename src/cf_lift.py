"""
CF-Lift candidate generator family.

Single source of truth for the v3 extractor used by ``ShorECDLPSolver.extract``
and the standalone calibration / measurement scripts. v3 generates many more
distinct (a, b) candidates per measured (j, k) than v2 (which saturates around
25 due to the natural continued-fraction expansion).

In the NISQ regime, measurements are essentially uniform random and the
extractor's job is to maximise the verification-filter hit rate by enumerating
as many *distinct, plausible* d-candidates per shot as possible. Empirically
calibrated on 22-bit / 19-bit IBM data: the per-shot hit rate matches the
uniform-noise model ``C / n`` within statistical noise — i.e. v3 is a
candidate generator, not a quantum-signal decoder. See README.md → "Honest
framing" for what that implies.
"""
from __future__ import annotations

from math import gcd


# ---------------------------------------------------------------------------
# Calibration table — measured on the 35K-shot 22-bit IBM job (ibm_fez, t=12,
# job d7o5mr62jamc73bp87eg) using ``scripts/measure_v3.py``. Maps the v3
# ``window`` parameter to the average number of distinct verified-form
# d-candidates generated per shot (after intersecting a- and b-side lifts and
# applying the gcd(b, n) == 1 invertibility filter).
#
# Used by the projection ``E[hits] = C_per_shot * shots / n`` in submit-time
# scripts (``scripts/preflight.py``, ``scripts/submit_25bit.py``) so we don't
# burn QPU budget on a misconfigured run.
#
# Re-calibrate by running:
#     python scripts/measure_v3.py --counts <new_counts.json> \
#         --bits <bits> --pt-w <pt_w> --window <W>
# and updating this table. Keep entries sorted by window for grep-friendliness.
# ---------------------------------------------------------------------------
CF_C_TABLE: dict[int, int] = {
    8: 3560,
    16: 8255,
    32: 23569,
    64: 77535,
    128: 269522,
}


def estimate_c_per_shot(window: int) -> int:
    """Return calibrated C-per-shot for ``window``, or a coarse fallback.

    The fallback ``(2W + 1)**2`` over-estimates because real candidate sets
    intersect with the b-side and dedupe — but it keeps preflight from crashing
    on uncalibrated windows. Calibrate properly before relying on the number.
    """
    cal = CF_C_TABLE.get(window)
    if cal is not None:
        return cal
    return max(8, 2 * window + 1) ** 2


def cf_lift_v3(x_meas: int, t: int, n: int,
               window: int = 64,
               max_scale: int = 4,
               include_bitflips: bool = True,
               include_mirror: bool = True,
               max_candidates: int | None = None) -> list[int]:
    """Generate plausible d-axis candidates from a single QFT measurement.

    Parameters
    ----------
    x_meas
        Measured QFT outcome on one axis (j or k).
    t
        Width of the counting register, so ``N = 2**t``.
    n
        Subgroup order — candidates are returned in ``[0, n)``.
    window
        Perturbation half-width around the direct rounding ``x_meas * n / N``.
        Larger window → more candidates → higher uniform-noise hit rate.
    max_scale
        Generates also ``s · (p, q)`` for ``s = 2..max_scale`` of each
        convergent (helps when the true denominator is a small multiple of a
        convergent's).
    include_bitflips
        Add a single-bit-flip variant of ``x_meas`` (covers 1-bit readout
        errors).
    include_mirror
        Add the ``x_meas ↔ (N - x_meas) mod N`` mirrored candidate set
        (QFT peaks come in symmetric pairs).
    max_candidates
        Optional cap on returned candidates — when set, prefers those closest
        to the direct rounding (most likely to be the true peak in an ideal
        run).
    """
    if x_meas == 0 and not include_mirror:
        return [0]

    N = 1 << t
    candidates: set[int] = set()

    def add(a: int) -> None:
        candidates.add(a % n)

    def lift_pq(p: int, q: int) -> None:
        if q <= 0:
            return
        a = (p * n + q // 2) // q
        if 0 <= a < n:
            add(a)

    def expand_convergents(x: int) -> None:
        if x == 0:
            return
        nn, dd = x, N
        g = gcd(nn, dd)
        nn //= g
        dd //= g
        cf: list[int] = []
        while dd > 0 and len(cf) < 40:
            cf.append(nn // dd)
            nn, dd = dd, nn % dd

        h0, h1 = 0, 1
        k0, k1 = 1, 0
        prev_p, prev_q = 0, 1
        for ai in cf:
            h2 = ai * h1 + h0
            k2 = ai * k1 + k0
            if k2 > n:
                if k1:
                    max_a = (n - k0) // k1
                    if max_a >= 1:
                        h2s = max_a * h1 + h0
                        k2s = max_a * k1 + k0
                        if 0 < k2s <= n:
                            lift_pq(h2s, k2s)
                            for s in range(2, max_scale + 1):
                                if k2s * s <= n:
                                    lift_pq(h2s * s, k2s * s)
                break
            lift_pq(h2, k2)
            for s in range(2, max_scale + 1):
                if k2 * s <= n:
                    lift_pq(h2 * s, k2 * s)
            if prev_q > 0:
                med_p, med_q = prev_p + h2, prev_q + k2
                if 0 < med_q <= n:
                    lift_pq(med_p, med_q)
            prev_p, prev_q = h2, k2
            h0, h1 = h1, h2
            k0, k1 = k1, k2

    expand_convergents(x_meas)
    if include_mirror:
        expand_convergents((N - x_meas) % N)

    a_direct = (x_meas * n + N // 2) // N
    for delta in range(-window, window + 1):
        add(a_direct + delta)

    if include_mirror:
        a_mirror = ((N - x_meas) * n + N // 2) // N
        for delta in range(-window, window + 1):
            add(a_mirror + delta)

    if include_bitflips:
        for bit in range(t):
            xf = x_meas ^ (1 << bit)
            af = (xf * n + N // 2) // N
            if 0 <= af < n:
                add(af)

    out = sorted(candidates)
    if max_candidates is not None and len(out) > max_candidates:
        out.sort(key=lambda a: abs(a - a_direct))
        out = out[:max_candidates]
    return out
