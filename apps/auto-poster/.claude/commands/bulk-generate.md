# /project:bulk-generate — 一括投稿生成コマンド

`mini_bulk_generator.py` を安全に実行し、ストック投稿を一括生成してCSVに追記する。

## 事前確認

実行前に現在のストック残数を確認する:

```bash
cd C:/Users/yotak/Documents/x-auto
venv/Scripts/python -c "
import pandas as pd, sys
df = pd.read_csv('data/drafts/stock_posts_draft.csv', encoding='utf-8-sig')
pending = df[df['ステータス'].isna() | (df['ステータス'] == '')].shape[0]
total = len(df)
sys.stdout.buffer.write(f'総行数: {total}\n未投稿（ストック）: {pending}\n'.encode('utf-8'))
"
```

ストックが **500件以上** ある場合は生成が過剰になるため、ユーザーに確認してから実行すること。

## 実行

```bash
cd C:/Users/yotak/Documents/x-auto
venv/Scripts/python mini_bulk_generator.py
```

対話型CLIが起動する。ユーザーが件数・カテゴリを入力するまで待機。

## 実行後の確認

生成完了後、結果を確認して報告する:

```bash
venv/Scripts/python -c "
import pandas as pd, sys
df = pd.read_csv('data/drafts/stock_posts_draft.csv', encoding='utf-8-sig')
pending = df[df['ステータス'].isna() | (df['ステータス'] == '')].shape[0]
total = len(df)
sys.stdout.buffer.write(f'--- 生成後 ---\n総行数: {total}\n未投稿ストック: {pending}\n'.encode('utf-8'))
"
```

## 報告フォーマット

```
[bulk-generate 完了]
- 生成前ストック: XX件
- 新規生成: XX件
- 生成後ストック: XX件
- トークン消費: in=XX / out=XX（mini_bulk_generator.py の出力から取得）
```

## エラー時の対処

| エラー | 対処 |
|---|---|
| `ModuleNotFoundError` | `venv/Scripts/pip install google-genai openpyxl pandas` |
| `404 NOT_FOUND` (モデル廃止) | `.claude/rules/model-routing.md` の廃止対応手順を参照 |
| `FileNotFoundError: knowledge.xlsx` | knowledge.xlsx がプロジェクトルートに存在するか確認 |
| CSV列が8列でない | `.claude/rules/csv-safety.md` の復旧手順を参照（`utils/migrate_csv.py` を実行） |
| 文字化け | `encoding='utf-8-sig'` が使われているか確認（`.claude/rules/coding-style.md`） |
