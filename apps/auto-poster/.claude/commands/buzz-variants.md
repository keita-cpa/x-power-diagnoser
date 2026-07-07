# /project:buzz-variants — バズ番頭: 高実績投稿のバリアント生成

過去のX Analyticsで高AlgoScoreを記録した投稿を手本に、
同じ感情フック構造・語りのリズムを維持した「変形バリアント投稿」を生成し、
stock_posts_draft.csv に追記する。

**設計根拠**:
- 『CodexでXを完全自動化』のバズ番頭パターン（実績上位投稿→変形5本ストック）
- 『loop設計』のVERIFY→ITERATE原則（月次Analytics VERIFY→勝ちパターン反復生成）

---

## 事前確認: analytics_posts.csv の存在チェック

```bash
cd C:/Projects/x-integrated-platform/apps/auto-poster
python -c "
import csv, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
p = Path('data/analytics/analytics_posts.csv')
if p.exists():
    rows = list(csv.DictReader(open(p, encoding='utf-8-sig')))
    posts = [r for r in rows if not r.get('ポスト本文','').startswith('@')]
    print(f'OK: {len(posts)}件のメイン投稿が見つかりました')
else:
    print('ERROR: analytics_posts.csv が存在しません')
    print('先に /project:monthly-analytics を実行してください')
"
```

---

## 実行（デフォルト: Top3 × 3変形 = 最大9件）

```bash
cd C:/Projects/x-integrated-platform/apps/auto-poster
python buzz_variant_generator.py
```

### オプション

**Top5を対象に2変形ずつ（10件）**:
```bash
python buzz_variant_generator.py --top 5 --variants 2
```

**書き込みなしプレビュー（確認用）**:
```bash
python buzz_variant_generator.py --dry-run
```

---

## 実行後の確認

```bash
cd C:/Projects/x-integrated-platform/apps/auto-poster
python -c "
import csv, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
with open('data/drafts/stock_posts_draft.csv', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))
pending = [r for r in rows if not r.get('ステータス','').strip()]
print(f'総行数: {len(rows)} | 未投稿ストック: {len(pending)}件')
"
```

---

## 報告フォーマット

```
[buzz-variants 完了]
- 対象: Top-N投稿（AlgoScore=X / Y / Z）
- 生成: N件 QC合格（N試行中）
- 現在のストック: XX件
- 推奨: /project:stock-check でConoHaとの差分確認
```

---

## 推奨実行タイミング

- `/project:monthly-analytics` 直後（Analyticsデータが新鮮なとき）
- ストックが30件を下回ったとき
- 特定カテゴリのAlgoScore平均が全体平均の1.5倍を超えているとき（その型を量産）

---

## エラー時の対処

| エラー | 対処 |
|---|---|
| `analytics_posts.csv が存在しません` | `/project:monthly-analytics` を先に実行 |
| QC全件REJECT | ナレッジファイルが古い可能性。`自動生成用ナレッジ/knowledge.xlsx` を確認 |
| `ImportError: post_generator` | venv が有効か確認。`venv/Scripts/activate` |
| モデル404 | `.claude/rules/model-routing.md` の廃止対応手順を参照 |
