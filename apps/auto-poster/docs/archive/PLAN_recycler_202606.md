# 実装計画: 死にポストリサイクルシステム（2026-06-27）

## 目的
AlgoScore低スコアの投稿（死にポスト）を削除前にアーカイブし、
Gemini Flash でリライトして stock_posts_draft.csv に再投入する。
タイムラインの類似投稿連続問題はカテゴリローテーション修正で別途解消する。

## 影響範囲
| ファイル | 変更種別 |
|---|---|
| `auto_poster.py` | 修正: append_history() にポストIDを追加保存 |
| `recycler.py` | **新規作成**: 3テーブル突合→アーカイブ→Geminiリライト→CSV追記 |
| `data/analytics/dead_posts_archive.csv` | 新規（自動生成） |
| `CLAUDE.md` | 修正: recycler.py の説明・/project:recycle-posts コマンド追加 |
| `auto_poster.py`（後工程） | 修正: カテゴリローテーション（重複問題） |

## スキーマ

### dead_posts_archive.csv（新設）
```
ポストID | 投稿日 | 削除日 | カテゴリ | フォーマット | AlgoScore | 投稿文全文 | リサイクル済み
```
- `リサイクル済み`: 空欄=未処理 / `recycled`=リライト済み

### posted_history.csv（追加列）
現在: 管理ID | カテゴリ | フォーマット | 投稿文 | リプライ文 | 画像タイトル | ALT | ステータス | 投稿日時
追加後: ...投稿日時 | ポストID
※ 既存行の「ポストID」列は空欄になる（後方互換性維持）

## 突合ロジック（recycler.py）
```
dead_posts_queue.csv ─[ポストID]──→ analytics_posts.csv → AlgoScore・ポスト本文取得
analytics_posts.csv ─[本文先頭50文字 fuzzy]──→ posted_history.csv → カテゴリ・フォーマット取得
```
posted_history.csv にポストID列が追加された後は直接 ポストID で突合（両方対応）。

## AlgoScore 計算式（recycler.py 内）
```
AlgoScore = Like×0.5 + Bookmark×10 + RT×1 + 返信×13.5
```
（著者リプライ返信は analytics_posts.csv では分離不能なため除外）

## タスク分解
- [x] Step 1: auto_poster.py の append_history() にポストID追加
- [x] Step 2: recycler.py 新規作成
  - [x] Step 2-1: 3テーブル突合 → dead_posts_archive.csv 生成
  - [x] Step 2-2: アーカイブ → Gemini Flash リライト → stock_posts_draft.csv 追記
  - [x] Step 2-3: --dry-run / --archive-only / --recycle-only モード
- [x] Step 3: CLAUDE.md 更新（recycler.py 説明・スラッシュコマンド）
- [x] Step 4: 構文チェック（py_compile）
- [ ] Step 5（後工程）: auto_poster.py カテゴリローテーション

## 懸念事項・リスク
- posted_history.csv に ポストID がない行は本文先頭 fuzzy 突合で対応する
  → strip() + 改行正規化で対処。突合失敗時はカテゴリ空欄・フォーマット="tweet" でフォールバック
- stock_posts_draft.csv への追記は csv-safety.md に従い追記モードのみ
- リライトは Gemini Flash（META_MODEL_NAME）。1件 約0.05円
- ローカル実行（Python 3.13）。ConoHa Python 3.6 互換コードは不要
- BLOCK_NONE セーフティ設定は変更禁止

## 合意事項（ユーザー確認済み 2026-06-27）
- アーカイブ保存項目: 本文全文・AlgoScore・投稿日削除日・カテゴリフォーマット
- 重複（カテゴリ連続）修正はリサイクル実装後にまとめて対応
