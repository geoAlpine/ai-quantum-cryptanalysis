"""
Generate WordPress blog figures for Project AQUA introduction post.

Outputs 5 PNGs into results/figures/:
  - fig1_keyvisual.png      : Project AQUA hero image (mountains + water +
                              wordmark). Brand-style placeholder; can be
                              replaced by a designer's version later.
  - fig2_bitcoin_gap.png    : Bit-length vs classical-difficulty (log scale),
                              showing AQUA's current reach (4/19/22-bit) and
                              the gap to Bitcoin (256-bit).
  - fig3_resource_scaling.png : qubits and 2Q-gate counts of actual IBM Quantum
                                runs (Lelli 17-bit + AQUA 4/19/22-bit).
  - fig4_flow.png           : AI-agent autonomous-execution flow. Color-coded
                              by Claude vs human role.
  - fig5_hit_position.png   : ideal Shor distribution, with the verified
                              19-bit hit's position vs the would-be peak.

Run:
    python scripts/generate_blog_figures.py
"""
from __future__ import annotations

import os

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch, Rectangle

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


def fig1_keyvisual():
    """Project AQUA hero image: mountains + water + wordmark.

    Free aspect ratio (not OG-image sized). Placeholder-quality; intended
    to be redrawn by a designer for production use.
    """
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Sky / atmosphere gradient (top dark teal -> bottom light)
    sky = LinearSegmentedColormap.from_list(
        "aqua_sky", ["#0a2230", "#155265", "#1f9bb8", "#bfe3ed"]
    )
    grad = np.linspace(1, 0, 256).reshape(-1, 1)
    ax.imshow(grad, extent=(0, 1, 0, 1), aspect="auto", cmap=sky, zorder=0)

    # Far mountain ridge (lighter, hazy)
    mtn_far = np.array([
        [0.00, 0.40], [0.08, 0.48], [0.18, 0.42], [0.28, 0.55],
        [0.40, 0.46], [0.52, 0.58], [0.65, 0.45], [0.78, 0.52],
        [0.90, 0.43], [1.00, 0.50], [1.00, 0.0], [0.0, 0.0],
    ])
    ax.fill(mtn_far[:, 0], mtn_far[:, 1], color="#1d4d5c", alpha=0.55, zorder=1)

    # Near mountain ridge (darker, sharper)
    mtn_near = np.array([
        [0.00, 0.28], [0.10, 0.42], [0.22, 0.30], [0.36, 0.50],
        [0.48, 0.32], [0.58, 0.45], [0.72, 0.30], [0.86, 0.40],
        [1.00, 0.30], [1.00, 0.0], [0.0, 0.0],
    ])
    ax.fill(mtn_near[:, 0], mtn_near[:, 1], color="#0f3a4a", alpha=0.92, zorder=2)

    # Snow caps on a couple of peaks (small triangles near peak tops)
    for px, py in [(0.10, 0.42), (0.36, 0.50), (0.86, 0.40)]:
        snow = np.array([[px - 0.02, py - 0.02], [px, py], [px + 0.02, py - 0.02]])
        ax.fill(snow[:, 0], snow[:, 1], color="white", alpha=0.85, zorder=3)

    # Water surface — multiple gentle waves at base
    x = np.linspace(0, 1, 400)
    for amp, freq, base, alpha in [(0.012, 6, 0.16, 0.55),
                                    (0.008, 9, 0.12, 0.45),
                                    (0.006, 14, 0.08, 0.40)]:
        wave_y = base + amp * np.sin(2 * np.pi * freq * x)
        ax.fill_between(x, 0, wave_y, color="#1f9bb8", alpha=alpha, zorder=3)

    # Wordmark
    ax.text(0.5, 0.78, "AQUA", fontsize=84, weight="bold",
            color="white", ha="center", va="center", zorder=5,
            family=["Helvetica Neue", "Arial", "DejaVu Sans"])
    ax.text(0.5, 0.65, "Autonomous Quantum cryptanalysis Agent",
            fontsize=18, color="#e8f6fa", ha="center", va="center",
            style="italic", alpha=0.95, zorder=5)
    ax.text(0.5, 0.04, "GeoAlpine LLC   ×   Project Eleven Q-Day Prize Round 2",
            fontsize=12, color="#bfe3ed", ha="center", va="center",
            alpha=0.9, zorder=5, weight="bold")

    out = os.path.join(OUT_DIR, "fig1_keyvisual.png")
    plt.savefig(out, facecolor="#0a2230")
    plt.close(fig)
    print(f"wrote {out}")


def fig4_flow():
    """AI-agent autonomous-execution flowchart.

    Horizontal sequence of role-tagged boxes, with arrows. Color denotes
    who performs each step (Claude vs human).
    """
    steps = [
        ("研究ゴール\n提示",  "human",  None),
        ("文献調査",          "claude", None),
        ("設計・実装",        "claude", None),
        ("デバッグ\n検証",    "claude", None),
        ("実機投入",          "claude", "(人間が Go 承認)"),
        ("結果解析",          "claude", None),
        ("執筆",              "claude", None),
    ]
    n = len(steps)

    fig, ax = plt.subplots(figsize=(14, 4.5))
    ax.set_xlim(0, n)
    ax.set_ylim(0, 4)
    ax.axis("off")

    box_w = 0.78
    box_h = 1.25
    y_c = 2.0

    for i, (label, who, sub) in enumerate(steps):
        cx = i + 0.5
        face = AQUA_BLUE if who == "claude" else AQUA_ACCENT
        rect = FancyBboxPatch(
            (cx - box_w / 2, y_c - box_h / 2), box_w, box_h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            facecolor=face, edgecolor=AQUA_DARK, linewidth=1.4,
            alpha=0.95, zorder=2,
        )
        ax.add_patch(rect)
        ax.text(cx, y_c, label, ha="center", va="center",
                fontsize=12, color="white", weight="bold", zorder=3)
        role_label = "Claude" if who == "claude" else "人間"
        ax.text(cx, y_c + box_h / 2 + 0.16, role_label,
                ha="center", va="bottom",
                fontsize=10, color=AQUA_DARK, weight="bold", alpha=0.85)
        if sub:
            ax.text(cx, y_c - box_h / 2 - 0.16, sub,
                    ha="center", va="top",
                    fontsize=9, color=AQUA_ACCENT, style="italic", weight="bold")

    # Arrows between boxes
    for i in range(n - 1):
        x1 = (i + 0.5) + box_w / 2 + 0.02
        x2 = (i + 1.5) - box_w / 2 - 0.02
        ax.annotate("", xy=(x2, y_c), xytext=(x1, y_c),
                    arrowprops=dict(arrowstyle="->", color=AQUA_DARK, lw=1.6),
                    zorder=1)

    # Legend
    legend_y = 0.5
    ax.add_patch(Rectangle((0.3, legend_y), 0.35, 0.28,
                           facecolor=AQUA_ACCENT, edgecolor=AQUA_DARK,
                           linewidth=1.2, alpha=0.95))
    ax.text(0.75, legend_y + 0.14, "人間が方針選択 / 投入承認",
            va="center", fontsize=11, color=AQUA_DARK)
    ax.add_patch(Rectangle((3.2, legend_y), 0.35, 0.28,
                           facecolor=AQUA_BLUE, edgecolor=AQUA_DARK,
                           linewidth=1.2, alpha=0.95))
    ax.text(3.65, legend_y + 0.14, "Claude が自律実行",
            va="center", fontsize=11, color=AQUA_DARK)

    ax.text(n / 2, 3.55, "AI エージェントによるエンドツーエンド自律実行",
            ha="center", va="center", fontsize=14, color=AQUA_DARK,
            weight="bold")

    out = os.path.join(OUT_DIR, "fig4_flow.png")
    plt.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


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
    fig1_keyvisual()
    fig2_bitcoin_gap()
    fig3_resource_scaling()
    fig4_flow()
    fig5_hit_position()
    print(f"\nAll figures written to {OUT_DIR}/")
