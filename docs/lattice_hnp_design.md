# Lattice-based HNP Recovery: Design Document

**Status**: design draft (2026-05-26). Implementation deferred to Year 1 H2 of the 3-year strategy.

**Goal**: extend the genuine-signal HNP recovery beyond the `n ≤ 10,000` ceiling imposed by exhaustive `hnp_score_search`. This is the unlock for the 15-bit+ genuine signal target.

**Audience**: future Claude session + any external collaborator we bring in for lattice expertise.

---

## 1. Background

### 1.1 Where the current code sits

`src/lattice_postprocess.py` exposes:

- `hnp_score_search` — works, but `n ≤ 10,000` only (exhaustive over all `d ∈ [0, n)`). Production path today.
- `hnp_recover_with_verification` — wraps `hnp_score_search` + EC verify + anti-`d` fallback. Used by Phase 1 hardware run.
- `hnp_recover` — **broken prototype**. Returns trivial short vectors (`d = 0`) even on noiseless 4-bit Aer data. The function we need to fix.

### 1.2 The relation to extract

Per shot the (noiseless) measurement satisfies

```
n · (j + d · k) ≡ s · M  (mod n · M)
```

where:
- `j, k ∈ [0, M)` are the counting-register measurements (M = 2^t),
- `s ∈ [0, n)` is the **hidden Shor peak index** for that shot (different per shot),
- `d ∈ [1, n)` is the discrete log we want.

On real hardware the relation holds approximately with an error term bounded by `O(M / n)` per shot for shots that landed near a peak (and `O(M)` for noise shots).

Stacking `N` shots produces a system of `N` modular constraints on `N + 1` unknowns
`(d, s_1, ..., s_N)`. This is a **multivariate Hidden Number Problem** (Boneh–Venkatesan 1996 generalised, c.f. Ekerå 2017 §3).

---

## 2. Why the current `hnp_recover` returns trivial vectors

### Bug #1 — missing modulus generators (critical)

The current basis (src/lattice_postprocess.py:100-110) is

```
Row 0:    [ n·k_1,  n·k_2,  ...,  n·k_N,   1 ]
Row i:    [   0,     ...,    -M (col i-1),  ...,   0 ]   for i = 1..N
target:   [-n·j_1, -n·j_2, ...,  -n·j_N,   0 ]
```

A lattice point `α · row_0 + Σ β_i · row_i` has column `i` equal to `α · n · k_i − β_i · M`. Setting `α = d, β_i = s_i` gives `d · n · k_i − s_i · M`, which should equal `-n · j_i` per the Shor relation — but **only modulo `n · M`**. The current basis enforces strict equality. The `mod n · M` wrap is not in the lattice. Result: most real shots have no integer solution in this basis, LLL falls to the trivial `α = β_i = 0` vector.

**Fix**: add `N` modulus rows
```
Row N+i:  [ 0, ...,  n·M (col i-1), ..., 0,  0 ]   for i = 1..N
```
This is the standard `q`-ary lattice construction.

### Bug #2 — d-tracker weight too small (critical)

`A[0, N] = 1` weights the d coordinate by `1`. The constraint columns are `O(n · k_i) = O(n · M / 2)`. After LLL the basis tries to minimise the L² norm; the algorithm will gladly pay `O(d)` ≪ `O(n · M / 2)` in the d-tracker to reduce a constraint column, so the d coordinate gets pushed to zero by reduction.

**Fix**: set `W_d ≈ M / (2 · n)` (the per-coord residual scale). Then a vector with `α = d_true` has comparable contribution from the d-tracker (`d · M / (2n)`) and from the residuals (`Σ |residual_i|² ≈ N · (M / (2n))²`), making it competitive against the trivial `α = 0` vector.

Concretely, write `W_d = ⌈M / (2 · n)⌉` (always ≥ 1).

### Bug #3 — embedding sentinel too small (moderate)

`sentinel = 1` in the Kannan embedding (src/lattice_postprocess.py:171). For the embedded short vector to contain the target+lattice difference cleanly, the sentinel must be **larger than the expected residual norm**. With `N` shots and per-coord residual `~M / (2n)`, the residual norm is `~√N · M / (2n)`.

**Fix**: `sentinel = ⌈√N · M / (2 · n)⌉` or simpler `M / 2`. Calibrate empirically on the noiseless 4-bit dataset.

### Bug #4 — basis ordering (minor)

`A[1+i, i] = -M` puts the `s_i` generator in column `i-1` of the matrix (Python 0-indexed). The intent matches the docstring (column `i-1` for the `i`-th `s` generator), but a quick off-by-one check is part of the rewrite.

---

## 3. Corrected lattice formulation

### 3.1 Basis (Ekerå-style, `q`-ary HNP)

`(2N + 1) × (N + 1)` integer matrix:

```
Row 0   (d-gen):   [ n·k_1,  n·k_2,  ...,  n·k_N,   W_d ]
Row i   (s_i):     [   0, ...,  -M (col i-1),  ..., 0,   0 ]    i = 1..N
Row N+i (modulus): [   0, ...,  n·M (col i-1), ..., 0,   0 ]    i = 1..N
```

Target row (Kannan embedding):
```
target: [ -n·j_1, -n·j_2, ..., -n·j_N,  0,  sentinel ]
```

Augmented embedded basis is `(2N + 2) × (N + 2)`:
- the original `(2N + 1)` rows extended with a final `0` column,
- the target row as the last row.

### 3.2 Recovery

After `LLL.reduction` and optional `BKZ.reduction(block_size=20-40)`:

1. Scan rows for `|last column| == sentinel`. Such rows encode `(target − closest_lattice_vector, ±sentinel)`.
2. From the closest-lattice-vector coefficient on row 0 (which is `α = d_recovered`), read `d` off the second-to-last column: `d_raw = ± row[col_d_tracker] / W_d`.
3. Return `d_raw mod n`.

### 3.3 Expected lattice properties

Determinant: `det(L) ≈ (n · M)^N · W_d`.
Gaussian heuristic for shortest vector: `λ_1 ≈ √((2N+1)/(2πe)) · (n·M)^(N/(2N+1)) · W_d^(1/(2N+1))`.
Residual norm for `d = d_true`: `√(N · (M/(2n))² + d² · W_d²) ≈ √N · M / (2n)`.

For genuine signal, `||residual|| < λ_1`, so LLL/BKZ should isolate the correct vector. **The sufficient condition is `N · (M/(2n))² ≪ det(L)^(2/(2N+1))`**, which is satisfied for any reasonable `N` (lattice "succeeds" once we collect enough shots).

Empirically (Ekerå 2017 Tab 1): `N ≈ 2m` to `4m` shots are sufficient. For `m = 15`, expect `30-60 shots` to suffice. This is FAR less than our 1024 shots per run — we should be sample-rich.

---

## 4. Implementation plan

### 4.1 Code changes

Rewrite `hnp_recover` keeping signature stable. New helper `_build_qary_lattice` returns basis + sentinel. Reuse the LLL/BKZ scan.

Pseudocode:

```python
def hnp_recover_lattice(shots, n, t, *, max_shots=64, block_size=30):
    M = 1 << t
    N = min(len(shots), max_shots)
    shots = shots[:N]

    W_d = max(1, M // (2 * n))
    sentinel = max(1, int(N**0.5 * M / (2 * n)))

    # (2N + 1) generators in (N + 1) cols.
    A = IntegerMatrix(2 * N + 1, N + 1)
    for i, (_j, k, _r) in enumerate(shots):
        A[0, i] = n * k
    A[0, N] = W_d
    for i in range(N):
        A[1 + i, i] = -M
        A[1 + N + i, i] = n * M

    target = [-n * j for (j, _k, _r) in shots] + [0]
    # Kannan embed.
    Aem = IntegerMatrix(A.nrows + 1, A.ncols + 1)
    for r in range(A.nrows):
        for c in range(A.ncols):
            Aem[r, c] = A[r, c]
    for c in range(A.ncols):
        Aem[A.nrows, c] = target[c]
    Aem[A.nrows, A.ncols] = sentinel

    LLL.reduction(Aem)
    if block_size > 2:
        BKZ.reduction(Aem, BKZ.Param(block_size=block_size))

    # Scan for the row with |last| == sentinel and minimum residual norm.
    best_d, best_norm = None, float("inf")
    for r in range(Aem.nrows):
        if abs(Aem[r, N + 1]) != sentinel:
            continue
        sign = 1 if Aem[r, N + 1] == sentinel else -1
        d_raw = sign * Aem[r, N] // W_d
        residual_norm_sq = sum(Aem[r, c] ** 2 for c in range(N))
        if residual_norm_sq < best_norm:
            best_norm, best_d = residual_norm_sq, d_raw % n
    return HNPResult(d_candidate=int(best_d or 0), ...)
```

### 4.2 Dependencies

- `fpylll` already in use (current `hnp_recover` imports it). No new packages needed.
- BKZ block size 20-30 is fine in pure Python `fpylll`; >40 needs `g6k` (a heavier install). Defer `g6k` until empirically required.

### 4.3 Estimated effort

| Phase | Work | Calendar |
|---|---|---|
| Implement new `_build_qary_lattice` + `hnp_recover_lattice` | ~150 LOC, with tests | 2-3 days |
| Validate on noiseless 4-bit Aer (n=7) | should recover d=6 with N=20 shots | 1 day |
| Validate on noiseless 9-bit Aer (n=313) | recover with N=30-50 shots | 1-2 days |
| Validate on ibm_kingston noise sim for 4-bit | recover with N=200 shots | 1 day |
| Validate on real 4-bit IBM data (Phase 1 + reps) | recover from 1024 shots | 1 day |
| Push to 19-bit IBM data (n=262K) | sample efficiency test | 2-3 days |
| Productionise (replace `hnp_score_search` for n>10K) | wire into fetch_result.py | 1 day |

**Total: ~2-3 weeks of solo work**, parallelisable with other Phase 1-2 hardware work.

---

## 5. Validation ladder

### 5.1 Step 1 — noiseless 4-bit Aer (n=7)

`scripts/aer_validate.py --bits 4 --t 6 --shots 256 --oracle dense` already gives clean noiseless data.

**Pass criterion**: lattice recovers `d = 6` with confidence > 0.5 using N = 20-30 shots.
**Fail criterion**: still returns d=0. → bugs in our formulation remain; revisit lattice construction.

### 5.2 Step 2 — noiseless 9-bit Aer (n=313)

`scripts/aer_validate.py --bits 9 --t 11 --shots 512` (build script may need t-flag widening).

**Pass criterion**: recover `d = 135` with N = 50-100 shots. Probes how fast `N` scales with `m`.

### 5.3 Step 3 — ibm_kingston noise sim for 4-bit

`scripts/noisy_sweep.py --noise-from ibm_kingston --bits 4 --t 6 --shots 1024 --trials 5`. Replace direct hnp_score_search with lattice variant.

**Pass criterion**: lattice recovers d=6 with N=200-500 shots out of 1024.

### 5.4 Step 4 — real 4-bit IBM data

Reuse Phase 1 + 3 reps (current submissions). Should give 4 × 1024 = 4096 shot pool.

**Pass criterion**: lattice recovers d=6 from N=100 shots subsampled. Demonstrates real-hardware competence.

### 5.5 Step 5 — 19-bit IBM data (sample-efficient test)

`results/_ibm_19bit_t12_counts.json` has 20K shots, n = 262,567. Exhaustive HNP impossible.

**Pass criterion**: lattice recovers `d = 36124` from any N ≤ 1000 shots subsampled.

This is the **make-or-break moment** for the genuine-signal extension to large m. If we recover d=36124 with the lattice, we've shown the 19-bit data has real signal that the v3/CF-Lift filter missed — a major scientific finding even before pushing further.

If we don't recover, the 19-bit data really is noise (confirming the collective-vote finding) and we need new hardware data at smaller m with better fidelity.

---

## 6. Risks and open questions

### 6.1 Risk: BKZ block size insufficient at large N

For `N > 100` and `m ≥ 12`, LLL alone is unlikely to find the short vector. BKZ-30 in pure `fpylll` runs in minutes; BKZ-40+ needs `g6k`. May need to install `g6k` for production large-m runs.

### 6.2 Risk: noise model mismatches Shor relation

The Shor relation is exact for ideal QFT peaks. On real hardware, noise scatters shots away from peaks; many shots have residuals close to uniform random in `[0, M)`. The lattice can be confused by these "non-peak" shots.

**Mitigation**: pre-filter shots by per-shot HNP residual (only keep shots whose `min_s |n·(j + d_guess·k) - s·M| < threshold`). Requires a `d_guess` though — chicken-and-egg unless we use bootstrap from a low-N successful recovery.

Alternative: weighted lattice with per-shot weights from residual likelihood (Bayesian variant). See `hnp_score_likelihood` in src/lattice_postprocess.py for an existing prototype.

### 6.3 Open question: best `N` per `m`

Ekerå 2017 suggests `N ≈ 2m` to `4m` is sufficient asymptotically, but real hardware needs more. Empirical sweep needed during validation Step 4.

### 6.4 Open question: anti-d ambiguity

`hnp_score` is degenerate between `d` and `(n - d) % n` (the Shor relation is symmetric under negation). The lattice may return either. Current `hnp_recover_with_verification` handles this with EC verify fallback — keep the same trick post-lattice.

---

## 7. Definition of done

The new `hnp_recover_lattice` is production-ready when:

1. Step 5 passes (19-bit recovery from subsampled real data).
2. `fetch_result.py` automatically uses lattice for `n > 10,000`.
3. Validation tests for Steps 1-5 are checked in to `tests/test_lattice_hnp.py`.
4. Computational cost (LLL + BKZ time) is < 1 minute for `N ≤ 100`.
5. The arXiv preprint Section 5.1 is updated with the proven formulation and references this design doc as the implementation record.

After that we're equipped to push to bit-widths beyond Phase 1-2 — the technical unlock for the 3-year world-record target.

---

## 8. References

- Boneh, Venkatesan (1996). "Hardness of Computing the Most Significant Bits of Secret Keys in Diffie–Hellman..." CRYPTO '96.
- Ekerå (2017). "Modifying Shor's algorithm to compute short discrete logarithms." eprint.iacr.org/2017/1027.
- Ekerå, Håstad (2017). "Quantum algorithms for computing short discrete logarithms and factoring RSA integers." PQCrypto.
- Nguyen, Stehlé (2009). "An LLL algorithm with quadratic complexity." SIAM J. Computing.
- `fpylll` documentation: github.com/fplll/fpylll.

---

## 9. Memory / dependency links

- [[project_three_year_strategy]] — this design is the Year 1 H2 milestone enabling Year 2-3 scale.
- [[project_collective_vote_findings]] — the 22-bit / 19-bit "no signal" finding is what motivates this lattice. If Step 5 succeeds, those findings need revisiting.
- [[project_qday_prize]] — Section 5.1 of `docs/honest_framing_preprint_outline.md` is the publication target for the validated lattice.
