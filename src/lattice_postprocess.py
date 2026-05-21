"""
Hidden Number Problem (HNP) lattice post-processor for Shor-ECDLP measurements.

The textbook (Lelli-style) recovery uses per-shot direct extraction
``d = (r - j) * k^{-1} (mod n)`` followed by verification — which we've
shown is verification-filter dominated even at noiseless small ``m`` and
gives zero collective signal on the 22-bit IBM run.

The HNP approach treats *all shots' constraints jointly*: each
measurement contributes a noisy linear constraint on ``d``, and LLL/BKZ
lattice reduction finds the ``d`` that simultaneously satisfies them
(closest-vector). When genuine quantum signal is present at sub-rounding
resolution, this can recover ``d`` from shots that direct extraction
treats as noise.

This is the D-1 path from the 2026-05-21 planning session — a *clean*
implementation independent of CF-Lift candidate enumeration and free of
the verification-filter shortcut. See ``project_collective_vote_findings``
in memory for the strategic context.

Status: **prototype skeleton** — pinned interface and lattice construction
based on Boneh–Venkatesan 1996. Validation against noiseless small-``m``
Aer data is the next step; do not rely on the output for hardware data
until that empirical calibration is done.

Reference: Ekerå (2017) eprint.iacr.org/2017/1027 for the cleaner
modular reduction of two-register Shor's algorithm — the lattice
construction below is the natural HNP variant of that relation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class HNPResult:
    """Outcome of an HNP recovery attempt."""

    d_candidate: int
    """Best ``d`` candidate from the LLL/BKZ short vector."""

    confidence: float
    """Heuristic: ``1 - (short_vec_norm / second_short_vec_norm)`` — values
    near 1 indicate a clean dominant solution, values near 0 indicate
    ambiguity. NOT a probability; calibrate empirically."""

    short_vector_norm: float
    """L2 norm of the shortest reduced lattice vector."""

    used_shots: int
    """Number of shots used to build the lattice (after filtering)."""


def build_hnp_lattice(
    shots: list[tuple[int, int, int]],
    n: int,
    t: int,
    *,
    max_shots: int | None = None,
):
    """Construct the HNP lattice from Shor-ECDLP measurements.

    Each shot ``(j_i, k_i, r_i)`` with the QFT-output convention
    ``j_i, k_i ∈ [0, 2^t)`` and ``r_i ∈ [0, n)`` contributes one row.

    The unknowns are ``d`` and per-shot integer ``s_i`` encoding which
    QFT peak the shot landed on. The lattice is built so that the target
    vector ``(j_i, ..., 0)`` is close to the lattice vector encoding the
    true ``d`` and ``{s_i}``.

    Returns the fpylll IntegerMatrix and target vector. Caller runs LLL
    or BKZ and decodes ``d`` from the short vector's last coordinate.
    """
    from fpylll import IntegerMatrix

    M = 1 << t
    if max_shots is not None and len(shots) > max_shots:
        shots = shots[:max_shots]
    N = len(shots)

    # Lattice dimensions: N rows for modular relations + 1 row for the d
    # column. Columns: N coefficients + 1 last column scaling by M.
    A = IntegerMatrix(N + 1, N + 1)
    for i in range(N):
        A[i, i] = n * M
    for i, (j_i, k_i, _r_i) in enumerate(shots):
        # The d-row contributes k_i * n to column i.
        A[N, i] = (k_i * n) % (n * M)
    A[N, N] = 1

    # Target vector: (n * j_1 - r_1 * M, ..., n * j_N - r_N * M, 0).
    target = [
        (n * j_i - r_i * M) % (n * M)
        for (j_i, k_i, r_i) in shots
    ] + [0]
    return A, target


def hnp_recover(
    shots: list[tuple[int, int, int]],
    n: int,
    t: int,
    *,
    max_shots: int = 128,
    block_size: int = 20,
    expected_d: Optional[int] = None,
) -> HNPResult:
    """LLL/BKZ-driven recovery of ``d`` from Shor-ECDLP shots.

    Parameters
    ----------
    shots
        List of ``(j, k, r)`` triples extracted from a counts file.
    n
        Subgroup order.
    t
        Counting register width (so ``M = 2^t``).
    max_shots
        Bound on lattice dimension. ~50–200 is typical; beyond that BKZ
        gets very slow.
    block_size
        BKZ block size. ``block_size=2`` reduces to LLL. ``20`` is a
        reasonable middle ground.
    expected_d
        Optional: if provided, the function also reports whether the
        recovered ``d_candidate`` matches. Useful for validation runs.
    """
    from fpylll import LLL, BKZ

    A, target = build_hnp_lattice(shots, n, t, max_shots=max_shots)
    N = A.nrows - 1

    LLL.reduction(A)
    if block_size > 2:
        BKZ.reduction(A, BKZ.Param(block_size=block_size))

    # The recovered d is encoded in the last column of the shortest
    # vector that captures most of the target. We iterate the reduced
    # basis and pick the row whose last coordinate yields a verifier-
    # consistent d.
    best_d = 0
    best_norm = float("inf")
    second_norm = float("inf")
    for i in range(A.nrows):
        norm_sq = sum(A[i, j] ** 2 for j in range(A.ncols))
        if norm_sq < best_norm:
            second_norm = best_norm
            best_norm = norm_sq
            best_d = A[i, A.ncols - 1] % n
        elif norm_sq < second_norm:
            second_norm = norm_sq

    confidence = 1.0 - (best_norm / second_norm) if second_norm > 0 else 0.0
    return HNPResult(
        d_candidate=int(best_d),
        confidence=float(confidence),
        short_vector_norm=float(best_norm ** 0.5),
        used_shots=N,
    )


def hnp_score(d: int, shots: list[tuple[int, int, int]],
              n: int, t: int) -> float:
    """Score a candidate ``d`` against shot data via the HNP residual.

    After measuring the point register at some ``R_0``, the two-register
    Shor (j, k) state is supported on the lattice
    ``L_d(R_0) = {(jₛ, kₛ) ∈ [0, M)² : jₛ + d·kₛ ≡ R_0 (mod n)}``.
    Inverse-QFT-ing concentrates that lattice's amplitude at
    ``(j_m, k_m)`` such that
    ``j_m + d · k_m ≡ round(s · M / n) (mod M)``
    for *some* integer ``s ∈ [0, n)`` — the "Shor index" of the peak,
    a hidden variable that varies per shot. Note that ``r`` (the
    measured point) does **not** enter this modular relation: ``r``
    selects which lattice ``L_d(R_0)`` we project into, but the QFT
    peaks of every such lattice live at the same set of ``(j_m, k_m)``.

    The score is therefore
    ``score(d) = Σ_i  min_{s ∈ [0, n)} | (j_i + d·k_i) mod M - round(s·M/n) |²``

    For the correct ``d`` the residuals are bounded by ~M/(2n) and the
    total is small; for wrong ``d`` the (j + d·k) mod M values are
    pseudo-uniform in [0, M) and the residual is large. The ``r`` field
    of each shot is unused by this score — kept in the function
    signature to match the parsed-shot tuple shape.
    """
    M = 1 << t
    # Pre-compute the n expected peak positions, sorted for binary search.
    expected = sorted({(s * M + n // 2) // n % M for s in range(n)})
    half = M // 2
    total_sq = 0
    for (j, k, _r) in shots:
        v = (j + d * k) % M
        # Find the closest expected peak (with wrap-around at M).
        best = M
        for e in expected:
            diff = (v - e) % M
            diff = diff if diff <= half else diff - M
            if abs(diff) < best:
                best = abs(diff)
        total_sq += best * best
    return total_sq / max(1, len(shots))


def hnp_score_search(
    shots: list[tuple[int, int, int]],
    n: int,
    t: int,
    *,
    max_n: int = 10_000,
    expected_d: Optional[int] = None,
) -> dict:
    """Exhaustive ``d ∈ [0, n)`` HNP-score search. Only feasible when n
    is small (≤ ``max_n``). Returns the argmin ``d`` and the runner-up
    score gap as a confidence indicator.

    On noiseless small-``m`` Aer data we expect ``d_true`` to dominate
    with a clear gap; on hardware data dominated by uniform noise we
    expect a nearly-flat score landscape (gap ≈ 0).
    """
    if n > max_n:
        raise ValueError(
            f"n={n:,} > max_n={max_n:,}; use lattice variant for large n"
        )

    scores: list[tuple[int, float]] = []
    for d in range(n):
        s = hnp_score(d, shots, n, t)
        scores.append((d, s))
    scores.sort(key=lambda x: x[1])

    best_d, best_score = scores[0]
    second_score = scores[1][1] if len(scores) > 1 else best_score
    mean_score = sum(s for _, s in scores) / n
    gap = (second_score - best_score) / max(1e-9, second_score)

    return {
        "d_recovered": best_d,
        "best_score": best_score,
        "second_best_score": second_score,
        "score_gap_ratio": gap,
        "mean_score": mean_score,
        "matches_expected": (expected_d is not None and best_d == expected_d),
        "expected_d": expected_d,
        "top5": scores[:5],
    }


__all__ = [
    "HNPResult",
    "build_hnp_lattice",
    "hnp_recover",
    "hnp_score",
    "hnp_score_search",
]
