# 19-bit Shor (t=12) — Step 1 Deep Analysis Report

**Date**: 2026-04-28
**Job**: `d7o2dem2jamc73bp3jig` on `ibm_fez`
**Source data**: `results/_ibm_19bit_t12_counts.json` (20,000 shots, all unique outcomes)

---

## TL;DR

We recovered `d=36124` for the 19-bit (m=19) ECDLP challenge curve on real IBM Quantum hardware. **The recovery is real, but the mechanism is verification-filter on near-random measurements, NOT quantum signal extraction.** Same regime as Lelli's 17-bit Q-Day Prize win. This is a competition result, not a proof of quantum advantage.

---

## Circuit Summary

| Parameter | Value |
|---|---|
| Curve | y² = x³ + 7 mod 262153 |
| Subgroup order n | 262567 |
| Group bit length m | 19 |
| Counting register width t | 12 (adaptive, < m=19) |
| Total qubits | 67 (vs Lelli 17-bit: 69) |
| Transpiled depth | 236,973 |
| Transpiled 2Q gates | 103,708 (vs Lelli 17-bit: 111,816) |
| Estimated circuit fidelity | 10⁻²²⁶ |
| Shots | 20,000 |
| Unique outcomes | 20,000 (all unique — fully decohered) |

---

## Direct Extraction Results

| Method | Verified d=36124 hits |
|---|---|
| Direct: `d_cand = (r-j)·k⁻¹ mod n` | **1** |
| Pairwise (20K samples) | 0 |
| Continued fraction | 0 |
| Bit-shift (low-precision compensation) | 1 (= same as direct) |
| Multi-shot consensus voting | 1 (same hit) |

The verified hit: `(j=1608, k=3100, r=132466)`, count=1.

Random expectation under uniform: 20000/262567 ≈ **0.076 hits**.
Observing 1 hit: p-value ≈ 0.073 — borderline, NOT significant at p<0.05.

---

## Bit-Marginal Distribution Analysis

44-bit measurement, per-bit p(1):

| Register | Mean p(1) | Std | Pattern |
|---|---|---|---|
| 4-bit IBM ref (known signal) | 0.466 | 0.027 | Uniform-like (signal spreads) |
| **19-bit t=12 (this run)** | **0.423** | **0.139** | **Bias toward 0 (decoherence)** |

Most extreme j-register bits (mapped to j_value bit positions):
- j_value bit_8: p(1) = 0.003 (z = -1285)
- j_value bit_4: p(1) = 0.012 (z = -622)
- j_value bit_2: p(1) = 0.039 (z = -337)

These extreme biases are consistent with **|0⟩-relaxation under deep T1/T2 decay**, NOT structured quantum signal.

Mode bitstring (most-likely value per bit) extracts to d_cand = **93707 ≠ 36124** → marginals carry no signal.

---

## Ideal Shor Distribution Comparison (key result)

For our verified hit's r₀ = 132466:
- Support: **64 valid (j', k') pairs** (matches predicted 4ᵗ/n = 64)
- Total P(r₀): 3.81e-6 ✓
- **Peak P (where signal would land)**: 1.455e-11 = **64× uniform**
- **Our hit's P**: 1.835e-14 = **0.081× uniform** (in a TROUGH)
- Hit's rank: 7,891,473 / 16,777,216 (47th percentile)

So even if the IBM machine had been noiseless, the position our hit landed at would have had probability **1/790 of the ideal peak**. We did not hit a Shor peak — we hit a generic low-amplitude position that happened to satisfy verification.

---

## Statistical Sample (50 random shots from data)

| Metric | Observed | Pure-Noise Expected | Quantum-Signal Expected |
|---|---|---|---|
| Avg P_hit / P_mean | **0.243** | 1.0 | >> 1.0 |
| Shots in TOP 100 / 16M cells | 0 | 0.0003 | many |
| Shots in TOP 1% cells | 0 | 0.5 | >> 0.5 |
| Median rank within r₀ | 9.99M | 8.39M | small |

**The 0.243 < 1.0 ratio is the smoking gun**: shots are systematically AVOIDING ideal-Shor peaks. This is the signature of hardware bias (toward |0⟩ at deep circuits) which happens to anti-correlate with quantum-peak positions. There is **no detectable quantum signal contribution** beyond the single lucky verification hit.

---

## J-K Bit Mutual Information

Best j-bit ↔ k-bit pair: MI = 5.6e-4 bits (random expects 5e-5, so **~11× above noise floor**).
Marginally above random — could be weak signal or shared noise. Not load-bearing for the conclusion.

---

## Honest Conclusion for Q-Day Prize submission

What we can claim:
- ✅ Successfully recovered private key d = 36124 of the 19-bit ECDLP challenge curve (m=19) on IBM Quantum hardware
- ✅ First public 19-bit ECDLP recovery on quantum hardware (3 algorithmic steps beyond Lelli's m=16 Q-Day Prize record)
- ✅ Used FEWER qubits (67 vs 69) and FEWER 2Q gates (104K vs 112K) than Lelli's 17-bit run
- ✅ Demonstrated novel adaptive-counting technique (t=12 < m=19) that Lelli did not employ
- ✅ Algorithm pipeline (oracle → controlled adds → QFT⁻¹ → extraction → verification) functions end-to-end

What we cannot honestly claim:
- ❌ Quantum signal contributed materially to the recovery (1 hit at p=0.073 is not significant)
- ❌ Quantum advantage demonstrated (verification filter is doing all the work)
- ❌ The verified hit corresponded to a Shor peak (it landed in a trough at 0.08× ideal mean)

This is the same regime as Lelli's 17-bit run; he won 1 BTC by submitting in this exact frame. Our submission would be honest about the same limitations and offer:
- +3 algorithmic steps (m=16 → m=19)
- Adaptive-counting precision as a novel technique
- Lower resource footprint
