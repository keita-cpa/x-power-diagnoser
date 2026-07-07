@echo off
rem ============================================================
rem run_daily_menu.cmd -- 今日の交流メニューを生成してブラウザで開く
rem タスクスケジューラ(タスク名: KeitaCPA_DailyMenu)から毎朝自動起動される。
rem 手動実行も可: このファイルをダブルクリックするだけ。
rem ============================================================
cd /d "%~dp0"
"..\..\venv\Scripts\python.exe" daily_menu.py > data\menus\last_run.log 2>&1
rem 投稿済みアーカイブをGDriveへ出力（重複防止ナレッジ・docs/gdocs_archive_sync.md 参照）
"..\..\venv\Scripts\python.exe" export_posts_for_notebooklm.py > data\menus\last_export.log 2>&1
start "" "%~dp0data\menus\latest.html"
