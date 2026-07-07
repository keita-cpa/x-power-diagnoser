# /project:daily-menu — 今日の交流メニュー生成コマンド

`daily_menu.py` を実行し、3つの交流エンジン（返信し返し・sniper・quote）の起案結果を
1枚のHTMLメニューに集約する。通常は タスクスケジューラ `KeitaCPA_DailyMenu` が
毎朝7:30に自動実行するため、このコマンドは手動での再生成・臨時実行用。

## 実行

```bash
cd C:/Projects/x-integrated-platform/apps/auto-poster
../../venv/Scripts/python.exe daily_menu.py
```

オプション:
- `--skip-mentions` / `--skip-sniper` / `--skip-quote` — 各エンジンをスキップ
- `--with-scout` — keyword_scout を強制実行（通常は月曜のみ自動）
- `--skip-scout` — 月曜でも scout をスキップ

## 実行後の報告

1. 実行サマリー（返信し返し案・リプライ案・引用案・新規候補の件数）を報告する
2. メニューの場所を案内する: `data/menus/latest.html`（ブラウザで開く）
3. 起案ゼロの場合は理由（新規メンションなし・72hインターバル等）を伝える

## 注意

- 投稿は必ず人間の手動承認（メニューの「返信画面を開く」→ 内容確認 → 投稿ボタン）
- 起案履歴は `data/logs/mention_drafts.csv` / `scouted_targets.csv` / `quote_drafts.csv` が自動管理
- タスクスケジューラの確認: `schtasks /query /tn KeitaCPA_DailyMenu`
- 全体像・行動基準: `docs/system_overview.html`
