# csv-safety.md — CSV データ破壊防止ルール

CSVファイルの誤操作はシステム全体の停止に直結する。
このファイルに記載されたルールは例外なく遵守すること。

---

## stock_posts_draft.csv（最重要ファイル）

### スキーマ（8列 — 絶対に変更しないこと）

| 列番号 | 列名 | 型 | 説明 |
|---|---|---|---|
| 1 | 管理ID | str | 一意識別子（例: CPA-001） |
| 2 | カテゴリ | str | POST_CATEGORIESのキーと一致 |
| 3 | フォーマット | str | `tweet` or `thread`（投稿対象は `tweet`） |
| 4 | 投稿文 | str | 本文（最大280文字） |
| 5 | リプライ文 | str | スレッドの2番目の投稿（空欄可） |
| 6 | 画像タイトル | str | OGP画像のタイトル（15文字以内） |
| 7 | ALT | str | 画像のALTテキスト（100文字以内） |
| 8 | ステータス | str | 空欄=未投稿 / `posted`=投稿済み |

**投稿対象の条件**: `フォーマット=tweet` かつ `ステータス=空欄` の最初の1行

### エンコーディング
```python
# 読み込み
df = pd.read_csv('stock_posts_draft.csv', encoding='utf-8-sig')

# 書き込み（既存ファイルへの追記）
df.to_csv('stock_posts_draft.csv', encoding='utf-8-sig', index=False)

# 追記（appendモード）
with open('stock_posts_draft.csv', 'a', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    writer.writerow(row)
```

`utf-8-sig` を `utf-8` に変更するとExcelで文字化けする。変更禁止。

### 危険な操作
```python
# 危険: 全データを上書きする
df.to_csv('stock_posts_draft.csv', ...)  # 既存データが消える

# 安全: 追記のみ
with open(..., 'a') as f: ...
```

**変更前に必ずバックアップ:**
```bash
cp stock_posts_draft.csv stock_posts_draft_backup_YYYYMMDD.csv
```

---

## analytics_posts.csv / analytics_replies.csv

- これらは `/project:monthly-analytics` で自動生成される分析用ファイル
- 上書き・削除しても再生成可能（ただし元のX Analytics CSVが必要）
- 分析用途のみ。`stock_posts_draft.csv` と混同しないこと

---

## CSV操作の安全チェックリスト

変更前に以下を確認すること:

```python
# 列数確認（必ず8列）
import pandas as pd
df = pd.read_csv('stock_posts_draft.csv', encoding='utf-8-sig')
assert len(df.columns) == 8, f"列数エラー: {df.columns.tolist()}"
print(f"列: {df.columns.tolist()}")

# 行数確認（削減されていないか）
before_count = len(df)
print(f"行数: {before_count}")
```

---

## FIELDNAMES（mini_bulk_generator.py と auto_poster.py で共通）

```python
FIELDNAMES = ['管理ID', 'カテゴリ', 'フォーマット', '投稿文', 'リプライ文', '画像タイトル', 'ALT', 'ステータス']
```

列名を変更する場合は両ファイルの `FIELDNAMES` を同期すること。

---

## 復旧手順

### 列が8列でない場合
```bash
venv/Scripts/python migrate_csv.py
```
注意: `migrate_csv.py` は**再実行可能か事前確認**すること（重複データが発生する可能性あり）。

### ファイルが破損した場合
1. Gitの最新コミットからリストアを試みる（`.gitignore` でCSVは除外されているため、自力復旧が必要）
2. バックアップファイルがあればリストア
3. バックアップがない場合: `mini_bulk_generator.py` で一から生成し直す

---

## scouted_targets.csv（sniper_radar.py の出力）

| 列名 | 説明 |
|---|---|
| 取得日時 | UTC形式 |
| 対象URL | ツイートのURL |
| ユーザー名 | @なしのユーザー名 |
| 対象ツイート | 引用元ツイートの本文 |
| AIリプライ案 | 生成されたリプライ案 |

- 削除しても `sniper_radar.py` の再実行で復旧可能
- 削除前に投稿済みの案がないか確認すること
