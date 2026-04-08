# /test-run — テスト生成コマンド

テスト用に `mini_bulk_generator.py` を1件だけ実行し、エラーがないか確認する。

## 実行内容

以下のステップを順番に実行してください。

**Step 1: 環境確認**

```bash
cd C:/Users/yotak/Documents/x-auto
venv/Scripts/python -c "from post_generator import generate_post, generate_meta_text; from config import GEMINI_API_KEY; print('imports OK')"
```

**Step 2: API疎通確認（Gemini）**

```bash
venv/Scripts/python -c "
from google import genai
from config import GEMINI_API_KEY
client = genai.Client(api_key=GEMINI_API_KEY)
resp = client.models.generate_content(model='gemini-3-flash-preview', contents='テスト。「OK」とだけ返してください。')
import sys; sys.stdout.buffer.write(resp.text.encode('utf-8')); print()
"
```

**Step 3: generate_meta_text の単体テスト**

```bash
venv/Scripts/python -c "
from post_generator import generate_meta_text
title, alt = generate_meta_text('税務調査が来たとき、セラピストはどう対応すればよいか。')
import sys
sys.stdout.buffer.write(f'title={title}\nalt={alt}\n'.encode('utf-8'))
"
```

**Step 4: CSV の現在状態を確認**

```bash
venv/Scripts/python -c "
import pandas as pd, sys
df = pd.read_csv('data/drafts/stock_posts_draft.csv', encoding='utf-8-sig')
sys.stdout.buffer.write(f'行数: {len(df)}\n列: {list(df.columns)}\n'.encode('utf-8'))
"
```

## 成功の判定基準

- Step 1: `imports OK` が表示される
- Step 2: 「OK」または日本語の短い返答が返る
- Step 3: `title=` に15文字以内の文字列、`alt=` に文字列が返る
- Step 4: 列が8列（`['管理ID', 'カテゴリ', 'フォーマット', '投稿文', 'リプライ文', '画像タイトル', 'ALT', 'ステータス']`）であること

## エラー時の対処

| エラー | 対処 |
|---|---|
| `ModuleNotFoundError: No module named 'google'` | `venv/Scripts/pip install google-genai` |
| `ModuleNotFoundError: No module named 'PIL'` | `venv/Scripts/pip install Pillow` |
| `404 NOT_FOUND` (モデル廃止) | `venv/Scripts/python -c "from google import genai; from config import GEMINI_API_KEY; c=genai.Client(api_key=GEMINI_API_KEY); [print(m.name) for m in c.models.list()]"` でモデル一覧を確認 |
| CSV列が8列でない | `venv/Scripts/python utils/migrate_csv.py` を実行して補完 |
