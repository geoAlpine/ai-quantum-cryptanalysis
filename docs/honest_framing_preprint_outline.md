# Beyond the Verification Filter

**Documenting the NISQ-era Boundary in Shor-ECDLP Recovery**

*Draft outline — 2026-05-21*
Author: Yosuke Aoki (GeoAlpine LLC)
Target: arXiv (quant-ph + cs.CR), ~6 pages, preprint server first
Status: ready to write once D-1 (HNP lattice) is validated on noiseless 4-bit

---

## Abstract (target ~150 words)

Public claims of "ECDLP private-key recovery on quantum hardware" — including
Project Eleven's Q-Day Prize Round-1 prize-winning 15-bit submission (Lelli,
April 2026) and our own 22-bit world-record run on ``ibm_fez`` (April 2026) —
all rely on a final classical EC verification step ``d_cand · G == Q``. We
show, via a no-side-channel **collective vote test** on the same hardware
data, that the recovered ``d`` is statistically indistinguishable from any
other ``d ∈ [0, n)`` in the candidate-vote distribution: on 35,000 ``ibm_fez``
shots at 22-bit, the true private key sits at the 48.8th percentile of vote
frequencies (z = -0.03σ, ratio 1.00× uniform-noise expectation). The recovery
is real, but the regime is *verification-filter-on-noise*, not quantum-signal
extraction. We name this regime, quantify the gap to genuine collective
recovery, and propose a sub-rounding lattice post-processor as the path to a
honestly-classifiable quantum advantage in cryptanalysis benchmarks.

---

## 1. Introduction (1 page)

- ECDLP is the security primitive under Bitcoin / TLS / digital signatures.
- Shor's algorithm theoretically breaks ECDLP in polynomial quantum time.
- Project Eleven Q-Day Prize (2026): public, prize-backed benchmark series
  for ECDLP recovery on quantum hardware.
- Round 1 (April 2026) awarded 1 BTC to Lelli for a 15-bit recovery on
  IBM Quantum.
- Question: what does "recovery on quantum hardware" actually measure?
- Our contribution: a no-side-channel statistical test that distinguishes
  *quantum-signal-driven* recovery from *verification-filter-driven*
  recovery, applied to:
  - Our own 22-bit IBM Quantum result (world-largest published).
  - Our 19-bit independent confirmation.
  - Implicitly: Lelli's 15-bit (same algorithm, same regime).

## 2. Background (~1 page)

### 2.1 Two-register Shor for ECDLP (brief refresher)

- Counting registers of size ``t``, point register of size ``m+1``.
- After QFT⁻¹, peaks should encode ``d`` via ``a + d·b ≡ R₀ (mod n)``
  for ``(a, b) ≈ (j_meas·n/2^t, k_meas·n/2^t)``.

### 2.2 The verification filter

- Existing extractors (Lelli's, ours) generate candidate ``d``-values per
  shot and accept those passing ``d · G == Q``.
- BSGS pre-computation of ``d_known`` reduces this verify to integer
  comparison; without that shortcut it is a full EC scalar mult per
  candidate.

### 2.3 NISQ-era hardware reality (Heron r2)

- ~10⁻³ two-qubit gate error; 22-bit Shor at ``t = 12`` uses ~125K 2Q
  gates, estimated end-to-end fidelity ≈ 10⁻¹⁵¹.
- Per-shot output is essentially uniform noise across the (j, k, r)
  outcome space.

## 3. The Collective Vote Test (~1.5 pages)

### 3.1 Construction

- For each shot, generate the CF-Lift-v3 candidate set ``{d_cand}``.
- Tally votes into a length-``n`` array, *without* using ``d_known`` as
  a shortcut.
- Statistical reference: under the null hypothesis ``H₀`` (uniform noise
  + uniform candidate density), each ``d`` receives
  ``E[votes/d] = C × shots / n`` votes, with
  ``σ = sqrt(E × (1 − 1/n))``.

### 3.2 Decision rule

- "Signal present" ↔ ``votes(d_true)`` significantly above ``E``
  *AND* ``d_true`` ranked near argmax.
- The "argmax test" is the strict version that the prize regime
  *should* pass if Shor signal were dominant.

### 3.3 Application to our data

| Dataset | shots | n | votes(d_true) | E_uniform | z-score | rank |
|---|---|---|---|---|---|---|
| 19-bit, t=12, ibm_fez | 20,000 | 262,567 | 62 | 58.0 | +0.52σ | 72,102 / 262,567 |
| **22-bit, t=12, ibm_fez** | **35,000** | **2,098,699** | **137** | **137.32** | **−0.03σ** | **1,024,632 / 2,098,699** |
| 4-bit noiseless Aer | 4,096 | 7 | n/a (n too small for test) | | | |

The 22-bit headline run shows **literally zero** collective signal —
``d_true`` ratio = 1.00× and z within rounding of the uniform mean.

### 3.4 Interpretation

- Verification accepted 12 hits at ``d_true``, but those 12 hits are
  exactly what uniform-noise + candidate-density predicts.
- The recovery is real (a real ``d`` was identified), but the
  identification mechanism is classical brute force through the
  verification filter, not quantum information extraction.

## 4. Implications (~1 page)

### 4.1 Reframing Q-Day Prize Round 1

- Lelli's 15-bit submission (m=15, t=15, ibm_fez) uses the same
  algorithmic family and the same extraction strategy.
- We argue — based on our regime classification — that the 1 BTC
  award validated **the verification-filter regime** as a legitimate
  benchmark, *not* a quantum-signal-extraction breakthrough.
- This is neither a critique of Lelli nor of Project Eleven; it is a
  precise *name* for the regime the field is currently operating in.

### 4.2 What real quantum signal would look like

- Argmax of the collective vote distribution coincides with ``d_true``.
- Or, equivalently, a sub-rounding-resolution lattice post-processor
  recovers ``d`` from a small number of shots without verification.
- We sketch an HNP-style lattice formulation (Section 5) as the
  natural next benchmark.

### 4.3 What this means for PQC migration urgency

- The largest verified ECC key recovery on quantum hardware to date
  (m = 22) does **not** imply that Bitcoin's 256-bit ECC is closer
  to attack than previously estimated.
- The gap to Bitcoin is not 22 → 256 in algorithmic ladder; it is the
  gap between "verification-filter regime" and "signal regime", which
  is gated by hardware fidelity, not algorithmic ingenuity at
  small ``m``.

## 5. Toward Signal-Regime Recovery (~1 page)

### 5.1 The HNP lattice formulation

- Each shot ``(j_i, k_i, r_i)`` contributes a noisy linear constraint
  on ``d`` plus an unknown peak index ``s_i ∈ [0, n)``.
- ``N`` shots → ``N + 1`` unknowns (``d`` and ``{s_i}``).
- Boneh–Venkatesan-style lattice with one row per shot + one row for
  ``d``; LLL/BKZ recovers ``d`` from the short vector.

### 5.2 Open implementation

- Released as ``src/lattice_postprocess.py`` and
  ``scripts/lattice_decode.py`` in the public
  ``ai-quantum-cryptanalysis`` repo (MIT licence).
- Current status: skeleton runs but returns trivial short vector;
  the next iteration adds ``{s_i}`` as explicit lattice variables.

### 5.3 Iterative QPE / semiclassical variant

- Mid-circuit measurement + classical feedback compresses each counting
  register to a single recyclable qubit (Mosca-Ekert, Beauregard).
- m=22 implementable in ~30 logical qubits (vs 73 in the full-precision
  layout).
- Lelli has a public reference implementation
  (``google_semiclassical.py``); independent re-implementation pending.

### 5.4 Roadmap

- Validate the lattice post-processor on noiseless small-``m`` Aer.
- Find the largest ``m`` at which the IBM noise model still admits
  collective signal under the lattice extractor.
- Submit to real hardware at that ``m``.
- That run, if it passes the collective vote argmax test, would be the
  first publicly documented *signal-regime* recovery on quantum hardware.

## 6. Conclusion (~0.5 page)

- The Shor-ECDLP recoveries currently published on quantum hardware sit
  in a verification-filter regime that conflates a real quantum
  computation with a real classical EC check. The intersection of those
  two is sufficient for a Q-Day Prize award but not for a
  cryptographic-relevance claim.
- We have provided the diagnostic — collective vote test — and the
  open-source tools for the community to make the distinction.
- Our 22-bit world record is real and useful **as a regime
  characterisation**. The next milestone is the first signal-regime
  recovery; we expect it to land at modest ``m ∈ [8, 12]`` rather than
  at the largest ``m`` someone can fit on hardware.

## Appendix A — Reproducibility

- All hardware Job IDs, raw counts, scripts, and analyses are public
  at ``github.com/geoAlpine/ai-quantum-cryptanalysis``.
- The collective vote test is one command:
  ``python scripts/collective_decode.py --counts <file> --bits <m> --window 16``.
- The full extractor regression replay is a single ``pytest`` invocation.

## Appendix B — AI-agent provenance

- All code (Shor solver, oracle, extractor, diagnostic tools, this
  paper draft) co-developed by an LLM agent (Anthropic Claude Sonnet
  / Opus 4.x via Claude Code), see ``AGENT.md``.
- This is documented as a methodological contribution: cryptanalysis-
  scale research increasingly tractable for solo / small-team
  operators via frontier AI workflow.

---

## References (target ~15)

- Shor 1994 (original)
- Beauregard 2003 (semiclassical / mid-circuit measurement)
- Mosca-Ekert 1998 (iterative phase estimation)
- Cuccaro et al. 2004 (CDKM ripple-carry adder)
- Boneh-Venkatesan 1996 (HNP, lattice attacks)
- Ekerå 2017 (modern Shor post-processing) — eprint.iacr.org/2017/1027
- Ekerå-Håstad 2017 (multi-shot lattice for factoring)
- Lelli 2026 — github.com/GiancarloLelli/quantum
- Project Eleven Q-Day Prize 2026 announcement
- ECDLP challenge ladder paper (arxiv:2508.14011)
- IBM Quantum Heron r2 calibration notes
- Google Quantum AI 2026-03 resource estimate
- ... fill the rest from internal references

---

## Notes for next session

- Numbers in Section 3.3 are verbatim from
  ``scripts/collective_decode.py`` output, reproducible from the
  shipped counts files. Keep them up to date if the extractor changes.
- Section 5.1 needs the HNP construction completed (Task #20) before
  the paper is publishable — otherwise we have a diagnosis without a
  proposed cure.
- Consider co-author: a Japanese university quantum researcher (per
  funding decisions memo) would strengthen both academic credibility
  and the IBM Quantum Credits angle. Reach out *after* Section 5 is
  validated on noiseless Aer.
- Submission strategy: arXiv preprint first → 2 weeks for community
  feedback → revise and submit to a venue (QIP, EUROCRYPT
  Real-World workshop, IACR Communications in Cryptology).
