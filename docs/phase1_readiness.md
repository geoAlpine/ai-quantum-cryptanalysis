# Phase 1 Hardware Submission Readiness

*Last updated: 2026-05-22*

## Submission target

```bash
python scripts/submit_18bit.py \
    --bits 4 --t 6 \
    --oracle dense --extractor hnp \
    --backend ibm_kingston --shots 1024
```

Resource budget: ~30 seconds of IBM open-plan QPU time, ~5% of the
10-minute/28-day allocation.

## Pre-submission validation status

### Noiseless Aer

| Solver | Oracle | t | qubits | d_true HNP rank | Gap | Status |
|---|---|---|---|---|---|---|
| Standard | Dense | 6 | 15 | 2 (top-1 = −d_true) | 22% | ✓ |
| Iterative | Ripple | 6 | 13 | 1 (top-1 = d_true) | 17% | ✓ |

### Noisy Aer (IBM backend noise models, 2026-05-22)

Dense oracle (the submission target):

| Backend | Shots | Trials | d_true rank | Gap | Recovery via |
|---|---|---|---|---|---|
| ibm_kingston | 1024 | 3 | **2** | 3.0% | direct |
| ibm_kingston | 2048 | 3 | **2** | 4.0% | direct |
| ibm_kingston | 4096 | 3 | **2** | 5.0% | direct |
| ibm_fez | 2048 | 1 | 4 | 6.6% | anti-d (HNP rank 3) |
| ibm_marrakesh | 2048 | 1 | 3 | 1.1% | anti-d (HNP rank 2) |

Iterative ripple at ibm_kingston: 8400 2Q gates after transpile,
estimated fidelity 4×10⁻¹⁹. Iterative discarded for Phase 1 hardware
on fidelity grounds — kept for future m ≥ 22 work where the qubit
savings become load-bearing.

## Pipeline components

- `scripts/submit_18bit.py --extractor hnp` — submission entry point.
- `scripts/fetch_result.py` — branches on `extractor` field of pending
  metadata; runs `hnp_recover_with_verification` for `hnp`.
- `src/lattice_postprocess.hnp_recover_with_verification` — production
  recovery: HNP score → top-K candidates → verify each + each one's
  anti-d partner against `d · G == Q`.
- `scripts/noisy_preview.py` — pre-submission Aer-with-noise check.
- `scripts/noisy_sweep.py` — multi-shot, multi-trial robustness sweep.
- `scripts/decode_offline.py` — re-decode any counts file without
  spending QPU; lets us re-extract with different parameters after
  the fact.
- `scripts/plot_hnp_distribution.py` — diagnostic plot generator.

## Test coverage

```
$ pytest -v -m "not slow"
- tests/test_cf_lift_v3.py: 16 property tests for the candidate generator
- tests/test_extractor_replay.py: 4 regression tests on saved IBM data
- tests/test_collective_decode.py: pinned honest-framing claims
- tests/test_hnp_verify.py: 5 tests for HNP+verify pipeline invariants
- tests/test_shor_iterative.py: construction + d_true-rank-1 property
- tests/test_ripple_oracle.py: oracle correctness
```

Total: ~30 tests, fast suite under 30s.

## Known limitations (carry forward to Phase 2)

1. **t > m + ~2 wraparound**: at large t the controlled-additions
   ``2^i · G`` repeat with period ``log_2(n)`` and the QFT signal
   collapses. For m=3 the safe range is t ≤ 6. For m=8+, t cannot
   exceed m + ~2 without breaking the signal.
2. **HNP exhaustive search**: only feasible for n ≤ 10^4. Lattice
   variant (`hnp_recover`) is scaffolded but not yet working — the
   CVP→SVP embedding lands on trivial short vectors on noiseless
   small-m data.
3. **Modular ambiguity**: HNP intrinsically returns the d-class
   ``{d, −d mod n}``, not d directly. The anti-d verification
   fallback handles this for small n; at large n it grows to a
   ``(Z/n)*``-orbit of size φ(n).
4. **Iterative QPE fidelity penalty**: at m=3 the qubit savings
   (23 → 13) don't compensate for the 7× increase in transpiled 2Q
   gates. Iterative becomes useful at m ≥ 22 where the standard
   variant exceeds the 156-qubit Heron r2 physical-qubit limit.

## Phase 2 follow-ups (after the m=3 hardware datapoint)

- Validate the HNP lattice (`hnp_recover`) on noiseless small-m,
  then push to n ≥ 100 simulated data.
- Implement iterative + dense oracle variant — dense compresses the
  oracle to a unitary block, which combined with iterative's qubit
  savings should make m=8 hardware-feasible with t=6.
- Real-hardware submission at the largest m where noisy-Aer + HNP
  still places d-class in top-K with high confidence.

## Submission go/no-go criteria

- [x] Pipeline end-to-end tested on existing 4-bit IBM data
- [x] Noisy-Aer recovery verified at target backend (ibm_kingston, 9/9 trials)
- [x] Submission script dry-run passes
- [x] Fetch script handles `extractor: "hnp"` branch
- [x] All committed and pushed to `refactor/code-review-may2026`
- [ ] **IBM open-plan budget refresh** (currently exhausted; refresh
      expected ~2026-05-26 based on 28-day window from prior runs)

When the budget clears, run the submission command above and then
`python scripts/fetch_result.py results/_pending_4bit_t6_dense_hnp_ibm.json`.
