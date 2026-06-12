"""
text_to_csv.py — AI（Gemini）生成テキストを投稿ストック用CSVへ自動変換する

使い方（ローカル、apps/auto-poster ルートで）:
    python utils/text_to_csv.py

入力:  data/inbox/raw_draft.txt（=====POST===== / =====END===== 区切りのブロック形式）
出力:  data/outbox/new_posts_YYYYMMDD_HHMMSS.csv（utf-8-sig・8列スキーマ）
       → bash scripts/push_drafts_to_conoha.sh で本番へマージする

入力フォーマット:
    =====POST=====
    [CATEGORY]カテゴリ名
    [BODY]
    本文のテキスト（複数行可）
    [REPLY]
    リプライ文（空の場合もあり）
    [TITLE]画像タイトル（感情系カテゴリ＝画像なし投稿では空欄が正規仕様）
    [ALT]代替テキスト（同上）
    =====END=====

設計:
- 管理IDは6桁の大文字16進数を自動生成（実行内・既存ストックと重複しない）
- フォーマットは常に tweet、ステータスは常に空欄（未投稿）
- BODY/REPLY内の改行は保持し、csvモジュールの標準クォートでエスケープする
- 必須項目は CATEGORY と BODY のみ。REPLY/TITLE/ALT は空欄でも正常（空文字でCSV出力）
- ConoHa WING（Python 3.6.15）にデプロイされても壊れないよう3.6互換構文のみ使用
"""

import csv
import io
import secrets
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set, Tuple

# ssh非TTY実行時（cron含む）はstdoutがASCIIになり日本語printで落ちるため強制UTF-8化
if (sys.stdout.encoding or "").lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_APP_ROOT  = Path(__file__).resolve().parent.parent
INPUT_TXT  = _APP_ROOT / "data" / "inbox" / "raw_draft.txt"
OUTBOX_DIR = _APP_ROOT / "data" / "outbox"
DRAFT_CSV  = _APP_ROOT / "data" / "drafts" / "stock_posts_draft.csv"
FIELDNAMES = ["管理ID", "カテゴリ", "フォーマット", "投稿文", "リプライ文", "画像タイトル", "ALT", "ステータス"]

POST_START = "=====POST====="
POST_END   = "=====END====="
# 行頭マーカー。BODY/REPLY は次のマーカーまでの複数行、それ以外は同一行の残りが値
MARKERS = ("[CATEGORY]", "[BODY]", "[REPLY]", "[TITLE]", "[ALT]")


def load_existing_ids() -> Set[str]:
    """既存ストックCSVの管理IDを返す（新規IDの重複防止用。CSVがなければ空集合）。"""
    if not DRAFT_CSV.exists():
        return set()
    with open(str(DRAFT_CSV), encoding="utf-8-sig", newline="") as f:
        return {(r.get("管理ID") or "").strip() for r in csv.DictReader(f)}


def generate_id(used: Set[str]) -> str:
    """未使用の6桁大文字16進数IDを生成する（例: A5F3B2）。"""
    while True:
        new_id = secrets.token_hex(3).upper()
        if new_id not in used:
            used.add(new_id)
            return new_id


def split_blocks(text: str) -> List[str]:
    """=====POST===== 〜 =====END===== で囲まれたブロック本文のリストを返す。"""
    blocks = []
    current = None  # type: Optional[List[str]]
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == POST_START:
            current = []
        elif stripped == POST_END:
            if current is not None:
                blocks.append("\n".join(current))
            current = None
        elif current is not None:
            current.append(line)
    return blocks


def parse_block(block: str) -> Tuple[Optional[dict], List[str]]:
    """1ブロックを解析して (fields, エラーリスト) を返す。失敗時 fields は None。"""
    fields = {}
    current_key = None  # type: Optional[str]
    buffer = []         # type: List[str]

    def flush():
        if current_key is not None:
            fields[current_key] = "\n".join(buffer).strip()

    for line in block.splitlines():
        matched = None
        for marker in MARKERS:
            if line.strip().startswith(marker):
                matched = marker
                break
        if matched:
            flush()
            current_key = matched
            rest = line.strip()[len(matched):].strip()
            buffer = [rest] if rest else []
        elif current_key is not None:
            buffer.append(line)
    flush()

    # 必須は CATEGORY と BODY のみ。TITLE/ALT は画像なし投稿（感情系）で空欄が正規仕様
    errors = []
    for marker, label in (("[CATEGORY]", "カテゴリ"), ("[BODY]", "本文")):
        if not fields.get(marker):
            errors.append("{}（{}）が空または未記載".format(marker, label))
    if errors:
        return None, errors

    return {
        "カテゴリ":     fields["[CATEGORY]"],
        "投稿文":       fields["[BODY]"],
        "リプライ文":   fields.get("[REPLY]", ""),
        "画像タイトル": fields.get("[TITLE]", ""),
        "ALT":          fields.get("[ALT]", ""),
    }, []


def main() -> None:
    if not INPUT_TXT.exists():
        print("[ERROR] 入力ファイルが見つかりません: {}".format(INPUT_TXT))
        sys.exit(1)

    with open(str(INPUT_TXT), encoding="utf-8-sig") as f:
        text = f.read()

    blocks = split_blocks(text)
    if not blocks:
        print("[ERROR] {} / {} で囲まれたブロックが見つかりません".format(POST_START, POST_END))
        sys.exit(1)

    used_ids = load_existing_ids()
    rows = []
    skipped = 0
    for i, block in enumerate(blocks, start=1):
        parsed, errors = parse_block(block)
        if parsed is None:
            skipped += 1
            print("[SKIP] ブロック{}: {}".format(i, " / ".join(errors)))
            continue
        rows.append({
            "管理ID":       generate_id(used_ids),
            "カテゴリ":     parsed["カテゴリ"],
            "フォーマット": "tweet",
            "投稿文":       parsed["投稿文"],
            "リプライ文":   parsed["リプライ文"],
            "画像タイトル": parsed["画像タイトル"],
            "ALT":          parsed["ALT"],
            "ステータス":   "",
        })

    if not rows:
        print("[ERROR] 有効なブロックが0件のためCSVは生成しません（スキップ {} 件）".format(skipped))
        sys.exit(1)

    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTBOX_DIR / "new_posts_{:%Y%m%d_%H%M%S}.csv".format(datetime.now())
    with open(str(out_path), "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print("[OK] 変換完了: {} 件（スキップ {} 件）".format(len(rows), skipped))
    print("[OK] 出力先: {}".format(out_path))
    print("次のステップ: bash scripts/push_drafts_to_conoha.sh --dry-run で本番反映を確認")


if __name__ == "__main__":
    main()
