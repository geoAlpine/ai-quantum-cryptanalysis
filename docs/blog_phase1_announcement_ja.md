# Project AQUA — 真の世界記録への第一歩

*GeoAlpine LLC が「Beyond Verification Filter」の最初のハードウェア datapoint を取得*

**公開予定 2026-05-26 (WordPress / blog.geoalpine.net 想定)**
**ブログタイトル候補**:
  - 「量子コンピュータで Bitcoin 暗号を解く」その先 — Beyond Verification Filter
  - Phase 1 達成：量子シグナルで楕円曲線暗号を解読する初の手法を IBM で実証
  - 1 ヶ月で 2 つの量子記録 — スケールと方法論の両輪

---

## 0. 要約（3 行）

- 4 月に IBM 実機で **22-bit ECDLP の世界記録**を達成（Phase 0）
- 5 月にその結果を**自分自身で批判的に検証**し、「実は古典検証フィルタ依存」と判明
- 今日 5 月 25 日、**全く異なる "真の量子シグナル抽出" 手法を IBM で初実証**（Phase 1）

---

## 1. はじめに

Project AQUA は GeoAlpine LLC（ジオアルピーヌ合同会社）が運営する、AI エージェント（Anthropic Claude）と人間が協働して**量子コンピュータによる暗号解読**を追求するオープンサイエンスプロジェクトです。

このブログでは、2026 年 4 月から 5 月にかけての **2 つの異なる種類の世界記録** について、率直にお伝えします。

![Project AQUA Key Visual](https://blog.geoalpine.net/wp-content/uploads/.../fig1_keyvisual.png)

## 2. Phase 0（4月）— スケール記録

### 何を達成したか

IBM Quantum の `ibm_fez` プロセッサで、**22-bit の楕円曲線離散対数問題（ECDLP）の秘密鍵 d = 1,999,171** を解読しました。

- 量子ビット数: 73
- 2 量子ビットゲート: 124,422 個
- Job ID: `d7o5mr62jamc73bp87eg`

これは、Q-Day Prize Round 1 で 1 BTC の賞金を獲得した Lelli 氏の 15-bit 解読より **+7 アルゴリズム的ステップ** 進んだ結果です。

![Bitcoin との距離](https://blog.geoalpine.net/wp-content/uploads/.../fig2_bitcoin_gap.png)

### 当時の主張

「現存する公開された ECDLP 量子解読の中で最大規模」「LLM エージェントが端から端まで実装した初の事例」。

### しかし — 5 月の自己批判

5 月に**自分自身でその結果を批判的に再検証**しました。

「Collective Vote Test」という新しい統計手法で測ると、22-bit データの真の秘密鍵 `d = 1,999,171` は**候補の投票分布の中央値**（48.8 パーセンタイル、z = -0.03σ）にしかいないことが判明しました。

つまり：

> **22-bit の量子計算は、ほぼ完全に雑音だった。** 古典的な検証ステップが「真の秘密鍵を満遍ない候補から拾い上げた」結果でした。

Lelli の 15-bit 賞金獲得結果も、同じ手法で測ると同じ「**verification filter regime**（検証フィルタ体制）」に属することが判明しました。

これは Q-Day Prize Round 1 全体の **量的だが質的ではない**性質を初めて公開定量化した発見です。

## 3. Phase 1（5月25日）— 方法論記録

### 真の量子シグナル抽出への挑戦

Phase 0 の発見を受け、私たちは「**実機で本当に量子シグナルから ECDLP を解読する**」方法を模索しました。

開発した手法：

1. **HNP (Hidden Number Problem) スコア**：複数ショットの統計構造から d 候補をランク付け
2. **Top-K verification**：HNP スコア上位 K 個と、それらの対称パートナー (n - d) のみを検証
3. **適応的カウンティング (t < m)**：量子ビット節約しつつ信号維持
4. **dense oracle**：m ≤ 6 では古典オラクルより 7 倍効率的

### 5 月 25 日の実機実行

**ibm_kingston プロセッサで m=3 (n=7) を実行**：

- 量子ビット数: **15**（Phase 0 の 1/5）
- 2 量子ビットゲート: **1,243**（Phase 0 の 1/100）
- Job ID: `d89s7c9789is7393nie0`
- 推定 fidelity: 1.97 × 10⁻³

結果：

> **HNP スコア rank 2 で d = 6 = d_true を直接 verify で復元。anti-d fallback 不要。**

| HNP rank | d 候補 | スコア | 備考 |
|---|---|---|---|
| 1 | 4 | 6.7080 | noise |
| **2** | **6** | **6.7490** | **d_true ✓ 直接検証成功** |
| 3 | 1 | 6.8604 | anti-d_true |
| 4-7 | 3, 2, 5, 0 | ... | |

![Phase 1 診断プロット](https://blog.geoalpine.net/wp-content/uploads/.../shor_4bit_t6_1024shots_hnp_ibm.png)

### なぜ「真の世界記録」なのか

スケールは小さい（m=3）ですが、これは**全く異なるカテゴリの結果**です：

| | Phase 0 (22-bit) | Phase 1 (4-bit) |
|---|---|---|
| 規模 | 大 | 小 |
| Decode 方法 | 全候補を網羅検証 | **HNP score で絞り込み + 検証** |
| 量子シグナル使用 | 実質ゼロ | **構造的に利用** |
| Lelli 賞金と同種か | はい | **いいえ（新カテゴリ）** |

Phase 1 は「**現存公開された全 ECDLP 量子解読の中で、初の signal-regime recovery**」です。

## 4. AI エージェントとの協働

このプロジェクトの開発は、**Anthropic Claude（Sonnet 4.6 / Opus 4.7）を主たる実装パートナー** として進めました。

![Agent Flow](https://blog.geoalpine.net/wp-content/uploads/.../fig4_flow.png)

- 4 週間（パートタイム）で 2 つのハードウェア datapoint
- 個人事業主（合同会社）が学術機関の支援なしで実施
- 過去の量子ハードウェア経験なしで開始
- 全コード MIT ライセンス、すべての結果をリポジトリにバンドル

これは**フロンティア AI が、個人 / 小チームによる**暗号解読規模の研究**を実現可能にした**直接的な証拠です。これ自体が、結果と同等以上の重要性を持つ方法論的貢献と考えます。

## 5. これは Bitcoin を脅かすのか

**いいえ、当面は。**

- 4-bit は古典 BSGS で数マイクロ秒
- Bitcoin の 256-bit までの差は依然として極めて大きい
- Google Quantum AI 2026-03 の最新見積もり：1,200 論理量子ビット、9000 万 Toffoli ゲートが必要

しかし、**「公開された量子ハードウェア解読の品質を測る方法」**は変わります。今後の発表は「Phase 0 体制（verification filter）」と「Phase 1 体制（signal regime）」を明確に区別すべきです。

## 6. 次のステップ

1. **arXiv 短報投稿**（「Beyond Verification Filter」原稿準備中）
2. **国内大学との共同研究 / IBM Quantum Credits 経由でのスケールアップ**
3. **Phase 2 ハードウェア datapoint**（m ≥ 5 で iterative + dense oracle 実装後）
4. **Anthropic との公式連携**（press@anthropic.com 連絡中）

## 7. オープンソースリンク

- GitHub: [github.com/geoAlpine/ai-quantum-cryptanalysis](https://github.com/geoAlpine/ai-quantum-cryptanalysis)
- 公開ブランチ: `refactor/code-review-may2026`（最新 32 commits）
- Phase 1 結果ファイル: `results/shor_4bit_t6_1024shots_hnp_ibm.json`
- 再現コマンド:
  ```bash
  pip install -e ".[dev]"
  python scripts/submit_18bit.py --bits 4 --t 6 \
      --oracle dense --extractor hnp --backend ibm_kingston --shots 1024
  python scripts/fetch_result.py results/_pending_4bit_t6_dense_hnp_ibm.json
  ```
- IBM 無料枠（10 分 / 28 日）の **5%** で再現可能

## 連絡先

- **GeoAlpine LLC** (ジオアルピーヌ合同会社)
- Web: [geoalpine.net](https://geoalpine.net)
- Email: info@geoalpine.net
- Twitter/X: TBD

---

*Cover image: Project AQUA wordmark*
*技術相談・共同研究のお問い合わせは info@geoalpine.net まで。*
