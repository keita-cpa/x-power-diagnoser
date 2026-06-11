---
name: llm-cost-optimizer
description: Gemini API呼び出しのコスト設計パターン集（バッチ呼び出し・絞り込みリトライ・予算ガードレール・同世代フォールバック）。Gemini利用スクリプト（post_generator / mini_bulk_generator / sniper_radar / therapist_introducer）に新規API呼び出しを追加・改修する時に使用。
---

# Skill: llm-cost-optimizer — LLMコスト最適化パターン

> **役割分担**: Gemini APIの呼び出し方・モデル表・エラー対処は
> `apps/auto-poster/.claude/skills/gemini-api/SKILL.md` を参照。
> モデルの使い分けルールは `apps/auto-poster/.claude/rules/model-routing.md` が正。
> 本スキルは「コストを抑える設計パターン」専用。

## 自動参照タイミング
- Gemini API呼び出しを含む新機能を設計・実装する時
- 大量件数の一括処理（bulk生成・スクリーニング・分析）を追加する時
- `429 RESOURCE_EXHAUSTED` が頻発しレート制限対策が必要な時
- 月次のAPIコストが想定（1投稿あたり約4〜7円）を超えた時

## 大前提: マルチAIの掟（MASTER_ARCHITECTURE §2）
1. CSV集計・スコア計算・正規化は **Python** で行う（LLMに推論させない）
2. 長文・大量生成は **Gemini** へオフロードする
3. Claude Codeは **司令塔と推敲** に専念する

---

## 1. バッチ呼び出し（最重要パターン）

短文メタ生成（タイトル・ALT・スクリーニング）を1件ずつ呼ばない。

```python
# NG: 33件 → 33回のAPI呼び出し（レート制限・コスト増）
for item in items:
    result = generate_meta(item)

# OK: 33件 → 7回（バッチサイズ5、構造化出力でまとめて受け取る）
BATCH_SIZE = 5
for i in range(0, len(items), BATCH_SIZE):
    batch = items[i:i + BATCH_SIZE]
    results = generate_meta_batch(batch)  # response_mime_type="application/json"
```

- バッチ化が有効なのは **Flash系の短文タスクのみ**。メイン長文生成・QC審査は1件ずつ（品質優先）
- バッチの結果はJSON構造化出力（gemini-api SKILL.md §8）で受け取り、件数一致を必ず検証する

## 2. 絞り込みリトライ（現行パターンの改善版）

`except Exception` で全エラーをリトライしない。恒久エラーは即時失敗させてリトライ分のコストと時間を節約する。

```python
MAX_RETRIES = 3
RETRY_WAIT  = 2  # 秒

for attempt in range(MAX_RETRIES):
    try:
        response = client.models.generate_content(...)
        if response.text:
            break
    except Exception as e:
        msg = str(e)
        # 恒久エラー → リトライせず即raise（リトライはコストの無駄）
        if "404" in msg or "400" in msg or "API key" in msg.lower():
            raise RuntimeError(f"恒久エラー（リトライ不可）: {e}") from e
        # 一時エラー（429 / 5xx / ネットワーク）のみリトライ
        if attempt < MAX_RETRIES - 1:
            wait = 60 if "429" in msg else RETRY_WAIT * (2 ** attempt)
            time.sleep(wait)
            continue
        raise RuntimeError(f"Gemini API失敗（{MAX_RETRIES}回）: {e}") from e
```

- `429` は1分以上待つ（gemini-api SKILL.md §7 と同一ルール）
- `404` はモデル廃止 → リトライ無意味。`client.models.list()` で同世代を探す

## 3. フォールバックは「同世代・同格」のみ

**格下げ禁止ルール（model-routing.md）を破るフォールバックは実装しない。**

```python
# OK: 廃止対応 — 同世代のpro previewへ（品質維持）
#     gemini-3.1-pro-preview 廃止時 → models/list で gemini-3.x-pro-* を探す
# OK: メタ生成のみ — flash → flash-lite（短文タスクは許容）
# NG: メイン生成・QC審査の pro → flash 自動フォールバック（法令誤引用リスク）
```

## 4. 予算ガードレール（一括処理に必須）

bulk処理には実行前見積もりと累積上限を入れる。

```python
# 単価目安（円/件）— model-routing.md のコスト表と同期すること
COST_PER_MAIN_POST = 7.0   # Pro: 長文生成+QC審査の上限目安
COST_PER_META      = 0.1   # Flash: タイトル+ALT

BUDGET_LIMIT_YEN = 500.0   # 1回のbulk実行の上限

estimated = len(items) * (COST_PER_MAIN_POST + COST_PER_META)
if estimated > BUDGET_LIMIT_YEN:
    print(f"[WARN] 見積もり {estimated:.0f}円 > 上限 {BUDGET_LIMIT_YEN:.0f}円")
    # 件数を分割するかユーザー確認を取ってから実行する

total_cost = 0.0
for item in items:
    text, *_, in_tok, out_tok = generate_post(...)
    total_cost += estimate_cost_yen(in_tok, out_tok)  # usage_metadataから実測
    if total_cost > BUDGET_LIMIT_YEN:
        print(f"[STOP] 累積コスト {total_cost:.0f}円が上限到達。処理を中断")
        break
```

- トークン実測は `response.usage_metadata`（gemini-api SKILL.md §4）から取る
- 中断時は処理済み分をCSVへ確実に保存してから止める（生成済みデータを捨てない）

## 5. アンチパターン

- 全リクエストにProを使う（短文メタはFlashで十分 — 格上げ不要）
- 全エラーを一律リトライする（404への3回リトライは時間とAPI枠の浪費）
- 1件ずつのメタ生成ループ（バッチ化で呼び出し回数を1/5にできる）
- 予算上限なしのbulk実行（暴走時に止まらない）
- コスト定数のハードコード分散（単価は本スキルとmodel-routing.mdの表に集約）
