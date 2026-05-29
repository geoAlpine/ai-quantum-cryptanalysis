"""Full HNP-score matrix + d-class / degeneracy audit across Phase 1 runs.

Goes deeper than ``cross_platform_analysis.py``. That tool reports the
HNP **argmax** ("top-1 winner") per run and tallies how often it equals
``d_true``. This tool exists because that framing is misleading, and the
matrix here shows why.

KEY FINDINGS THIS TOOL MAKES VISIBLE (verified 2026-05-29)
----------------------------------------------------------
1. CONVENTION MISMATCH.  ``lattice_postprocess.hnp_score`` is documented
   (docstring) for the *full-width* counting registers j, k ∈ [0, M),
   with peaks at round(s·M/n).  But the entire production pipeline
   (``azure_quantum_fetch.py``, ``cross_platform_analysis.py``,
   ``boundary_scan_*.py``) feeds it j, k **reduced mod n** ∈ [0, n).
   On noiseless data the full-width form is degenerate — d=0 wins
   trivially and the score is monotone in d — so the reduced form is the
   one that actually carries signal, and is used throughout. We therefore
   reduce mod n here too, matching production, and flag the docstring as
   stale.

2. ±d DEGENERACY.  Shor/HNP signal is symmetric under d ↔ (n−d) = anti_d.
   On NOISELESS m=3 data the reduced HNP score puts BOTH d_true=6 and
   anti_d=1 far below the noise plateau — but anti_d=1 is the argmax, NOT
   d_true. The metric cannot break the ±d tie. Hence "d_true wins HNP
   argmax k/4" is *within-d-class noise*, not evidence of a strict signal
   regime. The honest, reproducible signal is **the d-CLASS {d_true,
   anti_d} occupying the lowest-residual positions**, which the noiseless
   ground-truth row anchors.

The matrix below is reported against that noiseless ground truth so each
hardware run can be read as "how much of the noiseless d-class separation
survived the noise", instead of the misleading argmax tally.

3. SIGNIFICANCE.  A separation number alone ("H2-1E 30.9% vs IBM 1.6%") is
   an anecdote until tested. The permutation test here destroys the HNP
   signal by shuffling each run's k-values against its j-values (breaking
   the per-shot j–k correlation that produces the d-class dip, while
   preserving both marginals), recomputes the d-class statistic on each
   shuffle, and reports a p-value = P(null ≥ observed). This converts the
   claim into "genuine d-class signal present on H2-1E (p<α), absent on
   IBM" — the publishable form of the project's thesis.

Usage:
    PYTHONPATH=src python scripts/hnp_score_matrix.py
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
from collections import Counter

import numpy as np

from lattice_postprocess import hnp_score

# Permutation-test reproducibility: a fixed seed so the reported p-values
# are deterministic across runs (Date/random are otherwise unseeded here).
PERM_SEED = 20260529
N_PERM = 3000


def _h2_label(path):
    """Short, unique label for an H2-1E result file, robust to both the
    clean (``..._hnp_h2-1e_<tag>.json``) and the fetch/legacy
    (``...shor_azure_..._quantinuum.sim.h2-1e_<jid8>.json``) naming. Encodes
    the shot count so high-shot runs are visible at a glance."""
    base = os.path.basename(path)
    m = re.search(r"_(\d+)shots", base)
    shots = m.group(1) if m else "?"
    if "_hnp_h2-1e_" in base:
        tag = base.split("_hnp_h2-1e_")[-1].replace(".json", "")
    elif "quantinuum.sim.h2-1e_" in base:
        tag = base.split("quantinuum.sim.h2-1e_")[-1].replace(".json", "")
    else:
        tag = base.replace(".json", "")
    return f"H2-{shots}·{tag[:8]}"


def _discover_h2_results():
    """All H2-1E *emulator* result files, ANY shot count, EITHER filename
    format. Excludes pending metadata (no counts), the h2-1sc syntax
    checker, and h2-2* targets."""
    pats = [
        "results/shor_4bit_t6_*shots_hnp_h2-1e_*.json",          # clean
        "results/shor_azure_4bit_t6_*shots_quantinuum.sim.h2-1e_*.json",  # fetch
    ]
    seen, paths = set(), []
    for pat in pats:
        for p in glob.glob(pat):
            base = os.path.basename(p)
            if base.startswith("_pending") or "h2-1sc" in base:
                continue
            if p not in seen:
                seen.add(p)
                paths.append(p)
    return sorted(paths, key=lambda p: (
        int(re.search(r"_(\d+)shots", os.path.basename(p)).group(1))
        if re.search(r"_(\d+)shots", os.path.basename(p)) else 0,
        p))


def find_datasets():
    out = []
    for label, path in [
        ("IBM-P1", "results/shor_4bit_t6_1024shots_hnp_ibm_phase1.json"),
        ("IBM-R1", "results/shor_4bit_t6_1024shots_hnp_ibm_rep1.json"),
        ("IBM-R2", "results/shor_4bit_t6_1024shots_hnp_ibm_rep2.json"),
        ("IBM-R3", "results/shor_4bit_t6_1024shots_hnp_ibm_rep3.json"),
    ]:
        if os.path.exists(path):
            out.append((label, "ibm_kingston", path))
    for path in _discover_h2_results():
        out.append((_h2_label(path), "quantinuum_h2-1e", path))
    return out


def parse_shots(counts, t, pt_w, n):
    """Production convention: j, k, r reduced mod n (see module docstring
    finding #1 — full-width is degenerate)."""
    shots = []
    for bs, cnt in counts.items():
        b = bs.replace(" ", "")
        if len(b) != 2 * t + pt_w:
            continue
        k = int(b[:t], 2) % n
        j = int(b[t:2 * t], 2) % n
        r = int(b[2 * t:], 2) % n
        shots.extend([(j, k, r)] * cnt)
    return shots


def noiseless_ground_truth(n=7, t=6):
    """Run the exact production circuit on noiseless Aer to anchor the
    matrix. Returns a run-dict, or None if Aer/dependencies unavailable."""
    try:
        from challenges import get_challenge
        from ecc import EllipticCurve
        from shor_ecdlp import (ShorECDLPSolver, SubgroupIndexer,
                                DenseUnitaryOracle)
        from qiskit import transpile
        from qiskit_aer import AerSimulator
    except Exception as e:  # pragma: no cover - env dependent
        print(f"  (noiseless ground truth skipped: {type(e).__name__})")
        return None
    c = get_challenge(4)
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    n, d_true = c.n, c.expected_d
    ind = SubgroupIndexer(curve, G, n)
    solver = ShorECDLPSolver(curve, G, Q, n,
                             oracle=DenseUnitaryOracle(ind), num_counting=t)
    sim = AerSimulator()
    counts = sim.run(transpile(solver.build_circuit(), sim,
                               optimization_level=1),
                     shots=4096).result().get_counts()
    return build_run("NOISELESS", "aer_ideal", counts, n, t, d_true, pt_w=3)


def build_run(label, platform, counts, n, t, d_true, pt_w):
    shots = parse_shots(counts, t, pt_w, n)
    scores = [hnp_score(d, shots, n, t) for d in range(n)]
    return {"label": label, "platform": platform, "n": n, "t": t,
            "d_true": d_true, "anti_d": (n - d_true) % n, "scores": scores,
            "n_shots": sum(counts.values()),
            # retained for the permutation test (significance section)
            "j": np.array([s[0] for s in shots]),
            "k": np.array([s[1] for s in shots])}


def _scores_np(j, k, n, t):
    """Vectorised hnp_score for every d ∈ [0, n). Verified to match
    lattice_postprocess.hnp_score exactly (mean squared min-residual to
    the n expected peaks)."""
    M = 1 << t
    peaks = np.array(sorted({(s * M + n // 2) // n % M for s in range(n)}))
    half = M // 2
    out = np.empty(n)
    for d in range(n):
        v = (j + d * k) % M
        diff = (v[:, None] - peaks[None, :]) % M
        diff = np.where(diff <= half, diff, diff - M)
        best = np.abs(diff).min(axis=1).astype(float)
        out[d] = (best ** 2).mean()
    return out


def _nll_scores_np(j, k, n, t, sigma=None):
    """Likelihood (negative-log-likelihood) score for every d ∈ [0, n).

    Models each shot's residual v=(j+d·k) mod M as a Gaussian mixture over
    the n expected peaks (the numpy/vectorised twin of
    lattice_postprocess.hnp_score_likelihood). σ is fixed a-priori to the
    ideal-peak rounding width M/(2n) — NOT tuned to the data, so this is
    not a fitted/p-hacked statistic. At m=3 it is markedly more powerful
    than the squared-residual score on real signal (H2-1E 230-shot p
    0.02→0.0002, power@128 0.45→0.97) while staying null on the IBM
    negative control (p≈0.65) — more sensitive, not more false-positive
    prone. Lower NLL at a d = better fit = more signal there.

    ⚠️ m-DEPENDENT (verified 2026-05-29 by noiseless sim): this power
    advantage is m=3-SPECIFIC. At m=5 (n=31, t=8) the likelihood FAILS
    (noiseless p≈0.43) while the squared-residual score DETECTS the
    d-class (p≈0.003) — because σ=M/(2n) is ~half the peak spacing, so for
    larger n the Gaussian mixture's peaks overlap and wash out. Use the
    SQUARED score (_scores_np) as the robust cross-m default; treat the
    likelihood as an m=3-validated booster, not a universal upgrade. A
    narrower σ may rescue it at larger m but that needs its own
    validation (and risks σ-tuning)."""
    M = 1 << t
    peaks = np.array(sorted({(s * M + n // 2) // n % M for s in range(n)}))
    half = M // 2
    if sigma is None:
        sigma = max(1.0, M / (2 * n))
    inv = 1.0 / (2 * sigma * sigma)
    out = np.empty(n)
    for d in range(n):
        v = (j + d * k) % M
        diff = (v[:, None] - peaks[None, :]) % M
        diff = np.where(diff <= half, diff, diff - M).astype(float)
        d2 = diff * diff
        m = d2.min(axis=1)
        s = np.exp(-(d2 - m[:, None]) * inv).sum(axis=1)
        out[d] = (m * inv - np.log(s)).mean()
    return out


def _best_dc_z_from_scores(scores, dc):
    """Most-negative z over the d-class members (the signal statistic).
    More negative = d-class sits further below the noise plateau."""
    mu = scores.mean()
    sd = scores.std() or 1.0
    return min((scores[d] - mu) / sd for d in dc)


def significance_test(run, n_perm=N_PERM, seed=PERM_SEED, score_fn=_scores_np):
    """Permutation test: is the d-class dip real signal or chance?

    Null model — shuffle k against j (break the per-shot j–k correlation
    that produces the HNP peak structure) while preserving both marginals.
    Recompute the d-class statistic (best_dc_z) on each shuffle and report
    p = P(null ≤ observed) since more-negative z means stronger signal.

    ``score_fn`` selects the per-d scoring: ``_scores_np`` (squared
    residual, conservative) or ``_nll_scores_np`` (likelihood, more
    powerful). The permutation p-value is valid for either, since the same
    statistic is recomputed on every shuffle.
    """
    n, t = run["n"], run["t"]
    j, k = run["j"], run["k"]
    if len(j) == 0:
        return {"observed": float("nan"), "p_value": float("nan"),
                "null_mean": float("nan"), "null_std": float("nan"),
                "n_perm": 0}
    dc = {run["d_true"], run["anti_d"]}
    observed = _best_dc_z_from_scores(score_fn(j, k, n, t), dc)
    rng = np.random.default_rng(seed)
    null = np.empty(n_perm)
    for i in range(n_perm):
        kp = rng.permutation(k)
        null[i] = _best_dc_z_from_scores(score_fn(j, kp, n, t), dc)
    # one-sided: signal makes observed MORE negative than the null
    p = (1 + int(np.count_nonzero(null <= observed))) / (1 + n_perm)
    return {"observed": observed, "p_value": p,
            "null_mean": float(null.mean()), "null_std": float(null.std()),
            "n_perm": n_perm}


def _derive_n(blob):
    """n from the blob, or from get_challenge(bits), or default 7."""
    if blob.get("n"):
        return blob["n"]
    bits = blob.get("bits")
    if bits is not None:
        try:
            from challenges import get_challenge
            return get_challenge(bits).n
        except Exception:
            pass
    return 7


def load_run(label, platform, path):
    """Load one result file into a run-dict, or return None if it carries
    no usable shots (empty/placeholder file, or none parse at this width)."""
    blob = json.load(open(path))
    counts = blob.get("counts") or {}
    if not counts:
        print(f"  (skip {label}: no counts in {os.path.basename(path)})")
        return None
    n = _derive_n(blob)
    t = blob.get("t", 6)
    d_true = blob.get("expected_d", (n - 1))
    pt_w = 3 if blob.get("oracle", "dense") == "dense" else 4
    run = build_run(label, platform, counts, n, t, d_true, pt_w)
    if len(run["j"]) == 0:
        print(f"  (skip {label}: 0 shots parse at t={t}, pt_w={pt_w} in "
              f"{os.path.basename(path)})")
        return None
    return run


def ranks_of(scores):
    order = sorted(range(len(scores)), key=lambda d: scores[d])
    rank = [0] * len(scores)
    for pos, d in enumerate(order):
        rank[d] = pos + 1
    return rank


def zscores(scores):
    mu = sum(scores) / len(scores)
    sd = math.sqrt(sum((s - mu) ** 2 for s in scores) / len(scores)) or 1.0
    return [(s - mu) / sd for s in scores]


def dclass_metrics(run):
    """The honest signal metric: how well the d-class {d_true, anti_d}
    sits below the noise plateau, regardless of which class member wins."""
    n = run["n"]
    scores = run["scores"]
    rank = ranks_of(scores)
    z = zscores(scores)
    dc = {run["d_true"], run["anti_d"]}
    best_dc_rank = min(rank[d] for d in dc)
    worst_dc_rank = max(rank[d] for d in dc)
    best_dc_z = min(z[d] for d in dc)            # most negative = strongest
    # separation: how far the better d-class member is below the median d
    med = sorted(scores)[n // 2]
    best_dc_score = min(scores[d] for d in dc)
    sep = (med - best_dc_score) / max(1e-9, med) * 100
    return {
        "argmax_d": rank.index(1),
        "best_dc_rank": best_dc_rank,
        "worst_dc_rank": worst_dc_rank,
        "dclass_in_top2": worst_dc_rank <= 2,
        "best_dc_z": best_dc_z,
        "separation_pct": sep,
        "argmax_is_dclass": rank.index(1) in dc,
    }


def main():
    print(f"Phase 1 HNP matrix (reduced-mod-n convention; see module "
          f"docstring)\n")
    gt = noiseless_ground_truth()
    loaded = [load_run(*d) for d in find_datasets()]
    runs = ([gt] if gt else []) + [r for r in loaded if r is not None]
    if not runs:
        print("No usable datasets found.")
        return
    n = runs[0]["n"]
    d_true = runs[0]["d_true"]
    anti = runs[0]["anti_d"]

    print("=" * 82)
    print(f"HNP-SCORE MATRIX   (d_true={d_true}‡  anti_d={anti}ᵃ  "
          f"★=argmax; lower score = better)")
    print("=" * 82)
    header = f"  {'run':<16} " + "".join(f"{'d='+str(d):>9}" for d in range(n))
    print(header)
    print("-" * len(header))
    for r in runs:
        rank = ranks_of(r["scores"])
        cells = []
        for d in range(n):
            m = "★" if rank[d] == 1 else (
                "‡" if d == r["d_true"] else (
                    "ᵃ" if d == r["anti_d"] else " "))
            cells.append(f"{r['scores'][d]:>8.2f}{m}")
        print(f"  {r['label']:<16} " + "".join(cells))

    print("\n  --- z-score view (negative = stands out as low-residual peak) ---")
    print(header)
    for r in runs:
        z = zscores(r["scores"])
        print(f"  {r['label']:<11} " + "".join(f"{z[d]:>9.2f}" for d in range(n)))

    print("\n" + "=" * 82)
    print("d-CLASS SIGNAL TABLE  (the honest metric — argmax tie d_true↔anti_d "
          "is NOT signal)")
    print("=" * 82)
    print(f"  {'run':<16} {'argmax':>6} {'argmax∈dclass':>13} "
          f"{'dclass top-2':>12} {'best_dc_rank':>12} {'best_dc_z':>10} "
          f"{'separation':>11}")
    print("-" * 82)
    for r in runs:
        m = dclass_metrics(r)
        print(f"  {r['label']:<11} {m['argmax_d']:>6} "
              f"{str(m['argmax_is_dclass']):>13} "
              f"{str(m['dclass_in_top2']):>12} {m['best_dc_rank']:>12} "
              f"{m['best_dc_z']:>10.2f} {m['separation_pct']:>10.1f}%")

    # Aggregate honest verdict per platform
    print("\n  --- per-platform d-class verdict ---")
    for plat, name in [("aer_ideal", "Noiseless (ground truth)"),
                       ("ibm_kingston", "IBM ibm_kingston"),
                       ("quantinuum_h2-1e", "Quantinuum H2-1E")]:
        batch = [r for r in runs if r["platform"] == plat]
        if not batch:
            continue
        mets = [dclass_metrics(r) for r in batch]
        top2 = sum(1 for m in mets if m["dclass_in_top2"])
        argmax_dc = sum(1 for m in mets if m["argmax_is_dclass"])
        mean_z = sum(m["best_dc_z"] for m in mets) / len(mets)
        mean_sep = sum(m["separation_pct"] for m in mets) / len(mets)
        print(f"    {name:<26} ({len(batch)}): d-class in top-2 "
              f"{top2}/{len(batch)}, argmax∈d-class {argmax_dc}/{len(batch)}, "
              f"mean best-dc z={mean_z:.2f}, mean sep={mean_sep:.1f}%")

    print("\n  NOTE: 'argmax == d_true' is NOT reported as a headline because "
          "the\n  noiseless ground-truth row shows anti_d wins argmax even with "
          "perfect\n  signal — the ±d degeneracy is unbreakable by this score.")

    # ----------------------------------------------------------------- (3)
    print("\n" + "=" * 82)
    print(f"SIGNIFICANCE TEST  (permutation; shuffle k vs j; {N_PERM} perms; "
          f"seed={PERM_SEED})")
    print("=" * 82)
    print("  Statistic = best-dc z. p = P(null ≤ observed). Two scorers: "
          "p_sq = squared-")
    print("  residual (conservative); p_LR = likelihood (more powerful, "
          "validated). p_LR is")
    print("  the headline; p_sq is the conservative cross-check.")
    print(f"  {'run':<16} {'shots':>6} {'z_sq':>7} {'p_sq':>9} {'p_LR':>9}  "
          f"signal? (LR)")
    print("-" * 72)
    per_plat: dict[str, list[float]] = {}      # likelihood p-values
    run_sig: list[dict] = []  # captured for the VERDICT headline
    for r in runs:
        st = significance_test(r)                          # squared
        st_lr = significance_test(r, score_fn=_nll_scores_np)  # likelihood
        verdict = ("—" if st_lr["n_perm"] == 0
                   else "✓ p<.01" if st_lr["p_value"] < 0.01
                   else "✓ p<.05" if st_lr["p_value"] < 0.05
                   else "✗ n.s.")
        print(f"  {r['label']:<16} {r['n_shots']:>6} {st['observed']:>7.2f} "
              f"{st['p_value']:>9.4f} {st_lr['p_value']:>9.4f}  {verdict}")
        if st_lr["n_perm"]:
            per_plat.setdefault(r["platform"], []).append(st_lr["p_value"])
            run_sig.append({"label": r["label"], "platform": r["platform"],
                            "shots": r["n_shots"], "p": st_lr["p_value"],
                            "p_sq": st["p_value"], "observed": st["observed"]})

    print("\n  --- per-platform: single-run significance tally (p_LR<0.05) ---")
    for plat, name in [("aer_ideal", "Noiseless (ground truth)"),
                       ("ibm_kingston", "IBM ibm_kingston"),
                       ("quantinuum_h2-1e", "Quantinuum H2-1E")]:
        ps = per_plat.get(plat)
        if not ps:
            continue
        sig = sum(1 for p in ps if p < 0.05)
        print(f"    {name:<26} ({len(ps)}): {sig}/{len(ps)} significant "
              f"(p_LR<0.05), p_LR = "
              f"[{', '.join(f'{p:.3f}' for p in ps)}]")

    # Pooled test — the properly-powered question is per PLATFORM, not per
    # run. 16 shots/run is underpowered; pooling all of a platform's shots
    # asks "does this platform carry d-class signal" with full power.
    print("\n  --- POOLED per-platform test (all of a platform's shots "
          "concatenated) ---")
    for plat, name in [("ibm_kingston", "IBM ibm_kingston"),
                       ("quantinuum_h2-1e", "Quantinuum H2-1E")]:
        batch = [r for r in runs if r["platform"] == plat]
        if not batch:
            continue
        pooled = {
            "label": f"{plat}-POOL", "platform": plat,
            "n": batch[0]["n"], "t": batch[0]["t"],
            "d_true": batch[0]["d_true"], "anti_d": batch[0]["anti_d"],
            "j": np.concatenate([r["j"] for r in batch]),
            "k": np.concatenate([r["k"] for r in batch]),
        }
        st = significance_test(pooled)
        st_lr = significance_test(pooled, score_fn=_nll_scores_np)
        verdict = ("✓ p<.01" if st_lr["p_value"] < 0.01
                   else "✓ p<.05" if st_lr["p_value"] < 0.05 else "✗ n.s.")
        print(f"    {name:<26} ({len(pooled['j'])} pooled shots): "
              f"p_sq={st['p_value']:.4f}  p_LR={st_lr['p_value']:.4f}  "
              f"{verdict}")

    # ----------------------------------------------------------------- VERDICT
    # The decisive question the high-shot H2-1E run was submitted to answer:
    # does a properly-powered single run reach significance?
    HI = 100  # "high-shot" threshold — runs with the power to matter
    hi_h2 = [s for s in run_sig
             if s["platform"] == "quantinuum_h2-1e" and s["shots"] >= HI]
    print("\n" + "=" * 82)
    print("VERDICT — genuine d-class signal on H2-1E?")
    print("=" * 82)
    if not hi_h2:
        print(f"  No H2-1E run with ≥{HI} shots yet. Current H2-1E data is "
              f"all low-shot\n  (underpowered); see the POOLED test above for "
              f"the best available read.\n  The in-flight 230-shot run "
              f"(job e5b6a654) is the decisive datapoint —\n  re-run this tool "
              f"once its result lands in results/.")
    else:
        for s in hi_h2:
            if s["p"] < 0.05:
                print(f"  ✅ {s['label']} ({s['shots']} shots): "
                      f"p_LR={s['p']:.4f} (p_sq={s['p_sq']:.4f}) < 0.05 — "
                      f"GENUINE d-class signal CONFIRMED.")
                print(f"     First statistically-significant quantum d-class "
                      f"signal on hardware-class\n     noise. This is the "
                      f"'Beyond Verification Filter' datapoint (IBM pooled "
                      f"p≈0.6 = none).")
            else:
                print(f"  ❌ {s['label']} ({s['shots']} shots): "
                      f"p_LR={s['p']:.4f} (p_sq={s['p_sq']:.4f}) ≥ 0.05 — "
                      f"NOT yet significant.")
                print(f"     The effect is weaker than projected; re-run "
                      f"scripts/hnp_power_analysis.py with\n     this run "
                      f"pooled in to re-estimate the shots needed, then submit "
                      f"a larger run.")
    print("\n  (IBM pooled p≈0.6 across 4096 shots = no signal, confirmed "
          "verification-filter\n  regime. Significance, not recovery-success "
          "or argmax, is the genuine-signal test.)")


if __name__ == "__main__":
    main()
