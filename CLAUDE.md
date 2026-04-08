# CLAUDE.md — x-integrated-platform モノレポ

## このファイルの使い方

このCLAUDE.mdはモノレポ全体の「地図」です。
**作業対象が決まったら、下記のコンテキストロードセクションの該当ファイルを必ず参照してください。**
全アプリのコンテキストを同時にロードしないこと（トークン浪費・ノイズ増加のため）。

---

## モノレポ構成

| パス | 内容 | デプロイ先 |
|---|---|---|
| `apps/power-diagnoser/` | X戦闘力診断 FastAPI | Render (自動デプロイ) |
| `apps/auto-poster/` | X自動投稿・永久機関 Python CLI | ConoHa VPS (Cron) |
| `docs/knowledge/X_Algorithm/` | Xアルゴリズム参照ナレッジ | 読み取り専用 |
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

### Claude Code設定を参照・改善する場合
→ `.claude/contexts/claude-mastery.md` を参照

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
