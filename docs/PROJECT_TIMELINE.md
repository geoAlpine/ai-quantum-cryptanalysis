# Project Timeline — quantum-ecc

Compressed timeline of the two recovery datapoints and the
methodology evolution that connects them.

## 2026-04-27 — Project start

- Grover-based 4-bit ECC attack already in repo (legacy / comparison).
- Pivot to Shor's algorithm to compete in Project Eleven's Q-Day Prize.
- Hybrid strategy: beat Lelli's records AND differentiate the
  implementation (Strategy-pattern oracles, adaptive counting precision,
  multi-pass extractor).

## 2026-04-28 — Phase 0 hardware sequence on ``ibm_fez``

- 04:00 JST: 4-bit Shor on real ``ibm_fez`` succeeds.
- 12:00 JST: 6-bit, 7-bit Aer cross-validation.
- 14:30 JST: **19-bit (m=19) ECDLP world-first on ``ibm_fez``**
  (job ``d7o2dem2jamc73bp3jig``, 20 K shots, +3 algorithmic steps
  beyond Lelli's 17-bit best documented).
- 16:00 JST: 22-bit attempt at first reads as failure (0 v1 hits).
- 22:00 JST: deep analysis reveals v1 was too thin; CF-Lift v2
  implemented.
- 23:00 JST: **22-bit (m=22) recovered** (job ``d7o5mr62jamc73bp87eg``,
  12 verified hits at d=1,999,171, +7 over Lelli's prize win).

## 2026-04-29 — Public release

- Repository pushed to ``github.com/geoAlpine/ai-quantum-cryptanalysis``.
- MIT licence, no attribution debt.
- Anthropic press outreach.

## 2026-05-20 → 21 — Honest framing

- Project AQUA WordPress blog draft started.
- Funding-decision deliberation: prefecture ``助成金`` doesn't economise
  for a private-LLC sole-operator; submit ダメ元 only.
- IBM Quantum Credits ineligible for a non-academic submitter; pursue
  AWS Activate / academic co-PI / METI later.

## 2026-05-21 — **The collective-vote diagnostic**

The session's anchor finding. Implementing
``scripts/collective_decode.py`` and running it on our own 22-bit
data:

> ``d_true = 1,999,171`` sits at the **48.8th percentile** of the
> candidate-vote distribution, z = −0.03σ — statistically
> indistinguishable from random.

Conclusion: our 22-bit recovery, *and Lelli's 15-bit Round-1
winner*, both live in the same **verification-filter regime**, not
the signal-extraction regime that the wording in their papers
suggests. We renamed our work to be Phase 0, and started planning
the methodology contribution that would land in Phase 1.

## 2026-05-21 → 25 — Methodology buildout

- ``src/lattice_postprocess.hnp_score`` and
  ``hnp_recover_with_verification`` — the cross-shot HNP scoring
  with anti-d fallback.
- ``src/shor_iterative.py`` — Griffiths-Niu semiclassical Shor
  variant, 13-qubit at m=3 (vs 23 for standard).
- ``scripts/noisy_preview.py`` and ``noisy_sweep.py`` — Aer-based
  prediction tooling, run BEFORE any real QPU submission.
- ``scripts/decode_offline.py`` — re-decode any counts file without
  spending QPU.
- ``scripts/plot_hnp_distribution.py`` — diagnostic visualisation.
- ``scripts/readout_robustness.py`` — synthetic-flip robustness test.
- ``scripts/score_variants_sweep.py`` + ``likelihood_scoring.py`` —
  alternative scoring formulations (six variants tested; L2
  production, L1 / trimmed-L2 as backups; Bayesian likelihood works
  on noiseless but fails on noisy hardware).
- Test coverage: ``tests/test_hnp_verify.py`` (6 tests),
  ``test_collective_decode.py`` (3 tests), ``test_shor_iterative.py``
  (2 tests), plus all earlier suites — total ≈ 30 tests.
- Backend comparison: ``ibm_kingston`` (rank 2 stable),
  ``ibm_fez`` (rank 4), ``ibm_marrakesh`` (rank 3); ``ibm_kingston``
  picked as Phase 1 target.

The 14 / 14 noisy-Aer trial sweep at the production target
predicted: d_true at HNP rank 2, direct verification recovery,
no anti-d fallback needed.

## 2026-05-25 — **Phase 1 hardware**

Open-plan budget refresh delivered ≈ 1m22s, enough for the
1024-shot submission.

- Job: ``d89s7c9789is7393nie0`` on ``ibm_kingston``.
- 15 logical qubits, 1 243 transpiled 2Q gates, est-fid 1.97 × 10⁻³.
- DD XY4 + Pauli twirling enabled at the Sampler level.
- 1024 shots in well under 1 minute of QPU.
- 1001 unique outcomes from 1024 shots (high diversity → noisy).
- **HNP decode**: rank 1 = d=4 (verify fails), rank 2 = **d=6 → verify
  succeeds** (d_true!), rank 3 = d=1 (anti-d partner).
- Recovery path: direct verification at rank 2, no anti-d fallback.
- Match to noisy-Aer prediction: **exact**.

This is the methodology datapoint that the literature did not
have before: a quantum-hardware ECDLP recovery whose decode runs
the collective HNP score and verifies the top-K, rather than
brute-force verifying every plausible per-shot candidate.

## 2026-05-25 (same day) — Phase 2 prep

- Tried scaling to m=5 (n=31) noisy preview at t=7 ripple
  (29 qubits, 15.7 K transpiled 2Q, est-fid 7.8 × 10⁻³⁵). The
  noisy-Aer sim runs for over an hour; signal almost certainly
  destroyed by gate noise at that depth. Phase 2 needs algorithmic
  work — most likely the iterative+dense variant — before another
  hardware submission.
- Phase 1 hardware regression test
  (``test_phase1_hardware_result_replays``) added so any future
  refactor that breaks the decode trips immediately.
- ``README.md`` + ``brief.md`` + ``CITATION.cff`` updated to
  reflect the two-phase narrative.
- ``docs/honest_framing_preprint_outline.md`` §5.5 finalised with
  the actual hardware numbers.

## Repository state at end of timeline

- Branch ``refactor/code-review-may2026``, ~30 commits since the
  Phase 0 work on the ``blog/aqua-intro`` branch.
- All committed and pushed to
  ``github.com/geoAlpine/ai-quantum-cryptanalysis``.
- Test suite green; CI workflow in ``.github/workflows/test.yml``.

## Open items (Phase 2 and beyond)

1. **Lattice post-processor** — current ``hnp_recover`` scaffolding
   gives trivial short vectors; the CVP→SVP embedding needs more
   careful sentinel scaling. Required for n ≥ 10⁴.
2. **Iterative + dense oracle** — combine Lelli's semiclassical
   qubit recycling with the dense unitary block to break the
   ``t > m+~2`` wraparound. Path to m ≥ 5 hardware recovery.
3. **Multi-trial Phase 1 reproducibility** — submit 5 + independent
   jobs at the same config to characterise hardware variance.
   Needs full open-plan budget refresh (~ 5 minutes more).
4. **Noise-aware Bayesian calibration** — the noiseless likelihood
   table fails on noisy hardware; re-doing the calibration with the
   target backend's noise model may rescue the rank-1 direct
   recovery we see on noiseless Aer.
5. **arXiv preprint** — outline complete; convert to LaTeX, fill
   the references, submit.
