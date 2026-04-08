# Skill: gemini-api — Gemini API利用リファレンス

## 自動参照タイミング
- `post_generator.py` / `sniper_radar.py` の API呼び出し部分を編集する時
- モデル名の変更・追加を検討する時
- `404 NOT_FOUND` / `429` などのAPIエラーが発生した時
- 新しいGemini機能（思考モード・構造化出力等）を追加する時

---

## 1. モデルルーティング表（変更禁止）

| 用途 | モデル定数 | 実際のモデル名 |
|---|---|---|
| メイン長文生成（800〜1400字） | `MODEL_NAME` | `gemini-3.1-pro-preview` |
| QC品質審査（3基準） | `MODEL_NAME` | `gemini-3.1-pro-preview` |
| 画像タイトル生成（15字以内） | `META_MODEL_NAME` | `gemini-3-flash-preview` |
| ALTテキスト生成（100字） | `META_MODEL_NAME` | `gemini-3-flash-preview` |
| リプライ文生成（短文） | `META_MODEL_NAME` | `gemini-3-flash-preview` |
| VIPアカウントスクリーニング | `SCREEN_MODEL` | `gemini-2.5-flash-lite` |
| リプライ起案（sniper_radar） | `REPLY_MODEL` | `gemini-3-flash-preview` |

**格下げ禁止**: メイン生成・QC審査を Flash に変えると法令の誤引用リスクが上がる。
**格上げ不要**: タイトル・ALT・短文は Flash で十分。Pro は過剰投資。

---

## 2. 標準的なAPI呼び出しパターン

```python
from google import genai
from google.genai import types
from config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)

# 標準パターン（リトライ付き）
MAX_RETRIES = 3
RETRY_WAIT  = 2  # 秒

for attempt in range(MAX_RETRIES):
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.9,
                max_output_tokens=2048,
                safety_settings=SAFETY_SETTINGS,
            ),
        )
        text = response.text
        if text:
            break
    except Exception as e:
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_WAIT)
            continue
        raise
```

---

## 3. SAFETY_SETTINGS（変更禁止）

```python
SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",         threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT",  threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT",  threshold="BLOCK_NONE"),
]
```

**理由**: メンエス業界（性的労働・税務調査）の話題が過剰フィルタされると正常な投稿が生成できない。
国家資格者として法的に問題のない専門解説のための意図的設定。**絶対に変更しないこと。**

---

## 4. トークンカウントの取得

```python
# usage_metadata からトークン数を取得
in_tok  = response.usage_metadata.prompt_token_count     or 0
out_tok = response.usage_metadata.candidates_token_count or 0
```

---

## 5. モデル廃止への対応手順

`404 NOT_FOUND` が返った場合:

```python
# Step 1: 利用可能なモデル一覧を取得
for model in client.models.list():
    print(model.name)

# Step 2: 同世代の *-preview を探す
# 例: gemini-3.1-pro-preview が廃止 → models/gemini-3.1-pro-* を探す
```

変更箇所:
- `post_generator.py` の `MODEL_NAME` / `META_MODEL_NAME`
- `sniper_radar.py` の `SCREEN_MODEL` / `REPLY_MODEL`
- `.claude/rules/model-routing.md` のルーティング表

---

## 6. コスト目安（1投稿生成あたり）

| 処理 | モデル | 目安 |
|---|---|---|
| 長文生成（In 8k / Out 1.5k tokens） | Pro Preview | 約 3〜5 円 |
| QC審査（In 2k / Out 0.1k tokens） | Pro Preview | 約 0.5〜1 円 |
| タイトル+ALT（In 0.5k / Out 0.1k tokens） | Flash Preview | 約 0.05 円以下 |
| **合計（1投稿あたり）** | — | **約 4〜7 円** |

---

## 7. よくあるエラーと対処

| エラー | 原因 | 対処 |
|---|---|---|
| `404 NOT_FOUND` | モデル廃止 | Section 5の手順でモデル一覧確認 |
| `429 RESOURCE_EXHAUSTED` | レート制限 | `time.sleep(60)` → 再試行。1分以上待つ |
| `400 INVALID_ARGUMENT` | プロンプトが長すぎる | `max_output_tokens` を下げるか入力を分割 |
| `response.text` が `None` | セーフティブロック | SAFETY_SETTINGSが `BLOCK_NONE` か確認（変更禁止） |
| `ValueError: response.text` | FinishReason が STOP 以外 | `response.candidates[0].finish_reason` を確認 |

---

## 8. 構造化出力（将来実装時の参考）

```python
import json

# JSON出力を強制する場合
config = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema={"type": "object", "properties": {...}},
    safety_settings=SAFETY_SETTINGS,
)
result = json.loads(response.text)
```
