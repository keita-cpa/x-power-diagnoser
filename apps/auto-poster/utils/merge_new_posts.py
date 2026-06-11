"""
merge_new_posts.py — outbox差分CSVを本番ストックCSVへ安全にマージする（ConoHa側で実行）

使い方（ConoHa上、x-autoルートで）:
    python3 utils/merge_new_posts.py data/inbox/new_posts_20260611_120000.csv

設計:
- 管理ID または 投稿文 が既存と一致する行はスキップ（冪等 — 同じファイルを2回流しても安全）
- 本番CSVの既存行・postedステータスには一切触れない（追記のみ）
- 追記前バックアップ + 追記後の列数/行数アサーション（csv-safety.md 準拠）
"""

import csv
import shutil
import sys
from datetime import datetime
from pathlib import Path

_APP_ROOT  = Path(__file__).resolve().parent.parent
DRAFT_CSV  = _APP_ROOT / "data" / "drafts" / "stock_posts_draft.csv"
FIELDNAMES = ["管理ID", "カテゴリ", "フォーマット", "投稿文", "リプライ文", "画像タイトル", "ALT", "ステータス"]


def load_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDNAMES:
            print(f"[ERROR] 列構成が不正: {reader.fieldnames}")
            sys.exit(1)
        return list(reader)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python3 utils/merge_new_posts.py <new_posts.csv>")
        sys.exit(1)

    incoming_path = Path(sys.argv[1])
    if not incoming_path.exists():
        print(f"[ERROR] ファイルが見つかりません: {incoming_path}")
        sys.exit(1)

    incoming = load_rows(incoming_path)

    existing: list[dict] = []
    if DRAFT_CSV.exists():
        existing = load_rows(DRAFT_CSV)
    existing_ids    = {r["管理ID"] for r in existing}
    existing_bodies = {(r["投稿文"] or "").strip() for r in existing}

    new_rows = [
        r for r in incoming
        if r["管理ID"] not in existing_ids
        and (r["投稿文"] or "").strip() not in existing_bodies
    ]
    skipped = len(incoming) - len(new_rows)

    if not new_rows:
        print(f"[OK] 追加 0 件 / スキップ {skipped} 件（すべて登録済み）")
        return

    if DRAFT_CSV.exists():
        backup = DRAFT_CSV.with_name(
            f"stock_posts_draft_backup_{datetime.now():%Y%m%d_%H%M%S}.csv"
        )
        shutil.copy2(DRAFT_CSV, backup)
        print(f"[BACKUP] {backup.name}")

    before = len(existing)
    file_exists = DRAFT_CSV.exists()
    DRAFT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(DRAFT_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        for r in new_rows:
            writer.writerow({k: r.get(k, "") for k in FIELDNAMES})

    after_rows = load_rows(DRAFT_CSV)
    assert len(after_rows) == before + len(new_rows), \
        f"行数エラー: {before} + {len(new_rows)} != {len(after_rows)}"

    print(f"[OK] 追加 {len(new_rows)} 件 / スキップ {skipped} 件 / ストック総数 {len(after_rows)} 行")


if __name__ == "__main__":
    main()
