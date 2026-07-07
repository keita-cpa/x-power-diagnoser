"""
export_posts_for_notebooklm.py
-------------------------------
analytics CSVから全投稿を統合してAlgoScoreを計算し、
NotebookLM用テキストと削除/リサイクル候補CSVを生成する。

生成ファイル:
  data/analytics/notebooklm_posts_all.txt   - 全投稿（NotebookLM用・重複防止ナレッジ）
  data/analytics/dead_posts_candidates.csv  - 削除候補（AlgoScore<5 かつ IMP<200）
  data/analytics/recycle_candidates.csv     - リサイクル候補（5<=AlgoScore<20）

使い方:
  python export_posts_for_notebooklm.py            # 全出力
  python export_posts_for_notebooklm.py --dry-run  # 件数確認のみ（ファイル出力なし）
"""

import csv
import io
import os
import sys
from datetime import datetime

# Windows cp932 ターミナルでの文字化け対策
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DRY_RUN = "--dry-run" in sys.argv

BASE = os.path.dirname(os.path.abspath(__file__))
ANALYTICS_DIR = os.path.join(BASE, "data", "analytics", "raw")
OUT_DIR = os.path.join(BASE, "data", "analytics")

# 投稿予定ストック（未投稿ネタも重複防止の対象に含める）
STOCK_CSV = os.path.join(BASE, "data", "drafts", "stock_posts_draft.csv")

# GDrive出力先（Google Drive for Desktop 経由で自動同期 → Apps Script が Googleドキュメントへ転記）
GDRIVE_DIR  = r"G:\マイドライブ\90_X_KeitaCPA"
GDRIVE_FILE = "keita_posted_archive.txt"


def find_analytics_csvs() -> list:
    """
    raw/ 配下の account_analytics_content_*.csv を自動検出し、
    ファイル名末尾の終了日が新しい順に返す（重複はポストIDで除去・新しいものを優先）。
    """
    import glob
    import re
    paths = glob.glob(os.path.join(ANALYTICS_DIR, "account_analytics_content_*.csv"))

    def end_date_key(path):
        m = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(path))
        return m.group(1) if m else "0000-00-00"

    return sorted(paths, key=end_date_key, reverse=True)

DEAD_SCORE_THRESHOLD    = 5     # AlgoScore < この値 かつ IMP < IMP_THRESHOLD → 削除候補
RECYCLE_SCORE_THRESHOLD = 20    # DEAD <= AlgoScore < この値 → リサイクル候補
IMP_THRESHOLD           = 200   # 削除候補の追加条件（IMP低い）


def calc_algo_score(row: dict) -> float:
    """AlgoScore = Reply×13.5 + Bookmark×10 + RT×1 + Like×0.5"""
    try:
        reply    = float(row.get("返信", 0) or 0)
        bookmark = float(row.get("ブックマーク", 0) or 0)
        rt       = float(row.get("リポスト", 0) or 0)
        like     = float(row.get("いいね", 0) or 0)
        return reply * 13.5 + bookmark * 10 + rt * 1 + like * 0.5
    except (ValueError, TypeError):
        return 0.0


def load_all_posts() -> list:
    """raw/ の全analytics CSVを読み込み、ポストIDで重複除去する（新しいCSVを優先）"""
    seen_ids: set = set()
    posts = []
    csv_paths = find_analytics_csvs()
    if not csv_paths:
        print("[WARN] " + ANALYTICS_DIR + " に account_analytics_content_*.csv がありません")
    for filepath in csv_paths:
        filename = os.path.basename(filepath)
        count_added = 0
        with open(filepath, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                post_id = (row.get("ポストID") or "").strip()
                if not post_id or post_id in seen_ids:
                    continue
                seen_ids.add(post_id)
                row["_algo_score"] = calc_algo_score(row)
                row["_imp"] = float(row.get("インプレッション数", 0) or 0)
                posts.append(row)
                count_added += 1
        print("[INFO] " + filename + ": " + str(count_added) + " 件追加")
    return posts


def main():
    posts = load_all_posts()
    total = len(posts)
    print("[INFO] 総投稿数（重複除去済み）: " + str(total) + " 件")

    # リプライ（本文が@で始まる）は IMP が低くて当然なので削除候補から除外
    main_posts = [p for p in posts if not (p.get("ポスト本文") or "").strip().startswith("@")]
    reply_posts = [p for p in posts if (p.get("ポスト本文") or "").strip().startswith("@")]

    dead_candidates    = [p for p in main_posts if p["_algo_score"] < DEAD_SCORE_THRESHOLD and p["_imp"] < IMP_THRESHOLD]
    recycle_candidates = [p for p in main_posts if DEAD_SCORE_THRESHOLD <= p["_algo_score"] < RECYCLE_SCORE_THRESHOLD]
    high_performers    = [p for p in main_posts if p["_algo_score"] >= RECYCLE_SCORE_THRESHOLD]

    print("[INFO] うちリプライ（除外）: " + str(len(reply_posts)) + " 件 / メイン投稿: " + str(len(main_posts)) + " 件")
    print("[INFO] 削除候補（AlgoScore<" + str(DEAD_SCORE_THRESHOLD) + " かつ IMP<" + str(IMP_THRESHOLD) + "）: " + str(len(dead_candidates)) + " 件")
    print("[INFO] リサイクル候補（AlgoScore " + str(DEAD_SCORE_THRESHOLD) + " ~ " + str(RECYCLE_SCORE_THRESHOLD) + "）: " + str(len(recycle_candidates)) + " 件")
    print("[INFO] 高AlgoScore（AlgoScore>=" + str(RECYCLE_SCORE_THRESHOLD) + "）: " + str(len(high_performers)) + " 件")
    print()

    if DRY_RUN:
        print("[DRY-RUN] ファイル出力はスキップしました")
        # 削除候補の先頭5件を表示
        print("[削除候補 先頭5件]")
        for p in sorted(dead_candidates, key=lambda x: x["_algo_score"])[:5]:
            body = (p.get("ポスト本文") or "").replace("\n", " ")[:60]
            print("  AlgoScore=" + str(p["_algo_score"]) + " IMP=" + str(int(p["_imp"])) + " | " + body)
        return

    today = datetime.now().strftime("%Y-%m-%d")

    # 1. NotebookLM用テキスト（全投稿 - AlgoScore降順）
    notebooklm_path = os.path.join(OUT_DIR, "notebooklm_posts_all.txt")
    sorted_posts = sorted(posts, key=lambda x: x["_algo_score"], reverse=True)
    with open(notebooklm_path, "w", encoding="utf-8") as f:
        f.write("# @Keita_CPA 投稿済み一覧（NotebookLM用 - 重複防止ナレッジ）\n")
        f.write("# 生成日: " + today + " | 総件数: " + str(total) + " 件\n")
        f.write("# AlgoScore降順（高いものから）で並んでいる\n")
        f.write("# AlgoScore = Reply x13.5 + Bookmark x10 + RT x1 + Like x0.5\n\n")
        for i, p in enumerate(sorted_posts, 1):
            body  = (p.get("ポスト本文") or "").strip()
            score = p["_algo_score"]
            imp   = int(p["_imp"])
            date  = p.get("日付", "")
            f.write("=== POST " + str(i).zfill(4) + " | AlgoScore: " + str(round(score, 1)) + " | IMP: " + str(imp) + " | " + date + " ===\n")
            f.write(body + "\n\n")

        # 投稿予定ストック（未投稿）も重複防止の対象に含める
        stock_count = 0
        if os.path.exists(STOCK_CSV):
            f.write("\n# ---- 以下は【投稿予定ストック（未投稿）】。これらのネタ・切り口も使用済みとして扱うこと ----\n\n")
            with open(STOCK_CSV, encoding="utf-8-sig") as sf:
                for row in csv.DictReader(sf):
                    if (row.get("ステータス") or "").strip() != "":
                        continue  # 投稿済み・エラー行は上のanalytics側でカバーされる
                    body = (row.get("投稿文") or "").strip()
                    if not body:
                        continue
                    stock_count += 1
                    f.write("=== STOCK " + str(stock_count).zfill(3) + " | " + (row.get("カテゴリ") or "") + " ===\n")
                    f.write(body + "\n\n")
    print("[OK] NotebookLM用テキスト (投稿済 " + str(total) + " 件 + ストック " + str(stock_count) + " 件): " + notebooklm_path)

    # GDriveへ自動コピー（Drive for Desktop が同期 → Apps Script がGoogleドキュメントへ転記）
    gdrive_base = os.path.dirname(GDRIVE_DIR)
    if os.path.exists(gdrive_base):
        try:
            os.makedirs(GDRIVE_DIR, exist_ok=True)
            gdrive_path = os.path.join(GDRIVE_DIR, GDRIVE_FILE)
            import shutil
            shutil.copy2(notebooklm_path, gdrive_path)
            print("[OK] GDriveへコピー: " + gdrive_path)
        except OSError as e:
            print("[WARN] GDriveコピー失敗（ローカル出力は完了済み）: " + str(e))
    else:
        print("[WARN] GDrive (G:) が見つかりません。ローカル出力のみ")

    # 2. 削除候補CSV
    EXPORT_COLS = ["ポストID", "日付", "ポスト本文", "インプレッション数", "いいね", "返信", "リポスト", "ブックマーク", "_algo_score"]
    dead_path = os.path.join(OUT_DIR, "dead_posts_candidates.csv")
    with open(dead_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_COLS, extrasaction="ignore")
        writer.writeheader()
        for p in sorted(dead_candidates, key=lambda x: x["_algo_score"]):
            writer.writerow(p)
    print("[OK] 削除候補CSV (" + str(len(dead_candidates)) + " 件): " + dead_path)

    # 3. リサイクル候補CSV
    recycle_path = os.path.join(OUT_DIR, "recycle_candidates.csv")
    with open(recycle_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_COLS, extrasaction="ignore")
        writer.writeheader()
        for p in sorted(recycle_candidates, key=lambda x: x["_algo_score"], reverse=True):
            writer.writerow(p)
    print("[OK] リサイクル候補CSV (" + str(len(recycle_candidates)) + " 件): " + recycle_path)

    print()
    print("[次のステップ]")
    print("  1. Apps Script設定済みなら何もしなくてよい（Googleドキュメントへ毎日自動転記される）")
    print("     未設定なら docs/gdocs_archive_sync.md の手順で初回セットアップ")
    print("  2. NotebookLMを使う場合はソースの「同期」をクリック（Googleドキュメント参照時のみ有効）")
    print("  3. dead_posts_candidates.csv を確認 -> prune_dead_posts.py で削除 or recycler.py でリサイクル")


if __name__ == "__main__":
    main()
