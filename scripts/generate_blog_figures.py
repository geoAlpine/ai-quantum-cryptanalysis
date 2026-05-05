"""
Generate WordPress blog figures for Project AQUA introduction post.

Outputs 3 PNGs into results/figures/:
  - fig2_bitcoin_gap.png    : Bit-length vs classical-difficulty (log scale),
                              showing AQUA's current reach (4/19/22-bit) and
                              the gap to Bitcoin (256-bit).
  - fig3_resource_scaling.png : qubits and 2Q-gate counts of actual IBM Quantum
                                runs (Lelli 17-bit + AQUA 4/19/22-bit).
  - fig5_hit_position.png   : ideal Shor distribution, with the verified
                              19-bit hit's position vs the would-be peak.

Run:
    python scripts/generate_blog_figures.py
"""
from __future__ import annotations

import os

import matplotlib.pyplot as plt
import numpy as np

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "figures")
os.makedirs(OUT_DIR, exist_ok=True)

AQUA_BLUE = "#1f9bb8"
AQUA_DARK = "#0f3a4a"
AQUA_ACCENT = "#e8743b"
GRID_GREY = "#d8dde2"

plt.rcParams.update({
    "font.family": ["Hiragino Sans", "Hiragino Maru Gothic Pro", "DejaVu Sans"],
    "font.size": 12,
    "axes.titlesize": 14,
    "axes.labelsize": 12,
    "axes.edgecolor": AQUA_DARK,
    "axes.labelcolor": AQUA_DARK,
    "xtick.color": AQUA_DARK,
    "ytick.color": AQUA_DARK,
    "axes.grid": True,
    "grid.color": GRID_GREY,
    "grid.linewidth": 0.5,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.dpi": 160,
    "savefig.bbox": "tight",
})


def fig2_bitcoin_gap():
    """Horizontal bar chart of difficulty milestones from 4-bit to Bitcoin 256-bit."""
    # (bits, label, color, family)
    rows = [
        (4,   "AQUA 4-bit  (動作確認)",                            AQUA_BLUE,   "aqua"),
        (15,  "Lelli 15-bit  (Q-Day Prize Round 1 受賞)",          "#9aa0a6",   "lelli"),
        (17,  "Lelli 17-bit  (Lelli 最大)",                        "#9aa0a6",   "lelli"),
        (19,  "AQUA 19-bit  (独立検証)",                           AQUA_BLUE,   "aqua"),
        (22,  "AQUA 22-bit  (現在の公開最大)",                     AQUA_DARK,   "aqua_best"),
        (256, "Bitcoin secp256k1  (実用ECDLP)",                    AQUA_ACCENT, "btc"),
    ]
    bits = [r[0] for r in rows]
    labels = [r[1] for r in rows]
    colors = [r[2] for r in rows]
    cost = [2 ** (b / 2) for b in bits]

    fig, ax = plt.subplots(figsize=(11, 5.5))
    y_pos = np.arange(len(rows))
    bars = ax.barh(y_pos, cost, color=colors, edgecolor=AQUA_DARK, linewidth=1.0,
                   height=0.62)

    ax.set_xscale("log")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=11)
    ax.invert_yaxis()
    ax.set_xlabel("古典 BSGS のおおよその計算ステップ数  (∝ 2^{m/2}, log scale)")
    ax.set_title("Project AQUA の現在地と Bitcoin (secp256k1) との隔たり",
                 color=AQUA_DARK, weight="bold", pad=12)
    ax.set_xlim(1, 1e42)

    note = {
        4:   "数ミリ秒",
        15:  "<1秒",
        17:  "<1秒",
        19:  "数秒",
        22:  "数十秒",
        256: "古典では永遠に解けない (10^38 ステップ)",
    }
    for bar, b in zip(bars, bits):
        x = bar.get_width()
        ax.text(x * 1.6, bar.get_y() + bar.get_height() / 2,
                f"2^{b//2}{'' if b%2==0 else '.5'} ≈ " + (f"{int(2**(b/2)):,}" if b <= 32 else f"{2**(b/2):.1e}")
                + f"   古典: {note[b]}",
                va="center", fontsize=9, color=AQUA_DARK)

    ax.axhspan(-0.5, 4.5, color=AQUA_BLUE, alpha=0.05, zorder=0)
    ax.axhspan(4.5, 5.5, color=AQUA_ACCENT, alpha=0.07, zorder=0)
    ax.tick_params(axis="y", length=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    out = os.path.join(OUT_DIR, "fig2_bitcoin_gap.png")
    plt.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def fig3_resource_scaling():
    """Bar chart: qubits and 2Q gates for actual IBM Quantum runs."""
    runs = [
        ("Lelli 17-bit\n(m=16, t=m)",  69, 111_816, "#a0a0a0"),
        ("AQUA 19-bit\n(m=19, t=12)",  67, 103_708, AQUA_BLUE),
        ("AQUA 22-bit\n(m=22, t=12)",  73, 124_422, AQUA_BLUE),
    ]
    labels = [r[0] for r in runs]
    qubits = [r[1] for r in runs]
    gates = [r[2] for r in runs]
    colors = [r[3] for r in runs]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))

    x = np.arange(len(labels))
    bars1 = ax1.bar(x, qubits, color=colors, edgecolor=AQUA_DARK, linewidth=1.2)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=10)
    ax1.set_ylabel("Qubits")
    ax1.set_title("使用量子ビット数", weight="bold", color=AQUA_DARK)
    for bar, val in zip(bars1, qubits):
        ax1.text(bar.get_x() + bar.get_width() / 2, val + 0.7, str(val),
                 ha="center", fontsize=11, color=AQUA_DARK, weight="bold")
    ax1.set_ylim(0, max(qubits) * 1.15)

    bars2 = ax2.bar(x, gates, color=colors, edgecolor=AQUA_DARK, linewidth=1.2)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=10)
    ax2.set_ylabel("2-qubit gates (transpiled)")
    ax2.set_title("2量子ビットゲート数", weight="bold", color=AQUA_DARK)
    for bar, val in zip(bars2, gates):
        ax2.text(bar.get_x() + bar.get_width() / 2, val + 1500, f"{val:,}",
                 ha="center", fontsize=10, color=AQUA_DARK, weight="bold")
    ax2.set_ylim(0, max(gates) * 1.15)

    fig.suptitle("IBM Quantum ibm_fez 実機リソース  (大きい問題でも 2Q ゲート数が増えにくい)",
                 fontsize=13, weight="bold", color=AQUA_DARK, y=1.02)
    plt.tight_layout()

    out = os.path.join(OUT_DIR, "fig3_resource_scaling.png")
    plt.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def fig5_hit_position():
    """Bar chart: ideal Shor probabilities at peak / uniform / hit's actual position.

    Numbers from results/shor_19bit_t12_step1_analysis.md (verified hit at r₀=132466).
    """
    peak_p = 1.455e-11
    uniform_p = 2.27e-13
    hit_p = 1.835e-14

    labels = [
        "理想ピーク位置\n(量子信号があれば\nここに集中する)",
        "一様乱数の期待値\n(信号ゼロの場合)",
        "実機ヒットが\n落ちた位置",
    ]
    values = [peak_p, uniform_p, hit_p]
    colors = [AQUA_DARK, "#a0a0a0", AQUA_ACCENT]

    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(labels))
    bars = ax.bar(x, values, color=colors, edgecolor=AQUA_DARK, linewidth=1.2, width=0.55)
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("理想 Shor 分布における確率 (log)")
    ax.set_title("19-bit `d=36124` ヒットは Shor ピークではなく分布の谷に落ちた",
                 weight="bold", color=AQUA_DARK)

    annot = [
        f"P = {peak_p:.2e}\n= 64× uniform",
        f"P = {uniform_p:.2e}",
        f"P = {hit_p:.2e}\n= 0.081× uniform",
    ]
    for bar, txt in zip(bars, annot):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() * 1.4,
                txt, ha="center", fontsize=10, color=AQUA_DARK)

    ax.axhline(uniform_p, color="#a0a0a0", linestyle="--", linewidth=1, alpha=0.7, zorder=0)
    ax.text(2.55, uniform_p * 1.1, "uniform", color="#a0a0a0", fontsize=9, ha="right")

    ax.set_ylim(1e-15, 1e-10)
    ax.text(0.5, 0.97,
            "  → 量子信号による復元ではなく、検証フィルタによる候補選別が機構  ",
            transform=ax.transAxes, ha="center", va="top", fontsize=10,
            color=AQUA_DARK, style="italic",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#fff5ec",
                      edgecolor=AQUA_ACCENT, linewidth=1))

    plt.tight_layout()
    out = os.path.join(OUT_DIR, "fig5_hit_position.png")
    plt.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    fig2_bitcoin_gap()
    fig3_resource_scaling()
    fig5_hit_position()
    print(f"\nAll figures written to {OUT_DIR}/")
