# coding-style.md — x-auto Python コーディング規約

このプロジェクト固有のPython規約。グローバルルール（~/.claude/rules/python/）を継承しつつ、
x-auto特有の制約を上書き・追加する。

---

## API呼び出し（必須パターン）

すべてのGemini API呼び出しは以下のパターンに従うこと:

```python
MAX_RETRIES = 3
RETRY_WAIT  = 2  # 秒

for attempt in range(MAX_RETRIES):
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.9,
                safety_settings=SAFETY_SETTINGS,
            ),
        )
        if response.text:
            break
    except Exception as e:
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_WAIT)
            continue
        raise RuntimeError(f"Gemini API失敗（{MAX_RETRIES}回）: {e}") from e
```

**なぜ**: API呼び出しはネットワーク・レート制限・モデル廃止など外部要因で失敗する。
黙って失敗するのではなく、リトライして最終的に呼び出し元に例外を伝播する。

---

## CSV 読み書き

```python
# 読み込み（必ず utf-8-sig）
df = pd.read_csv('stock_posts_draft.csv', encoding='utf-8-sig')

# 追記（既存データを壊さない）
with open('stock_posts_draft.csv', 'a', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    writer.writerow(row_dict)

# 書き込み（全体上書き — 必要最小限に留める）
df.to_csv('stock_posts_draft.csv', encoding='utf-8-sig', index=False)
```

`utf-8` や `cp932` は使わない。Windowsでのexcel表示とPython読み込みの両立には `utf-8-sig` が必須。

---

## print() の制約

```python
# 禁止: 絵文字（Windows cp932で文字化けする）
print("✅ 完了")   # NG
print("🚀 起動")   # NG

# 推奨: ASCII記号または日本語のみ
print("[OK] 完了")
print("[START] 起動")

# UTF-8出力が必要な場合（ターミナル表示）
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
```

---

## generate_post() の戻り値型

```python
# post_generator.py の generate_post() は必ずこの6タプルを返す
def generate_post(knowledge_text: str, category: str, tone: str) -> tuple[str, str, str, str, int, int]:
    """
    Returns:
        (text, reply_text, image_title, alt_text, input_tokens, output_tokens)
    """
```

呼び出し側:
```python
text, reply_text, image_title, alt_text, in_tok, out_tok = generate_post(...)
```

---

## 文字数制限

| 対象 | 制限 | 実装 |
|---|---|---|
| ツイート本文 | 280文字 | プロンプトで指示、QC審査で確認 |
| 画像タイトル | 15文字以内 | `generate_meta_text()` のプロンプトで指示 |
| ALTテキスト | 100文字以内 | 同上 |

---

## エラーハンドリング原則

```python
# 禁止: エラーの握りつぶし
try:
    ...
except Exception:
    pass  # NG — エラーが消えて原因追跡できなくなる

# 禁止: 過剰な汎用except
try:
    ...
except Exception as e:
    print(f"エラー: {e}")  # NG — ロギングなし

# 推奨: 具体的な例外 + ログ + 再raise
try:
    df = pd.read_csv('stock_posts_draft.csv', encoding='utf-8-sig')
except FileNotFoundError:
    print("[ERROR] stock_posts_draft.csv が見つかりません")
    raise
except UnicodeDecodeError as e:
    print(f"[ERROR] エンコーディングエラー: {e}")
    raise
```

---

## 定数の命名規約

```python
# 定数はすべて大文字スネークケース
MODEL_NAME      = "gemini-3.1-pro-preview"
META_MODEL_NAME = "gemini-3-flash-preview"
SCREEN_MODEL    = "gemini-2.5-flash-lite"

FIELDNAMES = ['管理ID', 'カテゴリ', 'フォーマット', '投稿文', 'リプライ文', '画像タイトル', 'ALT', 'ステータス']
MAX_RETRIES = 3
RETRY_WAIT  = 2
```

---

## tweepy v1 / v2 の使い分け

```python
# v2 Client — テキスト投稿
client_v2 = tweepy.Client(
    bearer_token=BEARER_TOKEN,
    consumer_key=API_KEY,
    consumer_secret=API_SECRET,
    access_token=ACCESS_TOKEN,
    access_token_secret=ACCESS_TOKEN_SECRET,
)
client_v2.create_tweet(text=post_text, media_ids=[media_id])

# v1 API — メディア（画像）アップロード
auth = tweepy.OAuthHandler(API_KEY, API_SECRET)
auth.set_access_token(ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
api_v1 = tweepy.API(auth)
media = api_v1.media_upload(filename=image_path)
media_id = media.media_id
```

**なぜ**: X APIのメディアアップロードはv1エンドポイント（`/1.1/media/upload`）のみサポート。
テキスト投稿はv2（`/2/tweets`）を使う。混同すると `AttributeError` が発生する。

---

## コードの健全性チェック（変更後に実行）

```bash
# 構文チェック
venv/Scripts/python -m py_compile prompts.py post_generator.py auto_poster.py

# インポートチェック
venv/Scripts/python -c "import prompts, post_generator; print('imports OK')"
```
