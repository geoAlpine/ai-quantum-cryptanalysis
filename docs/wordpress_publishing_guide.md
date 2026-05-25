# WordPress 投稿ガイド — Project AQUA v2 記事

## 結論

**WordPress 標準 Gutenberg はフル markdown 非対応**。テーブル・コードブロック・画像 URL などは markdown のまま貼っても表示されません。3 つの選択肢から好きな方法を選んでください。

---

## 選択肢 A：HTML を Custom HTML ブロックに貼る（**推奨・最速**）

### 手順

1. WordPress 管理画面で「新規投稿」を作成
2. タイトル: 「**Project AQUA：2 回目の検証 — 検証フィルタを超えて、IBM 実機で「真の量子シグナル」から暗号鍵を復元**」
3. スラッグ: `project-aqua-v2` または `project-aqua-phase1`
4. 本文エディタで「ブロック追加」→「カスタム HTML」を選ぶ
5. `docs/wordpress_project_aqua_v2_publish.html` の中身をすべてコピーして貼る
6. プレビューで確認 → 公開

### メリット
- 1 つのブロックですべて再現される
- テーブル・コードブロックがそのまま動く
- 編集時に markdown のまま見える

### デメリット
- WordPress エディタ上では HTML として見える（読みにくい）
- 後で部分編集するとき HTML を直接いじる必要あり

---

## 選択肢 B：HTML を「コードエディタ」モードに直接貼る

1. Gutenberg 右上の「︙」メニュー → 「コードエディタ」モードに切替
2. `docs/wordpress_project_aqua_v2_block.html` をすべて貼る（``<!-- wp:html -->`` ラッパー付き）
3. 「ビジュアルエディタ」に戻すと WordPress が解釈
4. 公開

**A よりさらにシンプル**。WordPress の内部ブロック表記でラップされているので、後でも編集しやすい。

---

## 選択肢 C：markdown プラグインを導入して markdown をそのまま使う

| プラグイン | 特徴 | おすすめ度 |
|---|---|---|
| **Jetpack** | 公式・標準的・「設定 → 執筆」で Markdown 有効化 | ◎ サイトに既に入ってる場合 |
| **Markup Markdown** | EasyMDE エディタに置き換え、DB に markdown 保存 | ◯ 完全に markdown 派 |
| **Ultimate Markdown** | Gutenberg と共存、ブロックとして挿入可 | ◯ ハイブリッド派 |
| **Simple Markdown** | 軽量、Gutenberg ブロック追加のみ | △ シンプル用途 |

導入後は `docs/wordpress_project_aqua_v2.md` の中身（冒頭のメタ情報除く）をそのまま貼れます。

[Sources for plugin info](https://wordpress.org/plugins/) | [DAEXT plugin guide](https://daext.com/blog/the-best-markdown-plugins-for-wordpress/)

---

## 画像のアップロード

記事内で参照している画像は GitHub raw リンクですが、本番公開時は WordPress メディアライブラリにアップロードして差し替えるのが安全です（GitHub raw は将来リンク切れの可能性、ロード速度も劣る）。

### 必要な画像

| 画像 | 用途 | GitHub raw URL（仮置き） |
|---|---|---|
| `results/figures/fig1_keyvisual.png` | ヘッダ | `blog/aqua-intro` ブランチ |
| `results/figures/fig2_bitcoin_gap.png` | Phase 0 セクション | `blog/aqua-intro` ブランチ |
| `results/figures/fig4_flow.png` | AI agent flow（任意で再利用）| `blog/aqua-intro` ブランチ |
| `results/shor_4bit_t6_1024shots_hnp_ibm.png` | **Phase 1 診断（新規）** | `refactor/code-review-may2026` ブランチ |

WordPress メディアライブラリにアップ後、HTML 内の URL を置換してください。または Gutenberg の「画像」ブロックに分けても OK。

---

## SEO 設定

### 抜粋（excerpt）
> 4 月の 22-bit 量子解読は「検証フィルタ依存」だったと自己批判 → 5 月 25 日、IBM ibm_kingston で HNP score による真の量子シグナル抽出を初実証。Lelli の 15-bit 賞金獲得結果とは質的に異なるカテゴリの暗号鍵復元を達成。

### メタディスクリプション（160 字以内）
> Project AQUA 2 回目の検証。HNP スコアによる cross-shot 量子シグナル抽出で、IBM Quantum 上で初の signal-regime ECDLP 解読。1 回目の 22-bit verification-filter 結果との対比、再現コマンド付き。

### OGP 画像
- Phase 1 診断プロット（`results/shor_4bit_t6_1024shots_hnp_ibm.png`）が分かりやすい
- または fig1_keyvisual を再利用

### カテゴリ / タグ
- カテゴリ: Research / 量子計算 / Cryptography
- タグ: Project AQUA, ECDLP, Shor, IBM Quantum, AI Agent, Anthropic Claude, HNP

### 1 回目の記事との接続
- 1 回目記事から 2 回目への内部リンク追加（記事末尾の「次の記事」セクションなど）
- 1 回目記事冒頭にも 2 回目への注釈を後で追加するのが理想

---

## ファイル一覧

| ファイル | 用途 |
|---|---|
| `docs/wordpress_project_aqua_v2.md` | markdown ソース（編集はここで） |
| `docs/wordpress_project_aqua_v2.html` | HTML 変換版（メタ情報含む） |
| `docs/wordpress_project_aqua_v2_publish.html` | **公開用 HTML（メタ削除済み）** |
| `docs/wordpress_project_aqua_v2_block.html` | WordPress ブロック表記でラップ済み |
| `docs/wordpress_publishing_guide.md` | このファイル |

---

## markdown を再変換したいとき

WordPress 公開後に修正が必要になったら：

```bash
source .venv/bin/activate
python -c "
import markdown, re
src = open('docs/wordpress_project_aqua_v2.md').read()
src = re.sub(r'^> \*\*公開先\*\*.*?\n(?:>.*\n)*\n', '', src, count=1, flags=re.MULTILINE)
html = markdown.markdown(src, extensions=['extra', 'tables', 'fenced_code', 'sane_lists'])
open('docs/wordpress_project_aqua_v2_publish.html', 'w').write(html)
"
```
