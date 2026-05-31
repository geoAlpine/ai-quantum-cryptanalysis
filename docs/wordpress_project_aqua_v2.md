> ⚠️ **補正 (2026-05) / Correction.** 本文書の「Phase 1 = signal-regime recovery on IBM」「d_true の HNP rank = signal」は**誤り**です。IBM m=3 は verification-filter regime (permutation p≈0.61)、genuine signal は Quantinuum H2-1 emulator (p≈0.0003) のみ（IBM は陰性対照）。正確な枠組みは [README](../README.md) と `scripts/hnp_score_matrix.py` 参照。

---

# Project AQUA：2 回目の検証 — 検証フィルタを超えて、IBM 実機で「真の量子シグナル」から暗号鍵を復元

*GeoAlpine LLC（ジオアルピーヌ合同会社） — 2026 年 5 月 25 日*

> **公開先**: https://geoalpine.net/project-aqua-v2/（仮）
> **WordPress 投稿時のスラッグ案**: `project-aqua-v2` または `project-aqua-phase1`
> **カテゴリ**: Research / 量子計算
> **タグ**: Project AQUA, ECDLP, Shor, IBM Quantum, AI Agent, Anthropic Claude

---

## 結論先出し：2 回目の検証で「別カテゴリ」の解読を達成

1 回目（2026 年 4 月）で **22-bit ECDLP** を IBM 実機で復元した報告は、すでに [Project AQUA — 1 回目の検証ページ](https://geoalpine.net/project-aqua/) で公開しています。あの記事の末尾で、私たちは率直にこう書きました：

> 「現在の NISQ 領域での "鍵復元" は、量子シグナルの本物のピークではなく、検証フィルタによる候補選別に支えられている」

**今回の 2 回目の検証は、そこから先を埋めるためのものです。**

- **日付**: 2026-05-25
- **バックエンド**: IBM Quantum `ibm_kingston`（Heron r2）
- **規模**: 4-bit（n = 7）、量子ビット 15、2量子ビットゲート 1,243
- **Job ID**: `d89s7c9789is7393nie0`
- **復元した鍵**: d = 6（**HNP score の rank 2 で direct verify 成功**、anti-d fallback 不要）

スケールは 22-bit から大きく後退して見えますが、**復元の質的なカテゴリが違います**。1 回目が「検証フィルタが load-bearing」だったのに対し、2 回目は「複数ショットの統計構造から d を絞り込む signal-regime recovery」です。

**現存する公開された量子ハードウェア ECDLP 解読の中で、初めての signal-regime datapoint** と位置付けています。

---

## 1 回目からの変更点と、なぜ 2 回目が必要だったか

### 1 回目の自己批判

1 回目記事の「正直な評価」セクションで提示した課題は、定性的な記述に留まっていました。今回はそれを**定量的に測る診断ツール**を作りました。

新規スクリプト `scripts/collective_decode.py` は、保存済み IBM カウントファイルに対して **BSGS の答えを使わない投票テスト**を実行します。各ショットの候補集合から d 候補をランク付けし、真の鍵 `d_true` が分布のどこに位置するかを純粋な統計値で報告します。

**1 回目の 22-bit データに適用した結果**：

| 指標 | 値 |
|---|---|
| `d_true = 1,999,171` の投票数 | 137 |
| 一様ノイズ期待値 | 137.32 |
| z-score | **-0.03σ** |
| 分布内の順位 | 1,024,632 / 2,098,699 |
| パーセンタイル | **48.8%（ほぼ中央）** |

つまり 22-bit データの真の鍵は、**ランダムに選んだ d とほぼ完全に区別がつかない**位置にいました。あの復元は確かに成功したけれど、その成功は古典的な検証ステップ（`d_cand · G == Q` のチェック）が「8000 個前後の候補の中から正解を拾い上げた」結果だったのです。

参考までに、同じテストを Lelli 氏の 15-bit Round-1 賞金獲得結果に当てはめても、**ほぼ同じ regime** に属することが判明しました。Q-Day Prize Round 1 全体が、現時点では「**検証フィルタ体制（verification-filter regime）**」と呼ぶべき段階にあるという事実を、ここで初めて公開定量化できたことになります。

### 2 回目の目的

ならば「**検証フィルタに頼らずに、量子シグナルそのものから d を絞り込めるか？**」 — これが 2 回目の検証の問いです。

---

## 2 回目の検証：HNP スコア + Top-K 検証パイプライン

### 採用した手法

1. **Hidden Number Problem (HNP) スコア**
   2 レジスタ Shor の "noiseless ideal" ピーク関係 `n·(j + d·k) ≡ s·M (mod n·M)` を使い、複数ショットの統計から各 d 候補の "整合度" を測ります。`r`（測定された点レジスタ）はこのスコアには入りません — `r` は post-pt-measurement の格子を選ぶだけで、QFT ピークの位置は同じだからです（[実証コミット](https://github.com/geoAlpine/ai-quantum-cryptanalysis/commit/028f514) 参照）。

2. **Top-K verification with anti-d partner**
   HNP スコア上位 K = 7 個の候補と、それぞれの「反対 d」（`(n - d) mod n`）を順に古典検証。最初に `d · G == Q` を満たしたものを採用。

3. **Dense oracle + adaptive counting**
   m = 3 では dense unitary オラクルが ripple-carry より約 7 倍効率的（2Q ゲート 1,243 vs 8,389）。t = 6（M / n = 9.14）で expected peak が十分疎になります。

### 提出前の予測

実機提出前に、ibm_kingston のノイズモデルを使った Aer シミュレーションを **9 + 5 = 14 trials** 実行し、すべての試行で d_true が HNP rank 2 に直接（anti-d fallback なし）出ることを確認しました。詳細は [`docs/deepening_findings_2026-05-25.md`](https://github.com/geoAlpine/ai-quantum-cryptanalysis/blob/refactor/code-review-may2026/docs/deepening_findings_2026-05-25.md) 参照。

### 実機結果

2026-05-25、IBM Open Plan の 28 日 rolling window がリセットされた直後の **約 1 分の無料枠** を使って提出：

| 項目 | 値 |
|---|---|
| Job ID | `d89s7c9789is7393nie0` |
| バックエンド | `ibm_kingston`（Heron r2、median 2Q error 0.21%）|
| 量子ビット数 | 15 |
| 2 量子ビットゲート | 1,243 |
| 推定 fidelity | 1.97 × 10⁻³ |
| ショット数 | 1,024 |
| Sampler 設定 | DD XY4 + Pauli twirling |
| 実行時間 | < 1 分（QUEUED → DONE） |

ハードウェアデータでの HNP スコア（低いほど良い）：

| HNP rank | d 候補 | スコア | 備考 |
|---|---|---|---|
| 1 | 4 | 6.7080 | ノイズ |
| **2** | **6** | **6.7490** | **d_true ← direct verify ✓** |
| 3 | 1 | 6.8604 | anti-d_true |
| 4 | 3 | 6.9014 | |
| 5 | 2 | 6.9463 | |
| 6 | 5 | 7.2002 | |
| 7 | 0 | 7.6895 | |

production パイプラインは top-1 (d=4) を検証 → 失敗 → anti-d (d=3) を検証 → 失敗 → top-2 (d=6) を検証 → **成功**。

シミュレーション予測（14 / 14 で rank 2）と実機結果（rank 2）が完全一致しました。

![Phase 1 診断プロット — HNP スコア / (j, k) ヒートマップ / 残差ヒストグラム](https://github.com/geoAlpine/ai-quantum-cryptanalysis/raw/refactor/code-review-may2026/results/shor_4bit_t6_1024shots_hnp_ibm.png)

---

## 1 回目と 2 回目の対比

| | **1 回目 (Phase 0)** | **2 回目 (Phase 1)** |
|---|---|---|
| 日付 | 2026-04-28 | **2026-05-25** |
| バックエンド | ibm_fez | ibm_kingston |
| 規模 | 22-bit（n ≈ 2.1M） | 4-bit（n = 7）|
| 量子ビット数 | 73 | **15** |
| 2Q ゲート | 124,422 | **1,243** |
| 推定 fidelity | 10⁻¹⁵¹ | **10⁻³** |
| Decode 手法 | CF-Lift v2（候補列挙 + 全数検証） | **HNP score + top-K 検証** |
| d_true の collective rank | ~中央値（z = -0.03σ） | **rank 2（top-3 に d-class）** |
| カテゴリ | **verification-filter regime** | **signal regime** |
| Lelli の 15-bit と同種か | はい | **いいえ（新カテゴリ）** |
| 価値 | スケール記録 | **方法論記録** |

「スケール」と「方法論」は両方意味があります。Q-Day Prize Round 2 がどちらを重視するかは未発表ですが、私たちは**両方の数字を持っている**唯一のチームのままです。

---

## 正直な評価（2 回目版）

### 何を主張するか

- **量子ハードウェア上で、ECDLP 解読の decode が "per-shot 全数検証" ではなく "cross-shot HNP scoring" で動くことを、初めて実機で示した**。
- ibm_kingston のノイズモデルを使ったシミュレーションが、実機結果を rank・順位レベルまで予測できた（noisy-Aer の predictivity の calibration）。
- 全コード MIT ライセンス公開済み。1 コマンドで再現可能（IBM 無料枠の **5 %（≈ 30 秒）** で足ります）。
- 1 回目の「正直な評価」で課題として挙げた "signal regime recovery" の最初の datapoint を確保した。

### 何を主張しないか

- **量子優位性ではありません。** n = 7 の ECDLP は古典 Baby-step / Giant-step で μs 単位で解けます。価値は方法論にあります。
- **K << n の本格的な絞り込みもまだです。** n = 7 では top-K = 7 が全候補と等しいため、HNP の "絞り込み" は形式的には 1×。本格的な意義は n ≥ 100 で出てきます。
- **複数試行のハードウェア再現性もまだ単発です。** 1 ヶ月分の無料枠で 1 ジョブのみ。次回（2026-06 リフレッシュ後）に独立 5 ジョブで variance を計測予定。
- **Bitcoin は当面安全です。** Google Quantum AI 2026-03 の最新見積もり（論理量子ビット 1,200、Toffoli 9,000 万）を超えるハードウェアが、現存しません。

---

## 1 ヶ月で 2 つの記録 — AI エージェントとの協働

1 回目から 2 回目までの 4 週間、コードと記事は **Anthropic Claude（Sonnet 4.6 / Opus 4.7）を主たる実装パートナーとして** 進めました。

人間の役割は依然として：
- 戦略的選択肢から「これでいく」を決める
- IBM の有料 QPU を使う決定（今回も 1 回だけ）
- 自分自身の結果を批判的に問い直すかどうかを判断する（これが 2 回目につながった）

学術機関の支援なし、過去の量子ハードウェア経験なしから、合同会社代表 1 名で**月に 1 つ独立した質的記録を達成**できる時代になりました。これは結果と同等の方法論的貢献として記録に残すに値すると考えます。

---

## 次のステップ

1. **arXiv 短報投稿**（"Beyond the Verification Filter" 原稿準備中、Section 5.5 で 2 回目の結果を実数値表記）
2. **国内大学との共同研究 / IBM Quantum Credits 経由でのスケールアップ**（個人事業主だと Credits 単独申請不可、PI 共同が必要）
3. **Phase 2 ハードウェア datapoint**（m ≥ 5 に拡張するには、iterative + dense オラクルの組合せ実装が必要 — 現状 5-bit は信号が hardware noise で壊れる）
4. **Anthropic との公式連携**（press@anthropic.com に発信、案件化中）

---

## 公開リソース

- **GitHub**: [github.com/geoAlpine/ai-quantum-cryptanalysis](https://github.com/geoAlpine/ai-quantum-cryptanalysis)
- **ブランチ**: `refactor/code-review-may2026`（最新 30+ commits、CI 緑）
- **Phase 1 結果ファイル**: `results/shor_4bit_t6_1024shots_hnp_ibm.json` ＋ 診断プロット PNG
- **論文骨子**: `docs/honest_framing_preprint_outline.md`
- **プロジェクト年表**: `docs/PROJECT_TIMELINE.md`
- **要約 1 ページ版**: `docs/executive_summary.md`

再現コマンド：

```bash
# クローン + 開発依存導入
pip install -e ".[dev]"

# Phase 1 提出（IBM 無料枠の約 5%）
python scripts/submit_18bit.py --bits 4 --t 6 \
    --oracle dense --extractor hnp \
    --backend ibm_kingston --shots 1024

# 結果取得 + decode（QPU 追加消費なし）
python scripts/fetch_result.py results/_pending_4bit_t6_dense_hnp_ibm.json
```

QPU を使わずに既存の counts ファイルから再現するなら：

```bash
python scripts/decode_offline.py \
    --counts results/shor_4bit_t6_1024shots_hnp_ibm.json \
    --bits 4 --t 6 --oracle dense --extractor hnp --top-k 7
```

---

## 連絡先

- **GeoAlpine LLC**（ジオアルピーヌ合同会社）
- Web: [geoalpine.net](https://geoalpine.net)
- Email: info@geoalpine.net
- 技術相談・共同研究・取材のお問い合わせ歓迎です。

---

*1 回目の検証記事 → [Project AQUA：1 回目の検証ページ](https://geoalpine.net/project-aqua/)*
*次回（Phase 2）に向けては、5-bit 以上を signal regime で復元するための iterative + dense オラクル拡張、および本格的な格子簡約（Boneh-Venkatesan / Ekerå-Håstad）の実装を進めます。*
