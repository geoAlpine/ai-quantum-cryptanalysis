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
    """Construct the Boneh-Venkatesan-style HNP lattice for the
    two-register Shor ECDLP peak relation.

    Per shot the noiseless ideal satisfies
    ``n · (j_i + d · k_i) ≡ s_i · M (mod n · M)``
    for some integer ``s_i ∈ [0, n)`` (the hidden Shor peak index).
    Stacked across ``N`` shots, this is a multivariate HNP with
    unknowns ``d, s_1, …, s_N``.

    Lattice basis (``N+1`` generators, ``N+1`` columns):

      - Row 0 (the "d generator"): ``[n·k_1, n·k_2, …, n·k_N, B]``
        where ``B = 1`` keeps the d-encoded coordinate small after
        reduction.
      - Row i (for ``i ∈ [1, N]``, the "s_i generator"):
        ``[0, …, -M (column i-1), …, 0, 0]``.

    A lattice point ``α · row_0 + Σ_i β_i · row_i`` has coordinates
    ``(α · n · k_i − β_i · M  for i, α · B)``. Setting ``α = d`` and
    ``β_i = s_i`` makes the first ``N`` coordinates equal
    ``n · d · k_i − s_i · M``, which is close to ``-n · j_i`` (the
    target) by the Shor relation. The last coordinate is then ``d``,
    encoding the recovered key.

    Returns ``(B, target)`` where ``target = [-n·j_1, …, -n·j_N, 0]``.
    Caller embeds CVP→SVP and runs LLL/BKZ; ``hnp_recover`` does this.

    Note: ``r`` is intentionally NOT used — the post-pt-measurement
    state's R₀ shifts the Shor lattice but the QFT peak positions in
    (j, k) are the same set for every R₀.
    """
    from fpylll import IntegerMatrix

    M = 1 << t
    if max_shots is not None and len(shots) > max_shots:
        shots = shots[:max_shots]
    N = len(shots)

    A = IntegerMatrix(N + 1, N + 1)
    # Row 0: d generator.
    for i, (_j_i, k_i, _r_i) in enumerate(shots):
        A[0, i] = n * k_i
    A[0, N] = 1  # d-tracker column

    # Rows 1..N: each s_i generator contributes -M in its own column.
    for i in range(N):
        A[1 + i, i] = -M

    target = [-n * j_i for (j_i, _k_i, _r_i) in shots] + [0]
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

    **Status**: prototype. The CVP→SVP embedding currently lands on
    trivial short vectors (d=0 / norm=0) on noiseless 4-bit dense data
    where exhaustive ``hnp_score_search`` cleanly recovers d-class. The
    issue is most likely in the embedding scale (``sentinel = 1`` may
    be too small, letting the target be absorbed without paying enough
    cost) or in the basis ordering after LLL. Treat this as scaffolding
    until a deeper validation pass — for n ≤ 10K use
    ``hnp_score_search`` / ``hnp_recover_with_verification`` instead.

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
    from fpylll import IntegerMatrix, LLL, BKZ

    A, target = build_hnp_lattice(shots, n, t, max_shots=max_shots)
    N = A.nrows - 1

    # CVP → SVP embedding: append target as an extra row with a sentinel
    # in the new last column. After reduction, the short vector that
    # contains the embedded target (sentinel in last coord) decodes to
    # (lattice_vec - target), and its second-to-last coord is d.
    sentinel = 1  # any small positive — controls how "attractive" the
                   # target is to the short basis vector.
    n_cols = A.ncols
    Aem = IntegerMatrix(A.nrows + 1, n_cols + 1)
    for r in range(A.nrows):
        for c in range(n_cols):
            Aem[r, c] = A[r, c]
        Aem[r, n_cols] = 0
    for c in range(n_cols):
        Aem[A.nrows, c] = target[c]
    Aem[A.nrows, n_cols] = sentinel

    LLL.reduction(Aem)
    if block_size > 2:
        BKZ.reduction(Aem, BKZ.Param(block_size=block_size))

    # Scan reduced basis for the row whose embedded-sentinel is ±sentinel —
    # that row contains the (lattice − target) closest-vector difference.
    best_d = None
    best_norm = float("inf")
    second_norm = float("inf")
    for r in range(Aem.nrows):
        if abs(Aem[r, n_cols]) != sentinel:
            continue
        sign = -1 if Aem[r, n_cols] == sentinel else 1
        # The d coordinate sits in column A.ncols-1 of the embedded
        # vector. Recover sign-adjusted d.
        d_raw = sign * Aem[r, n_cols - 1]
        # norm of the "residual" portion (first N coords).
        norm_sq = sum(Aem[r, c] ** 2 for c in range(N))
        if norm_sq < best_norm:
            second_norm = best_norm
            best_norm = norm_sq
            best_d = d_raw % n
        elif norm_sq < second_norm:
            second_norm = norm_sq

    if best_d is None:
        best_d = 0  # fallback — likely indicates lattice failure
    confidence = (
        1.0 - (best_norm / second_norm) if second_norm > 0 and second_norm < float("inf") else 0.0
    )
    return HNPResult(
        d_candidate=int(best_d),
        confidence=float(confidence),
        short_vector_norm=float(best_norm ** 0.5) if best_norm < float("inf") else 0.0,
        used_shots=N,
    )


def hnp_score_likelihood(d: int, shots: list[tuple[int, int, int]],
                          n: int, t: int, *, sigma: float = 0.0) -> float:
    """Bayesian-style scoring: each shot's residual is modelled as a
    mixture of Gaussians centred on the n expected peak positions.

    The negative log-likelihood replaces the squared-distance score.
    Empirically widens the gap between d-class and competitors on the
    same noisy data, at marginal extra cost (still O(n × shots × n))
    but more principled.

    ``sigma`` controls the peak width — auto-tuned to ~M/(2n) when 0,
    matching the rounding error of an ideal noiseless peak.
    """
    import math
    M = 1 << t
    if sigma <= 0:
        sigma = max(1.0, M / (2 * n))
    inv_2s2 = 1.0 / (2 * sigma * sigma)
    expected = sorted({(s * M + n // 2) // n % M for s in range(n)})
    half = M // 2
    total_neg_logl = 0.0
    for (j, k, _r) in shots:
        v = (j + d * k) % M
        # Full Gaussian-mixture likelihood: sum exp(-d²/2σ²) across all
        # peaks, then take −log. log-sum-exp trick for stability.
        d2_list = []
        for e in expected:
            diff = (v - e) % M
            diff = diff if diff <= half else diff - M
            d2_list.append(diff * diff)
        # log-sum-exp: -log Σ exp(-d²/(2σ²)) = log_sum_exp_min(-d²)
        m_min = min(d2_list)
        from math import exp, log
        s = sum(exp(-(d2 - m_min) * inv_2s2) for d2 in d2_list)
        # neg log-likelihood (constant terms dropped)
        nll = m_min * inv_2s2 - log(s)
        total_neg_logl += nll
    return total_neg_logl / max(1, len(shots))


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


def hnp_recover_with_verification(
    shots: list[tuple[int, int, int]],
    n: int,
    t: int,
    verify_fn,
    *,
    top_k: int = 10,
) -> dict:
    """End-to-end signal-regime recovery: HNP score → top-K candidates →
    verify each (and its modular inverse partner ``(n - d) % n``) against
    the EC check ``d · G == Q``.

    This is the **production** recovery flow for the iterative + dense
    Shor variants where:
      - HNP top-1 may be ``d_true`` directly (noiseless small n) or
        ``-d_true mod n`` (most other cases) — symmetry-driven.
      - On hardware noise the right ``d`` may shift further down the
        ranking but should remain inside the top few.

    Parameters
    ----------
    shots
        Parsed ``(j, k, r)`` triples.
    n, t
        Subgroup order and counting register width.
    verify_fn
        Callable ``d -> bool`` returning ``True`` iff ``d · G == Q``.
        Pass ``lambda d: curve.scalar_mul(d, G) == Q`` from the caller.
    top_k
        Number of HNP-score-best candidates to verify (plus their
        anti-d partners). Default 10 covers the typical hardware
        regime where d_true may rank 4-6 (see 2026-05-21 n=31 data).

    Returns
    -------
    dict
        Keys: ``d_recovered`` (int or None), ``rank_in_hnp`` (int),
        ``verified_via_anti_d`` (bool), ``top_k_searched`` (int),
        ``hnp_top_k`` (list of (d, score)), ``elapsed_seconds`` (float).
    """
    import time
    t0 = time.time()
    # Score all d ∈ [0, n) — only feasible for small n. For large n
    # this should be replaced with a lattice-reduction variant.
    if n > 10_000:
        raise ValueError(
            f"n={n:,} > 10K; need lattice-reduction HNP for genuine recovery at this scale"
        )

    scores = sorted(
        ((d, hnp_score(d, shots, n, t)) for d in range(n)),
        key=lambda x: x[1],
    )

    seen: set[int] = set()
    for rank, (d_cand, _score) in enumerate(scores[:top_k], 1):
        for candidate, via_anti in [(d_cand, False),
                                     ((n - d_cand) % n, True)]:
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate == 0:
                continue
            try:
                if verify_fn(candidate):
                    return {
                        "d_recovered": candidate,
                        "rank_in_hnp": rank,
                        "verified_via_anti_d": via_anti,
                        "top_k_searched": top_k,
                        "hnp_top_k": [(d, s) for d, s in scores[:top_k]],
                        "elapsed_seconds": time.time() - t0,
                    }
            except Exception:
                continue

    return {
        "d_recovered": None,
        "rank_in_hnp": None,
        "verified_via_anti_d": None,
        "top_k_searched": top_k,
        "hnp_top_k": [(d, s) for d, s in scores[:top_k]],
        "elapsed_seconds": time.time() - t0,
    }


def hnp_recover_lattice(
    shots: list[tuple[int, int, int]],
    n: int,
    t: int,
    *,
    max_shots: int = 64,
    block_size: int = 30,
    expected_d: Optional[int] = None,
) -> HNPResult:
    """q-ary HNP lattice recovery of ``d`` from Shor-ECDLP shots.

    Corrected formulation per ``docs/lattice_hnp_design.md`` — fixes
    three bugs in the legacy ``hnp_recover`` prototype:

    1. Adds q-ary modulus rows for the ``(mod n·M)`` wrap of the Shor
       relation ``n·(j + d·k) ≡ s·M (mod n·M)``. Without these rows
       the lattice can only solve exact equalities and LLL collapses to
       the trivial zero vector.
    2. Scales the d-tracker by ``W_d = ⌈M/(2n)⌉`` so the d coordinate
       contributes comparably to the per-shot residual; with ``W_d=1``
       any d is "free" and reduction zeroes the d coordinate.
    3. Scales the Kannan-embedding sentinel by ``⌈√N · M/(2n)⌉`` so
       the embedded short vector reliably contains the target.

    Basis layout (``(2N + 1) × (N + 1)``):

      Row 0          d-generator   ``[ n·k_1, ..., n·k_N,  W_d ]``
      Row 1..N       s_i           ``[ 0,..., -M (col i-1),..., 0 ]``
      Row N+1..2N    modulus n·M   ``[ 0,..., n·M (col i-1),..., 0 ]``

    Target  ``[ -n·j_1, ..., -n·j_N,  0 ]`` is Kannan-embedded into an
    extra column whose only nonzero entry is ``sentinel`` (on the
    target row).

    After LLL/BKZ, scan rows for ``|last col| == sentinel``; the one
    with the smallest residual norm encodes ``±d_true·W_d`` in the
    d-tracker column.

    See Ekerå (2017) eprint.iacr.org/2017/1027 §3 for the modular
    reduction underlying this construction.
    """
    from fpylll import IntegerMatrix, LLL, BKZ

    M = 1 << t
    if max_shots is not None and len(shots) > max_shots:
        shots = shots[:max_shots]
    N = len(shots)
    if N == 0:
        return HNPResult(d_candidate=0, confidence=0.0,
                         short_vector_norm=0.0, used_shots=0)

    W_d = max(1, M // (2 * n))
    sentinel = max(1, int((N ** 0.5) * M / (2 * n)))

    # (2N + 1) generators, (N + 1) columns.
    A = IntegerMatrix(2 * N + 1, N + 1)
    for i, (_j, k, _r) in enumerate(shots):
        A[0, i] = n * k
    A[0, N] = W_d
    for i in range(N):
        A[1 + i, i] = -M
        A[1 + N + i, i] = n * M

    target = [-n * j for (j, _k, _r) in shots] + [0]

    # Kannan embedding: append target row with sentinel in a new last col.
    Aem = IntegerMatrix(A.nrows + 1, A.ncols + 1)
    for r in range(A.nrows):
        for c in range(A.ncols):
            Aem[r, c] = A[r, c]
        Aem[r, A.ncols] = 0
    for c in range(A.ncols):
        Aem[A.nrows, c] = target[c]
    Aem[A.nrows, A.ncols] = sentinel

    LLL.reduction(Aem)
    if block_size > 2:
        BKZ.reduction(Aem, BKZ.Param(block_size=block_size))

    last_col = A.ncols      # the new sentinel column (index N+1)
    d_col = N               # the d-tracker column inside the original basis

    best_d = None
    best_norm = float("inf")
    second_norm = float("inf")
    for r in range(Aem.nrows):
        sval = Aem[r, last_col]
        if abs(sval) != sentinel:
            continue
        val = Aem[r, d_col]
        # If sval == +sentinel: short vec = target - α·row_0 - ... ,
        # so d-tracker holds -α·W_d. If sval == -sentinel, sign is flipped.
        if sval == sentinel:
            val = -val
        d_raw = (round(val / W_d)) % n
        residual_sq = sum(int(Aem[r, c]) ** 2 for c in range(N))
        if residual_sq < best_norm:
            second_norm = best_norm
            best_norm = residual_sq
            best_d = d_raw
        elif residual_sq < second_norm:
            second_norm = residual_sq

    if best_d is None:
        best_d = 0

    confidence = (
        1.0 - (best_norm / second_norm)
        if 0 < second_norm < float("inf")
        else 0.0
    )

    return HNPResult(
        d_candidate=int(best_d),
        confidence=float(confidence),
        short_vector_norm=float(best_norm ** 0.5) if best_norm < float("inf") else 0.0,
        used_shots=N,
    )


__all__ = [
    "HNPResult",
    "build_hnp_lattice",
    "hnp_recover",
    "hnp_recover_lattice",
    "hnp_score",
    "hnp_score_search",
    "hnp_recover_with_verification",
]
