"""
recycler.py -- 死にポストリサイクラー

dead_posts_queue.csv の低スコート投稿を以下のフローで処理する:
1. analytics_posts.csv + posted_history.csv と突合 → dead_posts_archive.csv に全情報を保存
2. アーカイブの未処理行を Gemini Flash でリライト → stock_posts_draft.csv に追記

Usage:
    python recycler.py                # フル実行（突合→アーカイブ→リライト→追記）
    python recycler.py --archive-only  # 突合・アーカイブのみ（リライトしない）
    python recycler.py --dry-run       # 表示のみ（CSV書き込みなし）
    python recycler.py --recycle-only  # 既存アーカイブからリライトのみ実行

注意:
- ローカル実行専用（Python 3.13）。ConoHa Python 3.6 には置かない。
- config.py は直接 Read しない（APIキー漏洩防止）。import のみ。
- stock_posts_draft.csv への書き込みは追記モードのみ（csv-safety.md 準拠）。
"""

import argparse
import csv
import datetime
import os
import pathlib
import time

from google import genai
from google.genai import types

from config import GEMINI_API_KEY

DRAFT_FIELDNAMES = ["管理ID", "カテゴリ", "フォーマット", "投稿文", "リプライ文", "画像タイトル", "ALT", "ステータス"]

BASE_DIR = pathlib.Path(__file__).parent

QUEUE_PATH    = BASE_DIR / "data" / "analytics" / "dead_posts_queue.csv"
ANALYTICS_CSV = BASE_DIR / "data" / "analytics" / "analytics_posts.csv"
HISTORY_CSV   = BASE_DIR / "data" / "logs" / "posted_history.csv"
ARCHIVE_CSV   = BASE_DIR / "data" / "analytics" / "dead_posts_archive.csv"
DRAFT_CSV     = BASE_DIR / "data" / "drafts" / "stock_posts_draft.csv"

ENCODING = "utf-8-sig"

ARCHIVE_FIELDNAMES = [
    "ポストID", "投稿日", "削除日", "カテゴリ", "フォーマット",
    "AlgoScore", "投稿文全文", "リサイクル済み",
]

MAX_RETRIES = 3
RETRY_WAIT  = 2

META_MODEL_NAME = "gemini-3-flash-preview"

SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",         threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT",  threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT",  threshold="BLOCK_NONE"),
]

client = genai.Client(api_key=GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# AlgoScore 計算
# ---------------------------------------------------------------------------

def calc_algo_score(row: dict) -> float:
    """analytics_posts.csv の1行から AlgoScore を計算して返す。"""
    def _f(key: str) -> float:
        try:
            return float(row.get(key, 0) or 0)
        except (ValueError, TypeError):
            return 0.0

    like     = _f("いいね")
    bookmark = _f("ブックマーク")
    rt       = _f("リポスト")
    reply    = _f("返信")
    return like * 0.5 + bookmark * 10.0 + rt * 1.0 + reply * 13.5


# ---------------------------------------------------------------------------
# 突合ロジック
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """突合用に先頭50文字を正規化（改行・全角スペース→半角スペース・strip）。"""
    return text.replace("\n", " ").replace("\r", " ").replace("　", " ").strip()[:50]


def load_queue() -> list[dict]:
    if not QUEUE_PATH.exists():
        return []
    with open(QUEUE_PATH, encoding=ENCODING, newline="") as f:
        return list(csv.DictReader(f))


def load_analytics() -> dict[str, dict]:
    """analytics_posts.csv を {ポストID: row} の辞書で返す。"""
    if not ANALYTICS_CSV.exists():
        print("[WARN] analytics_posts.csv が見つかりません。")
        return {}
    with open(ANALYTICS_CSV, encoding=ENCODING, newline="") as f:
        rows = list(csv.DictReader(f))
    return {r["ポストID"].strip(): r for r in rows if r.get("ポストID")}


def load_history() -> list[dict]:
    """posted_history.csv を全件リストで返す。"""
    if not HISTORY_CSV.exists():
        print("[WARN] posted_history.csv が見つかりません。")
        return []
    with open(HISTORY_CSV, encoding=ENCODING, newline="") as f:
        return list(csv.DictReader(f))


def load_archive() -> list[dict]:
    """dead_posts_archive.csv を全件リストで返す。なければ空リスト。"""
    if not ARCHIVE_CSV.exists():
        return []
    with open(ARCHIVE_CSV, encoding=ENCODING, newline="") as f:
        return list(csv.DictReader(f))


def find_history_row(post_id: str, analytics_text: str, history_rows: list[dict]) -> dict:
    """
    posted_history.csv から対応行を探す。
    1. ポストID列が存在し一致する場合は直接返す。
    2. なければ analytics_posts の本文先頭50文字と posted_history の投稿文先頭50文字で fuzzy 突合。
    """
    # ポストID 直接突合
    for h in history_rows:
        if h.get("ポストID", "").strip() == post_id:
            return h

    # fuzzy 突合（本文先頭50文字）
    needle = _normalize(analytics_text)
    if not needle:
        return {}
    for h in history_rows:
        hay = _normalize(h.get("投稿文", ""))
        if needle and hay and (needle[:40] in hay or hay[:40] in needle):
            return h
    return {}


# ---------------------------------------------------------------------------
# アーカイブ生成
# ---------------------------------------------------------------------------

def build_archive(dry_run: bool = False) -> list[dict]:
    """
    dead_posts_queue.csv + analytics_posts.csv + posted_history.csv を突合し、
    dead_posts_archive.csv に保存して新規追加行を返す。
    """
    queue    = load_queue()
    if not queue:
        print("[INFO] dead_posts_queue.csv が空です。/project:monthly-analytics を先に実行してください。")
        return []

    analytics = load_analytics()
    history   = load_history()

    # 既存アーカイブで処理済みのポストIDを取得
    existing = {r["ポストID"].strip() for r in load_archive() if r.get("ポストID")}

    today = datetime.date.today().isoformat()
    new_rows = []

    for q in queue:
        post_id = q.get("ポストID", "").strip()
        if not post_id:
            continue
        if post_id in existing:
            print(f"  [SKIP] 既にアーカイブ済み: ID={post_id}")
            continue

        # analytics_posts.csv から AlgoScore・本文取得
        ana_row = analytics.get(post_id, {})
        if not ana_row:
            print(f"  [WARN] analytics_posts.csv に見つかりません: ID={post_id}")
        algo_score = calc_algo_score(ana_row)
        analytics_text = ana_row.get("ポスト本文", "")

        # posted_history.csv から全文・カテゴリ・フォーマット取得
        hist_row = find_history_row(post_id, analytics_text, history)
        full_text = hist_row.get("投稿文", analytics_text)  # histになければ analytics の本文で代替
        category  = hist_row.get("カテゴリ", "")
        fmt       = hist_row.get("フォーマット", "tweet")

        archive_row = {
            "ポストID":    post_id,
            "投稿日":      q.get("日付", "").strip(),
            "削除日":      today,
            "カテゴリ":    category,
            "フォーマット": fmt,
            "AlgoScore":   f"{algo_score:.1f}",
            "投稿文全文":  full_text,
            "リサイクル済み": "",
        }

        if dry_run:
            print(f"  [DRY-RUN] アーカイブ対象: ID={post_id} | AlgoScore={algo_score:.1f} | カテゴリ={category}")
            print(f"           本文先頭: {full_text[:40]}...")
        else:
            new_rows.append(archive_row)

    if not dry_run and new_rows:
        write_header = not ARCHIVE_CSV.exists()
        with open(ARCHIVE_CSV, "a", encoding=ENCODING, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ARCHIVE_FIELDNAMES)
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)
        print(f"[OK] dead_posts_archive.csv に {len(new_rows)} 件追記しました。")

    return new_rows


# ---------------------------------------------------------------------------
# Gemini リライト
# ---------------------------------------------------------------------------

RECYCLE_SYSTEM_PROMPT = """\
あなたは @Keita_CPA（Big4出身の公認会計士・税理士）のX投稿を担当するライターです。
ペルソナv2「3つの顔」（良客・頼れる専門家・話すと楽しい人）に厳密に従って投稿を書き直してください。

絶対ルール:
- 一人称「ぼく」・二人称「あなた」
- 絵文字禁止・Markdown太字（**）禁止・URL禁止・ハッシュタグ禁止
- 関西弁禁止（完全標準語）
- 性的ニュアンス禁止
- 280文字以内（文字数を超えないこと）
- 法令・税務数字はナレッジベース外の捏造禁止
"""

RECYCLE_PROMPT_TEMPLATE = """\
以下の投稿は「伸びなかった投稿」です（AlgoScore={score}）。
カテゴリ: {category}

【元の投稿文】
{original}

---

この投稿が「伸びなかった理由」を1〜2文で簡潔に分析したうえで、
同じカテゴリ・テーマを保ちながら、以下の観点でリライトしてください:

1. フック（冒頭2〜3行）を「私のことだ」と手が止まる共感型か「え？」と意外性型に変える
2. 一般論を避け、具体的なシーンや数字・条文を入れて読み応えを出す
3. 元の投稿と「書き出し」と「フォーカスするポイント」を変える（同じ書き方のリサイクルは禁止）
4. 結びはそっと上向き・温度のしっぽで終わる

【出力フォーマット（厳守）】
分析: （伸びなかった理由・1〜2文）
リライト:
（リライトした投稿文のみ。マーカー・番号・説明文は不要）
"""


def rewrite_with_gemini(original: str, category: str, algo_score: float) -> str | None:
    """Gemini Flash で投稿をリライトして返す。失敗時は None。"""
    prompt = RECYCLE_PROMPT_TEMPLATE.format(
        score=f"{algo_score:.1f}",
        category=category or "不明",
        original=original,
    )

    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=META_MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=RECYCLE_SYSTEM_PROMPT,
                    temperature=0.85,
                    safety_settings=SAFETY_SETTINGS,
                ),
            )
            raw = (response.text or "").strip()
            if not raw:
                raise ValueError("Geminiが空テキストを返しました")

            # "リライト:" 以降の本文を取り出す
            if "リライト:" in raw:
                rewritten = raw.split("リライト:", 1)[1].strip()
            elif "リライト：" in raw:
                rewritten = raw.split("リライト：", 1)[1].strip()
            else:
                rewritten = raw  # マーカーがない場合はそのまま

            return rewritten

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
                continue
            print(f"  [ERROR] Gemini リライト失敗（{MAX_RETRIES}回）: {e}")
            return None


# ---------------------------------------------------------------------------
# stock_posts_draft.csv への追記
# ---------------------------------------------------------------------------

def _next_recycle_id() -> str:
    """既存の draft CSV から最大の RCY-XXX 番号を取得して次の ID を返す。"""
    if not DRAFT_CSV.exists():
        return "RCY-001"
    with open(DRAFT_CSV, encoding=ENCODING, newline="") as f:
        reader = csv.DictReader(f)
        max_n = 0
        for row in reader:
            mid = row.get("管理ID", "")
            if mid.startswith("RCY-"):
                try:
                    max_n = max(max_n, int(mid[4:]))
                except ValueError:
                    pass
    return f"RCY-{max_n + 1:03d}"


def append_to_draft(rewritten: str, category: str, fmt: str = "tweet") -> None:
    """リライト済み投稿を stock_posts_draft.csv に追記する。"""
    new_id = _next_recycle_id()
    draft_row = {
        "管理ID":    new_id,
        "カテゴリ":  category or "趣味・人間味・日常",
        "フォーマット": fmt,
        "投稿文":    rewritten,
        "リプライ文": "",
        "画像タイトル": "",
        "ALT":       "",
        "ステータス": "",
    }
    write_header = not DRAFT_CSV.exists()
    with open(DRAFT_CSV, "a", encoding=ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DRAFT_FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(draft_row)
    print(f"  [OK] stock_posts_draft.csv に追記: {new_id} | {category} | {rewritten[:30]}...")


def mark_recycled(post_id: str) -> None:
    """dead_posts_archive.csv の対象行を リサイクル済み='recycled' に更新する。"""
    if not ARCHIVE_CSV.exists():
        return
    with open(ARCHIVE_CSV, encoding=ENCODING, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r.get("ポストID", "").strip() == post_id:
            r["リサイクル済み"] = "recycled"
    with open(ARCHIVE_CSV, "w", encoding=ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ARCHIVE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="死にポストリサイクラー")
    parser.add_argument("--dry-run",       action="store_true", help="表示のみ（CSV書き込みなし）")
    parser.add_argument("--archive-only",  action="store_true", help="突合・アーカイブのみ（リライトしない）")
    parser.add_argument("--recycle-only",  action="store_true", help="既存アーカイブからリライトのみ実行")
    args = parser.parse_args()

    print("=" * 60)
    print("recycler.py -- 死にポストリサイクラー")
    print("=" * 60)

    # --- Step 1: アーカイブ生成 ---
    if not args.recycle_only:
        print("\n[STEP 1] 突合・アーカイブ生成...")
        build_archive(dry_run=args.dry_run)

    if args.archive_only or args.dry_run:
        print("\n[INFO] --archive-only / --dry-run のためリライトをスキップします。")
        return

    # --- Step 2: リライト・追記 ---
    print("\n[STEP 2] Gemini Flash でリライト中...")
    archive = load_archive()
    targets = [r for r in archive if not r.get("リサイクル済み")]

    if not targets:
        print("[INFO] リサイクル対象がありません（全件リサイクル済みまたはアーカイブ空）。")
        return

    print(f"[INFO] リサイクル対象: {len(targets)} 件")
    success = 0

    for r in targets:
        post_id    = r.get("ポストID", "")
        original   = r.get("投稿文全文", "")
        category   = r.get("カテゴリ", "")
        fmt        = r.get("フォーマット", "tweet")
        algo_score = float(r.get("AlgoScore", 0) or 0)

        print(f"\n  処理中: ID={post_id} | AlgoScore={algo_score:.1f} | カテゴリ={category}")
        print(f"  元本文先頭: {original[:40]}...")

        rewritten = rewrite_with_gemini(original, category, algo_score)
        if rewritten is None:
            print(f"  [SKIP] リライト失敗。スキップします。")
            continue

        append_to_draft(rewritten, category, fmt)
        mark_recycled(post_id)
        success += 1
        time.sleep(1)  # レート制限対策

    print(f"\n[DONE] リサイクル完了: {success}/{len(targets)} 件")
    print(f"       stock_posts_draft.csv に RCY-xxx として追記されました。")
    print(f"       投稿前に内容を確認してください（QC審査は mini_bulk_generator.py と同等）。")


if __name__ == "__main__":
    main()
