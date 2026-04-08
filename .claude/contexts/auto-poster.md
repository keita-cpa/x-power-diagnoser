# Context: apps/auto-poster/

## 役割

X自動投稿・永久機関。ConoHa VPS上でCronが `conoha_worker.py` を定期実行。
CSVの投稿ストックをXに自動投稿し、OGP画像を自動生成・ALTテキストを付与する。

---

## エントリーポイント（ConoHa Cron）

```
*/5 * * * * /root/x-auto/venv/bin/python /root/x-auto/conoha_worker.py >> /root/x-auto/logs/cron.log 2>&1
```

**パス変更が必要な場合**: `docs/SOP_Manual.md` §4「ConoHaのCronパス変更手順」を参照。

---

## 重大な制約（必ず守ること）

| 禁止事項 | 理由 |
|---|---|
| `config.py` の Read/Edit 禁止 | APIキー漏洩リスク |
| `tone_sample_*.txt` の Read/Edit 禁止 | 個人情報含有 |
| `data/drafts/stock_posts_draft.csv` の削除禁止 | 投稿ストック全滅 |
| `data/*.csv` のコミット禁止 | `.gitignore` 対象 |
| `schedule.json` の削除禁止 | ランタイム投稿管理状態 |

---

## パイプライン

```
knowledge.xlsx
    ↓
mini_bulk_generator.py → [Gemini API] → stock_posts_draft.csv (ストック補充)
                                                ↓
                                         conoha_worker.py → auto_poster.py → X投稿
                                                             (画像生成・ALT付与)
```

---

## ファイル構成

| ファイル | 役割 |
|---|---|
| `conoha_worker.py` | Cronエントリーポイント。投稿タイミング制御 |
| `auto_poster.py` | メイン投稿ロジック |
| `x_poster.py` | Tweepy経由X API投稿 |
| `post_generator.py` | 投稿文生成 |
| `prompts.py` | プロンプト定義 |
| `mini_bulk_generator.py` | 一括投稿ストック生成 |
| `sniper_radar.py` | ターゲットアカウント探索 |
| `therapist_introducer.py` | セラピスト紹介投稿 |
| `config.py` | **Read/Edit禁止** APIキー等の設定 |

---

## CSVスキーマ（8列 — 絶対に変更しない）

```
管理ID | カテゴリ | フォーマット | 投稿文 | リプライ文 | 画像タイトル | ALT | ステータス
```

- エンコーディング: `utf-8-sig`（BOM付きUTF-8）
- ステータス空欄 = 未投稿、`posted` = 投稿済み

---

## ConoHaへのデプロイ

```bash
# 環境変数を設定してから実行
export CONOHA_USER="root"
export CONOHA_HOST="xxx.xxx.xxx.xxx"
export CONOHA_DEPLOY_PATH="/root/x-auto"
export SSH_KEY="/c/Users/yotak/Documents/x-auto/key-*.pem"

bash scripts/deploy_to_conoha.sh --dry-run  # まず確認
bash scripts/deploy_to_conoha.sh            # 実行
```

---

## 詳細ルール

`apps/auto-poster/CLAUDE.md` および `apps/auto-poster/.claude/rules/` を参照。
