# Short-form announcements for Phase 1

Drafts to copy-paste into LinkedIn / X / Hacker News.

---

## X / Twitter (Japanese, 280 chars)

> 🎯 量子コンピュータで ECDLP を解読する新カテゴリ達成
>
> IBM ibm_kingston で 4-bit ECDLP の鍵 d=6 を、HNP score で**真の量子シグナルから**復元（従来の "全候補ブルートフォース検証" とは違うカテゴリ）
>
> 4 月の 22-bit 記録は実は古典フィルタ依存と自己批判 → 5/25 に方法論記録
>
> github.com/geoAlpine/ai-quantum-cryptanalysis

---

## X / Twitter (English, 280 chars)

> 🎯 First quantum-hardware ECDLP recovery decoded by Hidden-Number-Problem
> scoring instead of verification-filter brute force.
>
> IBM ibm_kingston, m=3, HNP rank-2 direct verify, recovered d=6.
> Distinct category from Lelli's 15-bit Q-Day Prize win.
>
> github.com/geoAlpine/ai-quantum-cryptanalysis

---

## LinkedIn (Japanese, long-form ~1500 chars)

GeoAlpine LLC として、量子コンピュータによる楕円曲線暗号（ECDLP）解読プロジェクトで、**2 ヶ月で 2 つの異なる種類の世界記録**を達成しました。

**Phase 0（4 月）**：IBM Quantum で **22-bit ECDLP の秘密鍵を解読**。Q-Day Prize Round 1 で 1 BTC を獲得した Lelli 氏の 15-bit 結果より +7 ステップ進んだ規模記録。

**しかし** — 5 月に自分自身でその結果を批判的に再検証しました。「Collective Vote Test」で測ると、22-bit データは**事実上、量子シグナルを持っていなかった**ことが判明。古典的な検証フィルタが「真の秘密鍵を満遍ない候補から拾い上げた」結果だった。Lelli の結果も同じ regime だと判明。

**Phase 1（5 月 25 日）**：その反省に基づき、**真の量子シグナルから ECDLP を解読する新手法**を IBM ibm_kingston で初実証：

- Hidden Number Problem (HNP) スコアで複数ショットの統計構造から d 候補をランク付け
- d_true=6 が HNP rank 2 で直接 verify 成功
- 15 量子ビット、1,243 ゲート（Phase 0 の 1/100 規模）

スケールは小さいですが、これは「**公開された量子 ECDLP 解読の中で初の signal-regime recovery**」です。

このプロジェクトは Anthropic Claude（Sonnet 4.6 / Opus 4.7）を実装パートナーとして、合同会社代表 1 名で 4 週間で構築。学術機関の支援なし、過去の量子ハードウェア経験なしから出発。フロンティア AI が個人 / 小チームに **暗号解読規模の研究**を可能にした事例として、結果と同等の方法論的貢献と考えます。

全コード MIT ライセンス公開：
github.com/geoAlpine/ai-quantum-cryptanalysis

Bitcoin はまだ安全です（4-bit は古典で μs 解、Bitcoin の 256-bit まで膨大な差）。しかし「公開された量子解読の品質を測る言葉」は変わります。

#quantum #cryptanalysis #ECDLP #Shor #IBM #AI #Claude #Anthropic #cryptography

---

## LinkedIn (English, long-form ~1500 chars)

I'm announcing two qualitatively different ECDLP quantum-hardware
recoveries from GeoAlpine LLC, built end-to-end with an LLM agent
(Anthropic Claude) as my primary implementation partner.

**Phase 0 (April 2026)**: Recovered the 22-bit ECDLP private key on IBM
Quantum `ibm_fez`. +7 algorithmic steps beyond Lelli's 1-BTC-winning
15-bit Q-Day Prize Round-1 submission. The largest publicly-reported
ECDLP quantum-hardware recovery to date — a scale record.

**Then I critiqued my own result.** A "Collective Vote Test" I built
in May showed the 22-bit data has essentially no quantum signal: the
recovered private key sits at the median of the candidate vote
distribution (z = -0.03σ). The classical verification step did the
work. Lelli's result is in the same "verification-filter regime."

**Phase 1 (May 25, 2026)**: First hardware ECDLP recovery in a
*signal* regime. On `ibm_kingston`, m=3 (n=7), the new HNP-score +
verification pipeline places d_true at HNP rank 2 with direct
verification — *not* via per-shot brute force. 15 qubits, 1,243
two-qubit gates, fidelity 2 × 10⁻³.

Small scale, but a category the field hasn't had a public
hardware datapoint for.

Built solo + LLM agent, 4 weeks part-time, no academic affiliation,
no prior quantum hardware experience. All code MIT-licensed at
github.com/geoAlpine/ai-quantum-cryptanalysis. The methodology
(frontier AI making cryptanalysis-scale research tractable for
small teams) is a contribution alongside the result.

Bitcoin not in danger. Classical BSGS solves m=3 in microseconds and
the 256-bit gap to Bitcoin remains huge per Google Quantum AI's
2026-03 estimate (1,200 logical qubits, 90M Toffolis). But the
vocabulary the field uses to measure published recoveries is what
needs updating.

#quantum #cryptanalysis #ECDLP #Shor #IBM #Anthropic #Claude #AIagent

---

## Hacker News (Show HN)

> Show HN: Phase 1 of quantum ECDLP recovery — beyond verification filter
>
> https://github.com/geoAlpine/ai-quantum-cryptanalysis
>
> I run a one-person shop (GeoAlpine LLC) building open-source quantum
> cryptanalysis with an LLM agent (Claude) as the primary implementation
> partner. In April I recovered a 22-bit ECDLP private key on IBM Quantum,
> a scale record beyond Lelli's 1-BTC Q-Day Prize Round-1 win.
>
> In May I wrote a diagnostic (`scripts/collective_decode.py`) that takes
> any saved IBM counts file and runs a no-side-channel "collective vote"
> test: it scores every candidate d by frequency in the per-shot candidate
> sets, without using the bsgs shortcut the production extractor uses.
>
> On my own 22-bit data the result is brutal: d_true sits at the
> **48.8th percentile** of vote frequencies, z = -0.03σ. The recovery is
> real, but the quantum compute is essentially noise — the classical
> verification step ("does d_cand · G == Q?") found the answer. Lelli's
> 15-bit win is in the same regime.
>
> Today (2026-05-25) I submitted a hardware datapoint that's a different
> category. m=3, n=7, on ibm_kingston, 15 qubits and 1,243 2Q gates. The
> decode runs Hidden Number Problem scoring across all shots, picks the
> top-K, and verifies — d_true at HNP rank 2, direct verify, no
> verification-filter brute force needed.
>
> Job ID `d89s7c9789is7393nie0`, results bundled with the repo, one-command
> reproducible from the 1 m 22 s of IBM open-plan free QPU budget I had
> when the 28-day window cleared.
>
> Tools: Python + Qiskit + qiskit-aer + qiskit-ibm-runtime + fpylll, all
> MIT. Test suite ~30 tests on GitHub Actions. Paper outline in
> `docs/honest_framing_preprint_outline.md`; full timeline in
> `docs/PROJECT_TIMELINE.md`.
>
> Not a quantum advantage. Bitcoin is fine. But the diagnostic and the
> Phase 1 recovery let us name and measure where current
> quantum-hardware results actually sit.
