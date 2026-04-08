"""
conoha_worker.py — Cron 用ステートレス司令塔
- Cron で 5 分おきに呼び出される前提。
- schedule.json でスケジュール状態を管理し、投稿すべき時刻なら1件投稿して終了。
- 該当なし・エラー時は静かに（最小限のログで）終了する。
"""

import json
import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ── 自動環境構築（ConoHa WING専用） ──
import os
import sys

# パーツの自動インストール（ユーザー領域へのローカルインストール）
try:
    import PIL
    import tweepy
except ImportError:
    print("[System] WING環境用：必要なパーツをインストールします...")
    os.system(f"{sys.executable} -m pip install --user Pillow tweepy")
    os.system("rm -f schedule.json")
    print("[System] インストール完了。次回の実行から正常稼働します。")
# ──────────────────────────────────────

from auto_poster import execute_single_post, find_target, load_csv

# ──────────────────────────────────────────
# 定数
# ──────────────────────────────────────────

_BASE_DIR       = Path(__file__).parent
SCHEDULE_JSON   = str(_BASE_DIR / "schedule.json")
CANDIDATE_HOURS = [7, 12, 18, 22]   # 朝の通勤7時台・昼休み12時台・夕方18時台・夜22時台（最低4時間間隔）
MIN_POSTS       = 4
MAX_POSTS       = 4
WINDOW_MINUTES  = 10   # 予定時刻から何分以内を「有効」とするか


# ──────────────────────────────────────────
# スケジュール生成・保存・読み込み
# ──────────────────────────────────────────

def _generate_schedule():
    """本日の投稿スケジュールを新規生成して辞書で返す。"""
    n = random.randint(MIN_POSTS, MAX_POSTS)
    selected_hours = random.sample(CANDIDATE_HOURS, n)

    today    = date.today()
    tomorrow = today + timedelta(days=1)

    slots = []
    for hour in selected_hours:
        minute      = random.randint(0, 59)
        target_date = tomorrow if hour == 1 else today
        dt = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
        slots.append({
            "datetime": dt.strftime("%Y-%m-%d %H:%M"),
            "posted":   False,
        })

    slots.sort(key=lambda s: s["datetime"])

    return {
        "date":  today.isoformat(),   # スケジュールを生成した日付（翌日チェック用）
        "slots": slots,
    }


def _save_schedule(data):
    with open(SCHEDULE_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_or_create_schedule():
    """
    schedule.json を読み込む。
    - ファイルなし or 日付が今日でない → 新規生成して保存
    Returns:
        (dict, bool): (スケジュールデータ, 新規生成フラグ)
    """
    today_str = date.today().isoformat()

    if os.path.exists(SCHEDULE_JSON):
        try:
            with open(SCHEDULE_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today_str:
                return data, False          # 既存スケジュールを使用
        except (json.JSONDecodeError, KeyError, OSError):
            pass                            # 破損 → 再生成へ

    data = _generate_schedule()
    _save_schedule(data)
    return data, True


# ──────────────────────────────────────────
# 実行すべきスロットの検索
# ──────────────────────────────────────────

def find_due_slot(slots):
    """
    「posted=False かつ 予定時刻 <= 現在 < 予定時刻 + WINDOW_MINUTES」の
    最初のスロットを返す。

    Returns:
        (int, dict) | (None, None): (スロットのインデックス, スロット辞書)
    """
    now          = datetime.now()
    window_start = now - timedelta(minutes=WINDOW_MINUTES)

    for idx, slot in enumerate(slots):
        if slot.get("posted"):
            continue
        scheduled = datetime.strptime(slot["datetime"], "%Y-%m-%d %H:%M")
        # 予定時刻が「window_start 以降」かつ「現在以前」なら有効
        if window_start <= scheduled <= now:
            return idx, slot

    return None, None


# ──────────────────────────────────────────
# 1件投稿
# ──────────────────────────────────────────

def post_one():
    """
    stock_posts_draft.csv から tweet・未投稿の原稿を1件取得し、
    画像生成・投稿・ツリー投稿・履歴移動のフルフローを実行する。

    Returns:
        (bool, str): (成功フラグ, メッセージ or エラー内容)
    """
    try:
        rows = load_csv()
    except SystemExit:
        return False, "CSV_NOT_FOUND"

    target_idx, target_row = find_target(rows)
    if target_row is None:
        return False, "STOCK_EMPTY"

    return execute_single_post(rows, target_idx, target_row)


# ──────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────

def main():
    # ① スケジュール読み込み or 新規生成
    data, is_new = load_or_create_schedule()

    if is_new:
        total = len(data["slots"])
        times = ", ".join(s["datetime"][11:] for s in data["slots"])   # HH:MM のみ
        print(f"[schedule] 本日のスケジュールを新規生成 ({total}件): {times}")

    # ② 実行すべきスロットがあるか確認
    slot_idx, due_slot = find_due_slot(data["slots"])

    if due_slot is None:
        # 該当なし → Cron に頻繁に呼ばれるため出力なしで静かに終了
        sys.exit(0)

    now_str        = datetime.now().strftime("%H:%M:%S")
    scheduled_time = due_slot["datetime"]
    print(f"[{now_str}] {scheduled_time} の投稿を実行します...")

    # ③ 投稿実行
    try:
        success, message = post_one()
    except Exception as e:
        print(f"  [ERROR] 予期しないエラー: {e}")
        sys.exit(1)

    # ④ 結果の処理
    if success:
        data["slots"][slot_idx]["posted"] = True
        _save_schedule(data)

        posted = sum(1 for s in data["slots"] if s["posted"])
        total  = len(data["slots"])
        print(f"  [OK] 投稿成功: {message} ({posted}/{total}件完了)")

    elif message == "STOCK_EMPTY":
        print("  [WARN] 原稿ストックが切れています。mini_bulk_generator.py で補充してください。")
        sys.exit(1)

    elif message == "CSV_NOT_FOUND":
        print(f"  [ERROR] {data.get('csv', 'stock_posts_draft.csv')} が見つかりません。")
        sys.exit(1)

    else:
        print(f"  [ERROR] 投稿失敗: {message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
