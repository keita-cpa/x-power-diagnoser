# CLAUDE.md — x-integrated-platform モノレポ

## このファイルの使い方

このCLAUDE.mdはモノレポ全体の「地図」です。
**作業対象が決まったら、下記のコンテキストロードセクションの該当ファイルを必ず参照してください。**
全アプリのコンテキストを同時にロードしないこと（トークン浪費・ノイズ増加のため）。

---

## 現在地と次の一手（2026-06-12時点）

- 稼働中: ペルソナv2「3つの顔」（prompts.py v6.1）/ ドロップ＆パース原稿補充 / ConoHa自動投稿（4件/日）
- 次回セッションの最優先課題:
  1. X API認証の OAuth 2.0（リフレッシュトークン）移行 → `docs/MASTER_ARCHITECTURE.md` §8
  2. 次回 monthly-analytics で新カテゴリ weight の初回実測チューニング（v7） → `docs/SOP_Manual.md` §11

---

## モノレポ構成

| パス | 内容 | デプロイ先 |
|---|---|---|
| `apps/power-diagnoser/` | X戦闘力診断 FastAPI | Render (自動デプロイ) |
| `apps/auto-poster/` | X自動投稿・永久機関 Python CLI | ConoHa WING (Cron・Python 3.6) |
| `.claude/skills/` | モノレポ共通スキル（context-budget / llm-cost-optimizer / content-engine） | — |
| `.claude/agents/` | 専門サブエージェント（security-reviewer） | — |
| `docs/knowledge/X_Algorithm/` | Xアルゴリズム参照ナレッジ（技術層） | 読み取り専用 |
| `docs/knowledge/X_Operations/` | X運用ルール・機能ナレッジ（運用層） | 読み取り専用 |
| `docs/knowledge/Psychology/` | 人蕩し術・話術の戦術原則（心理層） | 読み取り専用 |
| `docs/knowledge/Claude_Mastery/` | Claude Code設定コレクション | 読み取り専用 |
| `scripts/migrate_local.py` | ローカル移行スクリプト | ローカル実行 |
| `scripts/deploy_to_conoha.sh` | ConoHaデプロイスクリプト | ローカル実行 |
| `docs/SOP_Manual.md` | 運用マニュアル（日本語） | — |

---

## コンテキストロード（作業前に必ず参照）

### power-diagnoser を触る場合
→ `.claude/contexts/power-diagnoser.md` を参照

### auto-poster を触る場合
→ `.claude/contexts/auto-poster.md` を参照
→ さらに `apps/auto-poster/CLAUDE.md` を参照（詳細ルール）

### X Algorithmを参照する場合
→ `.claude/contexts/x-algorithm.md` を参照

### X運用ルール（凍結回避・自動化規約）・X記事機能・ペルソナ心理設計を扱う場合
→ `.claude/contexts/x-operations.md` を参照

### Claude Code設定を参照・改善する場合
→ `.claude/contexts/claude-mastery.md` を参照

### コンテキスト消費の監査・`.claude` 肥大化チェック
→ `context-budget` スキル（`.claude/skills/context-budget/`）

### Gemini APIのコスト設計（バッチ・リトライ・予算上限）
→ `llm-cost-optimizer` スキル（`.claude/skills/llm-cost-optimizer/`）

### 収益化コンテンツ（セールスレター・LP・媒体展開）の作成
→ `content-engine` スキル（`.claude/skills/content-engine/`）

### コミット前・デプロイ前のセキュリティ監査
→ `security-reviewer` エージェント（`.claude/agents/security-reviewer.md`）

---

## 共通制約（全アプリ共通・例外なし）

- `.env` ファイルは絶対にコミット・デプロイしない
- `*.pem` 秘密鍵は絶対にコミット・デプロイしない
- `venv/`, `node_modules/` はコミット禁止
- `apps/auto-poster/config.py` はRead/Edit禁止（APIキー含有）
- `apps/auto-poster/data/drafts/stock_posts_draft.csv` は削除禁止

---

## クイックコマンド

```bash
# dry-runで移行プレビュー
python scripts/migrate_local.py --dry-run

# 移行実行
python scripts/migrate_local.py

# auto-posterをConoHaへdeploy (dry-run)
bash scripts/deploy_to_conoha.sh --dry-run

# power-diagnoser ローカル起動
cd apps/power-diagnoser && uvicorn app.main:app --reload
```

---

## コミット前セキュリティチェック

```bash
git diff --cached --name-only | grep -E "\.env|\.pem|config\.py" && echo "DANGER: シークレット検出" || echo "OK: クリーン"
```
