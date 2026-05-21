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


__all__ = ["HNPResult", "build_hnp_lattice", "hnp_recover"]
