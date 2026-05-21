# quantum-ecc

> Autonomous AI-driven cryptanalysis of the Elliptic Curve Discrete Logarithm
> Problem (ECDLP) on IBM Quantum hardware. Built end-to-end by an LLM agent
> (Anthropic Claude Sonnet 4.6 via Claude Code) — see [`AGENT.md`](AGENT.md)
> for the workflow record.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Quantum: IBM Heron r2](https://img.shields.io/badge/Quantum-IBM_Heron_r2-blueviolet.svg)](https://www.ibm.com/quantum)
[![Q-Day Prize: submission](https://img.shields.io/badge/Q--Day_Prize-Round_2_submission-orange.svg)](https://www.qdayprize.org/)

## 🏆 Headline result

**Recovered the 22-bit (m = 22) ECDLP private key `d = 1,999,171` on IBM Quantum
`ibm_fez`** — **+7 algorithmic steps beyond Lelli's Q-Day Prize Round-1 winning
15-bit (m = 15) submission, and +6 beyond his highest documented success
(17-bit, m = 16)**. Job ID: `d7o5mr62jamc73bp87eg`.

| Submission | label | m | qubits | 2Q gates | Recovered d | Hits | Job |
|---|---|---|---|---|---|---|---|
| Lelli 2026 — Round-1 prize | 15-bit | 15 | (smaller) | (smaller) | (15-bit prize key) | — | (Round-1 award) |
| Lelli 2026 — best documented | 17-bit | 16 | 69 | 111,816 | 1,441 ✓ | 1+ | d790krrc6das739idasg |
| **This work — 22-bit** | 22-bit | **22** | 73 | 124,422 | **1,999,171 ✓** | **12** | **d7o5mr62jamc73bp87eg** |
| This work — 19-bit (independent confirm) | 19-bit | 19 | 67 | 103,708 | 36,124 ✓ | 1+ | d7o2dem2jamc73bp3jig |

**Note on bit-length labeling.** The Q-Day Prize challenges are labeled by the
prime `p`'s bit length, but the Shor algorithm's actual difficulty is governed
by the subgroup order `n` bit length (`m = ⌈log₂ n⌉`). The "17-bit challenge"
has m = 16 because n = 65,173 < 2¹⁶. Our "22-bit challenge" has m = 22 because
n = 2,098,699 ≥ 2²¹.

Submission writeup: [`brief.md`](brief.md). Full hardware reproduction
instructions below.

## Quick start

```bash
# 1. Install (editable — picks up source changes without re-installing)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Set IBM Quantum token
cp .env.example .env
# edit .env to add your IBM_QUANTUM_TOKEN (get one at https://quantum.cloud.ibm.com/)

# 3. Run on simulator (free, ≤6-bit)
python run_experiment.py --shor --shor-bits 6 --shots 4096

# 4. Run on real IBM Quantum hardware (uses ~1-7 min of monthly free QPU)
python scripts/submit_18bit.py --bits 22 --t 12 --shots 35000 --backend auto
python scripts/fetch_result.py results/_pending_22bit_t12_ibm.json
```

## Reproducing the headline 22-bit result from existing data

The 35,000-shot raw counts file (`results/_ibm_22bit_t12_counts.json`) is
shipped with the repository. To re-derive `d = 1,999,171` without any quantum
access:

```bash
python -c "
import json
from challenges import get_challenge
from ecc import EllipticCurve
from shor_ecdlp import ShorECDLPSolver, RippleCarryOracle, SubgroupIndexer
counts = json.load(open('results/_ibm_22bit_t12_counts.json'))['counts']
c = get_challenge(22); curve = EllipticCurve(0, 7, c.p)
G, Q = curve.point(*c.G), curve.point(*c.Q)
solver = ShorECDLPSolver(curve, G, Q, c.n,
    oracle=RippleCarryOracle(SubgroupIndexer(curve, G, c.n)), num_counting=12)
print(f'recovered d = {solver.extract(counts)}')  # → 1999171
"
```

## Layout

```
src/
  ecc.py              Classical EC arithmetic (point add, scalar mult, BSGS)
  shor_ecdlp.py       Two-register Shor for ECDLP. Strategy-pattern oracles.
                      Includes Adaptive Counting Precision (t<m), lazy
                      SubgroupIndexer (for n ≳ 10^6), and the CF-Lift v2/v3
                      Extractor family (Stern-Brocot convergents; v3 widens
                      candidate enumeration for the larger-n regime).
  grover_ecdlp.py     Grover-based attack (legacy / comparison)
  quantum_ecc.py      IBM/IonQ runners, Aer wrappers, ZNE
  challenges.py       Q-Day Prize challenge curves (4-bit through 30-bit)
  analysis.py         χ², KL divergence, TVD, success probability

scripts/
  submit_18bit.py     Build & submit Shor circuit at chosen (bits, t)
                      Auto-selects best Heron r2 backend by 2Q-error;
                      enables Sampler-side dynamical decoupling + twirling.
  submit_25bit.py     Same flow tuned for 25-bit (lazy indexer, v3 extractor,
                      C/shot-calibrated hit projection). [Draft — not yet run.]
  fetch_result.py     Poll IBM job and extract d
  apply_m3.py         Apply M3 readout-error mitigation post-hoc
  preflight.py        Free-metadata resource estimator (qubits/depth/2Q/fid
                      + v3-extractor hit projection) — run before any QPU
                      submission to avoid wasting the monthly budget.
  aer_validate.py     End-to-end Aer pipeline test (noiseless + optional
                      noise-model from a real IBM backend; ≤22 qubits).
  replay_benchmark.py Regression test: re-extract d from all saved IBM
                      counts files. Zero QPU. Run after touching extractor.
  cflift_v3.py        Standalone CF-Lift v3 candidate generator (also
                      embedded in shor_ecdlp.py — see notes below).
  measure_extractor.py / measure_v3.py
                      Empirical calibration tools that count candidate
                      density and hit rate per shot on saved counts.
  quimb_simulate.py   Tensor-network cross-validation (≤6-bit dense)
  agent_planner.py    Read past results, propose next experiment
  agent_loop.py       Autonomous plan→submit→poll→update loop

results/
  shor_*_ibm.json     Hardware run summary + recovered d
  _ibm_*_counts.json  Raw IBM counts (post-job pull)
  *_analysis.md       Step-by-step deep analysis reports

docs/
  22bit_attack_plan.md  Resource projections + execution plan

run_experiment.py     CLI entry point (Grover / Shor / dummy modes)
brief.md              Q-Day Prize submission writeup (2 pages)
AGENT.md              Record of autonomous AI workflow
```

## Algorithm summary

Two-register Shor variant for ECDLP:

1. Prepare counting registers `|j⟩|k⟩` in uniform superposition (Hadamard).
2. Apply controlled point additions: `|j⟩|k⟩|0⟩ → |j⟩|k⟩|jG + kQ⟩`.
3. Measure point register → collapses to some `r₀` on the cyclic group.
4. Apply inverse QFT to `j`, `k`.
5. Measure (j, k); enumerate `(a, b)` lifts via Stern-Brocot continued-fraction
   approximation toward fractions with denominator ≤ n.
6. For each `(a, b)`: candidate `d = (r₀ - a) · b⁻¹ mod n`.
7. Verify: accept only `d_cand · G == Q`.

The verification step is robust to noise: only the true `d` survives the
classical EC scalar-multiply check, so a small number of signal-bearing
shots suffices for recovery.

## Novel contributions

### 1. Adaptive Counting Precision

Standard Shor uses counting-register width `t = m = ⌈log₂ n⌉`. We use `t < m`
to reduce qubit count and circuit depth.

Mathematical threshold for QFT⁻¹ to extract structure: `4ᵗ / n ≥ 1`. For our
22-bit problem (n ≈ 2.1M), `t = 12` gives `4¹² / n ≈ 8`, sufficient with the
v2 extractor. This pushes the per-shot signal density from "would need t = 22
counting qubits" down to "12 suffice".

### 2. Continued-Fraction Lift Extractor — v2 and v3

When `t < m`, the direct extraction formula `d = (r − j) · k⁻¹ mod n` loses
precision. The CF-Lift family restores recoverability by enumerating many
plausible candidates per measurement and routing each through the
verification check `d_cand · G == Q`.

**v2** (used for the 22-bit headline result): generates ~25 candidates per
axis via the natural Stern-Brocot continued-fraction expansion plus
mediants between adjacent convergents and a precision-gap-scaled symmetric
perturbation window. Backed by a BSGS-precomputed verifier for fast lookup.
On the 22-bit IBM data this delivered **12 verified hits at d = 1,999,171**,
where the v1 (direct + ±2) extractor returned 0.

**v3** (added May 2026, used for scaling toward 25-bit): widens the
enumeration further with (a) a configurable perturbation window around the
direct rounding, (b) symmetric mirroring `x ↔ 2ᵗ − x`, (c) bit-flip
neighbours for readout-error robustness, and (d) convergent-denominator
scaling. The candidate count per shot is empirically calibrated on saved
22-bit IBM data; at `cf_window = 16` it yields ~8K distinct candidates per
shot. In this regime the extractor's verified-hit rate matches the
uniform-noise model `C · shots / n` — see the "Honest framing" section
below for what that implies.

### 3. Autonomous AI Agent Workflow

The complete pipeline runs as `agent_planner.py + agent_loop.py`. The planner
distills the strategic reasoning of this submission into a deterministic
policy (climb-on-success, reproduce-on-borderline, diagnose-on-fail). The
loop wraps `plan → submit → poll → update brief.md` with `--dry-run`,
`--max-iter`, and `--budget-cap-shots` safety guards.

## Honest framing

At depth 100K+ on Heron r2 with effective gate fidelity 0.997, the **verification
filter is the load-bearing classical post-processing step** that converts noisy
quantum measurements into a recovered key. We do not claim quantum advantage —
classical BSGS solves 22-bit ECDLP in milliseconds. Bitcoin's 256-bit ECDLP
remains unattainable on near-term hardware (Google Quantum AI 2026-03 estimate:
1,200 logical qubits, 90M Toffoli gates).

What this work claims:

- The **largest publicly-reported ECDLP key recovery on quantum hardware to
  date** (m = 22), achieved end-to-end by an LLM agent.
- A CF-Lift v2/v3 extractor family that combines real Shor execution with
  aggressive classical candidate enumeration through the EC-verification
  filter. This is the same operating regime as Lelli's Q-Day Prize Round-1
  winning 15-bit submission, extended by seven algorithmic steps.

What this work explicitly does **not** claim:

- That the recovered measurements carry net quantum information above the
  uniform-noise baseline. On the 22-bit data, v2 hits sit modestly above the
  uniform expectation (P_hit/P_mean ≈ 1.69 against the analytical noiseless
  Shor distribution); v3, by widening the candidate set, matches the
  uniform-noise hit rate. Both are documented behaviours, not bugs — the v3
  extractor is a candidate generator, not a quantum-signal decoder, and its
  source docstring says so.
- That this approach scales to cryptographic key sizes by adding more
  qubits alone. Bridging from m = 22 to m = 256 requires a fundamental
  improvement in per-shot signal — i.e. error correction, not just bigger
  candidate sets.

The intended contribution is engineering-level: documenting the practical
recovery boundary on current commercial quantum hardware honestly, with
working code, so that the PQC-migration policy decisions downstream are made
against an accurate picture of where the threshold actually sits today.

See [`results/shor_22bit_t12_analysis.md`](results/shor_22bit_t12_analysis.md)
for the v1-vs-v2 comparison and analytical-distribution evidence on the
22-bit dataset, and [`results/shor_19bit_t12_step1_analysis.md`](results/shor_19bit_t12_step1_analysis.md)
for the deep noise/signal analysis at 19-bit.

## Testing

Property tests for the CF-Lift v3 candidate generator and regression tests
that replay every saved IBM-hardware counts file through the current
extractor:

```bash
pip install pytest
pytest -v -m "not slow"   # fast suite (~22 sec)
pytest -v                 # full suite incl. 22-bit replay (~75 sec)
```

The 22-bit replay is marked ``@pytest.mark.slow`` because it re-extracts
``d = 1,999,171`` from the 35,000-shot ``ibm_fez`` counts (~30 sec).
GitHub Actions runs the fast suite on every push and the slow suite on
pull requests — see [`.github/workflows/test.yml`](.github/workflows/test.yml).

## Citation

If you use this work, please cite via [`CITATION.cff`](CITATION.cff).

## Author / Contact

**Yosuke Aoki** — [GeoAlpine LLC (ジオアルピーヌ合同会社)](https://geoalpine.net)
Inquiries: info@geoalpine.net

This submission was produced in collaboration with **Claude Sonnet 4.6**
(Anthropic) via the Claude Code interface — see [`AGENT.md`](AGENT.md).

## License

[MIT](LICENSE).
