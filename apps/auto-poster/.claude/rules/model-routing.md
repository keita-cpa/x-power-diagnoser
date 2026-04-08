# Model Routing Rules — コスト最適化設計

このファイルは Gemini モデルの使い分けルールを定義する。
**無断でモデルを変更・統一しないこと。コスト設計と品質設計が破綻する。**

---

## ルーティング表

| 用途 | モデル | 理由 |
|---|---|---|
| メイン長文生成（800〜1400字） | `gemini-3.1-pro-preview` | 法令・判例の正確な引用と深い洞察が必要。品質最優先 |
| QC品質審査（Big4監査人3基準） | `gemini-3.1-pro-preview` | ハルシネーション検出は最高精度で行う |
| 画像タイトル生成（15文字以内） | `gemini-3-flash-preview` | 軽量タスク。高速・低コストで十分 |
| ALTテキスト生成（100文字・LLMO対策） | `gemini-3-flash-preview` | 同上 |
| リプライ文の生成 | `gemini-3-flash-preview` | 短文生成。コスト削減 |
| 炎上・文脈監視（将来実装） | `gemini-2.5-flash-lite` | 大量処理。精度より速度・コストを優先 |

---

## 実装上の定数（`post_generator.py`）

```python
MODEL_NAME      = "gemini-3.1-pro-preview"   # メイン生成・QC審査
META_MODEL_NAME = "gemini-3-flash-preview"    # タイトル・ALT生成
```

---

## コスト目安（1件生成あたり）

| 処理 | モデル | 目安 |
|---|---|---|
| 長文生成（In 8k / Out 1.5k tokens） | Pro Preview | 約 3〜5 円 |
| QC審査（In 2k / Out 0.1k tokens） | Pro Preview | 約 0.5〜1 円 |
| タイトル+ALT生成（In 0.5k / Out 0.1k tokens） | Flash Preview | 約 0.05 円以下 |
| **合計（1投稿あたり）** | — | **約 4〜7 円** |

---

## 変更ルール

1. **Pro → Flash への格下げ禁止**: メイン生成・QC審査を Flash に変えると品質が著しく低下し、法令の誤引用リスクが上がる
2. **Flash → Pro への格上げ不要**: タイトル・ALT は短文生成なのでProは過剰投資
3. **モデル名変更前の確認必須**: 変更前に `client.models.list()` で利用可否を確認する
4. **廃止モデルへの対応**: `404 NOT_FOUND` が返った場合は `models/list` で同世代の `*-preview` を探す

---

## セーフティ設定（変更禁止）

```python
SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",         threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT",  threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT",  threshold="BLOCK_NONE"),
]
```

**理由**: メンエス業界（性的労働・税務調査）の話題が過剰フィルタされると正常な投稿が生成できない。
国家資格者として法的に問題のない専門解説を行うための意図的な設定。
