# Context: apps/auto-poster/

## 役割

X自動投稿・永久機関。ConoHa WING（共用レンタルサーバー・root権限なし）上でCronが
`conoha_worker.py` を定期実行。CSVの投稿ストックをXに自動投稿し、OGP画像を自動生成・ALTテキストを付与する。

---

## エントリーポイント（ConoHa WING Cron・2026-06-12実測）

```
*/5 * * * * cd ~/x-auto && /usr/local/bin/python conoha_worker.py > cron_run.log 2>&1
```

- 実行Python: `/usr/local/bin/python` = **Python 3.6.15**（venvなし）。
  **サーバーで実行されるファイルに3.7+構文（`list[dict]`注釈等）を入れないこと**
- ログは `~/x-auto/cron_run.log`（毎回上書き＝最新実行分のみ）

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

## ConoHa WINGへのデプロイ

WING本番の接続情報（`c9994802@www1156.conoha.ne.jp`・SSHポート**8022**・
`/home/c9994802/x-auto`・鍵 `/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem`）は
スクリプトの既定値に設定済み。環境変数の事前exportは不要。

```bash
bash scripts/deploy_to_conoha.sh --dry-run  # まず確認
bash scripts/deploy_to_conoha.sh            # 実行
bash scripts/push_drafts_to_conoha.sh       # outbox差分CSVのみの本番マージ
```

注意: `sniper_radar.py` / `mini_bulk_generator.py` / `therapist_introducer.py` /
`ingest_raw_contents.py` 等のローカル実行スクリプトはPython 3.9構文を含む。
サーバー（Python 3.6.15）で実行しないこと。

---

## 詳細ルール

`apps/auto-poster/CLAUDE.md` および `apps/auto-poster/.claude/rules/` を参照。
