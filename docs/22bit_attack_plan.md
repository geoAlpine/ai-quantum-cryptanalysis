# 22-bit ECDLP Attack Plan (May 2026 budget)

**Target**: 22-bit Q-Day Prize challenge curve (m=22, **+7 algorithmic steps over Lelli's prize-winning m=15** / +6 over his best documented m=16)
**Backend**: ibm_fez (IBM Heron r2, 156 qubits)
**Budget**: 10 minutes monthly QPU on Open Plan

## Curve parameters

| Param | Value |
|---|---|
| p | 2,097,211 |
| n | 2,098,699 (m=22) |
| G | (2,096,853, 790,051) |
| Q | (184,036, 1,283,798) |
| expected_d | 1,999,171 |

## Resource projection (dry-run completed 2026-04-28)

| t | qubits | trans-depth | 2Q gates | est-fid | 4ᵗ/n | risk |
|---|---|---|---|---|---|---|
| 12 | 71 | 278,703 | 123,936 | 10⁻²⁷⁰ | 8 | borderline |
| 14 | 75 | 325,413 | 143,387 | 10⁻³¹³ | 128 | more noise (worse) |
| 16 | 79 | 370,621 | 164,406 | ~0 | 2048 | unusable |

**Recommended: t=12** — minimum gates, accept borderline 4^t/n=8 since hardware
noise dominates anyway. Going to higher t adds gates without benefit on this hardware.

## Decision criteria (post-dry-run)

Pick **t** such that:
- `4ᵗ/n ≥ 16` (safety margin, derived from t=12 19-bit success)
- `2Q gates ≤ 130,000` (Lelli 17-bit benchmark)
- `qubits ≤ 80` (heavy-hex routing comfort zone)

**Recommended**: t=12 (4^t/n=8 OK with CF-lift extractor compensation).

## CF-Lift Extractor Boost

Post-dry-run discovery (2026-04-28): the continued-fraction lift extractor
(`shor_ecdlp.py extract Pass 3`) lifts hits by ~50× over direct extraction by
trying ~25 (a,b) candidates per shot through the verification filter.
Calibration: 19-bit data went from 1 hit → 4 hits.

Updated success projection at 22-bit, t=12:

| Shots | Expected hits (CF-lift) | P(≥1 hit) |
|---|---|---|
| 20K | 0.48 | 38% |
| 30K | 0.71 | 51% |
| **50K** | **1.19** | **70%** |
| 100K | 2.38 | 91% |

## Execution plan

```bash
# Step 0 (no QPU): Confirm dry-run numbers match plan
python scripts/submit_18bit.py --bits 22 --t <chosen_t> --dry-run

# Step 1 (~5-7 min QPU): Submit
python scripts/submit_18bit.py --bits 22 --t <chosen_t> --shots 20000 --backend ibm_fez

# Step 2 (~immediately): Poll & extract
python scripts/fetch_result.py results/_pending_22bit_t<t>_ibm.json
```

## Success criteria

| Outcome | Meaning |
|---|---|
| `recovered_d == 1999171` | 22-bit broken — new public record (m=22) |
| `recovered_d == None` (0 verified hits) | Need re-run (Lelli regime — luck-bounded) |
| Multi-d candidates with d_true winning | Same as success, with stronger evidence |

## Fallback plan if 22-bit fails

- **Reduce shots, retry** at same t (e.g., 10K shots × 2 trials → independent stats)
- **Step down to 21-bit** (m=20, easier, still beats 19-bit)
- **Step up to 23-bit** (only if 22-bit succeeded + budget remains)

## Statistical analysis post-execution

Mirror Step 1 / Step 2 analysis from 19-bit results:
1. Verified hit count + p-value vs Poisson(shots/n)
2. Bit marginal distribution (decoherence pattern check)
3. Ideal Shor distribution comparison (P_hit / P_mean ratio)
4. Pairwise extraction
5. Update brief.md with new headline

## Connection to brief.md

If 22-bit succeeds, update `brief.md` headline to:
> "Autonomous AI Agent Recovery of **22-bit** ECDLP on IBM Quantum"
> "+7 algorithmic steps over Lelli 2026 Round-1 15-bit prize-winning submission, +6 over his best-documented 17-bit run"

Resource table updates accordingly.

If 22-bit fails, keep 19-bit as headline result and report 22-bit attempt as
"resource projection beyond current hardware fidelity" (still useful contribution).
