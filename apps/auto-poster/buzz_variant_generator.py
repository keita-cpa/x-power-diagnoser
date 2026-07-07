"""
buzz_variant_generator.py — バズ番頭

過去のX Analyticsで高AlgoScoreを記録した投稿の「変形バリアント」を生成し、
stock_posts_draft.csv に追記する。

参考: 『CodexでXを完全自動化』記事のバズ番頭パターン
      → 実績上位投稿の感情フック構造・語りのリズムを学習し、別内容で再生成
      『loop設計』VERIFY→ITERATE原則
      → Analytics VERIFY 後、winning patternをITERATEにフィードバック

使い方:
    python buzz_variant_generator.py                    # Top3 x 3変形 = 最大9件
    python buzz_variant_generator.py --top 5            # Top5を対象
    python buzz_variant_generator.py --variants 2       # 1投稿あたり2変形
    python buzz_variant_generator.py --dry-run          # CSV書き込みなし（確認のみ）

前提:
    data/analytics/analytics_posts.csv が存在すること。
    なければ /project:monthly-analytics を先に実行してください。
"""

import argparse
import csv
import io
import sys
import time
import uuid
from pathlib import Path

from google.genai import types

# Windows cp932対策
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from post_generator import (
    client, MODEL_NAME, SAFETY_SETTINGS,
    evaluate_post, _build_system_instruction, load_rag_context,
)
from prompts import NO_RAG_CATEGORIES

_BASE_DIR     = Path(__file__).parent
ANALYTICS_CSV = _BASE_DIR / "data" / "analytics" / "analytics_posts.csv"
DRAFT_CSV     = _BASE_DIR / "data" / "drafts" / "stock_posts_draft.csv"
FIELDNAMES    = ["管理ID", "カテゴリ", "フォーマット", "投稿文", "リプライ文", "画像タイトル", "ALT", "ステータス"]

# X Analytics 日本語エクスポートの列名 → AlgoScore重み
_COL_WEIGHT = {
    "返信":                   5,
    "プロフィールへのアクセス数": 4,
    "ブックマーク":            3,
    "リポスト":               3,
    "詳細のクリック数":        2,
    "いいね":                 1,
}
_COL_TEXT = "ポスト本文"

# カテゴリ分類キーワード（prompts.py v6 / analyze_my_account.py と同期）
CATEGORY_KEYWORDS = {
    "お金と法律のお守り":           ["確定申告", "経費", "節税", "控除", "所得", "消費税", "源泉", "帳簿", "税務調査", "リスク", "勘違い", "誤解", "ガチレス"],
    "施術中のワンシーン・そっと解決": ["施術中", "会話", "聞かれ", "ポロッ", "相談され", "答えた", "そうなんですか"],
    "良客の目線・メンエス愛":       ["気遣い", "救われ", "癒や", "入室", "タオル", "照明", "通", "お店", "セラピストさん"],
    "痛みの代弁・がんばりの承認":   ["誰にも言えない", "孤独", "消耗", "笑顔", "演技", "がんばり", "承認", "しんどい", "疲れ"],
    "趣味・人間味・日常":           ["小説", "本", "映画", "読んだ", "コンビニ", "帰り道", "季節", "失敗"],
}


def _classify(text: str) -> str:
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return cat
    return "お金と法律のお守り"


def load_top_posts(n: int) -> list[dict]:
    """analytics_posts.csv からAlgoScore上位n件を返す（リプライ除外）。"""
    if not ANALYTICS_CSV.exists():
        print(f"[ERROR] {ANALYTICS_CSV} が存在しません。")
        print("先に /project:monthly-analytics を実行してください。")
        sys.exit(1)

    rows = []
    with open(ANALYTICS_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            text = row.get(_COL_TEXT, "").strip()
            if not text or text.startswith("@"):
                continue
            score = sum(
                int(row.get(col, 0) or 0) * w
                for col, w in _COL_WEIGHT.items()
                if col in row
            )
            rows.append({
                "text":     text,
                "score":    score,
                "category": _classify(text),
            })

    rows.sort(key=lambda r: r["score"], reverse=True)
    if not rows:
        print("[ERROR] 有効な投稿が見つかりませんでした。analytics_posts.csv を確認してください。")
        sys.exit(1)

    return rows[:n]


def _generate_variant(original_text: str, category: str, score: int, knowledge_text: str | None) -> str | None:
    """
    original_text を手本に、同じ感情フック構造で別内容のバリアントを1本生成する。
    QC合格なら投稿文を返す。失敗/REJECT なら None を返す。
    """
    is_emotional = category in NO_RAG_CATEGORIES
    system_instr = _build_system_instruction(output_mode="tweet", rag_mode=not is_emotional)

    variant_block = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【バズ番頭モード: 実績上位投稿の変形バリアント生成】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

以下はAlgoScore={score}を実際に記録した高実績の投稿です（カテゴリ: {category}）。

この投稿と同じ「感情フックの型・語りのリズム・CTA形式・文体の温度感」を踏襲しながら、
具体的な内容（エピソード・数字・法律条文・場面）を変えた別の投稿を1本生成してください。

【手本投稿 AlgoScore={score}】
{original_text}

【バリアント生成ルール（絶対厳守）】
・手本の「構造・フック型・CTAパターン」は踏襲する
・手本の「具体的なエピソード・数字・条文・場面」は一切コピーしない（別のネタで書く）
・カテゴリ「{category}」として生成する
・QC3基準（ハルシネーション禁止・暴言禁止・事実誤認禁止）は通常通り厳守
・出力は投稿文のみ。前置き・説明・タグは不要
"""

    rag_section = ""
    if not is_emotional and knowledge_text:
        rag_section = f"\n\n【参考ナレッジ（事実根拠として使用・引用表記禁止）】\n{knowledge_text[:8000]}"

    user_content = variant_block + rag_section

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_instr,
                    safety_settings=SAFETY_SETTINGS,
                    temperature=0.95,
                ),
            )
            text = (resp.text or "").strip()
            if not text:
                print(f"  [WARN] 空レスポンス（試行{attempt}/{max_retries}）")
                time.sleep(2)
                continue

            kt = knowledge_text if not is_emotional else None
            verdict = evaluate_post(text, kt)
            if verdict.startswith("[PASS]"):
                return text
            print(f"  [QC REJECT] {verdict[:100]}")
            return None

        except Exception as e:
            print(f"  [ERROR] 試行{attempt}/{max_retries}: {e}")
            if attempt < max_retries:
                time.sleep(2)
    return None


def _append_to_draft(post_id: str, category: str, text: str) -> None:
    file_exists = DRAFT_CSV.exists()
    with open(DRAFT_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(FIELDNAMES)
        writer.writerow([post_id, category, "tweet", text, "", "", "", ""])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="バズ番頭: 高AlgoScore投稿の変形バリアントを生成してCSVに追記"
    )
    parser.add_argument("--top",      type=int, default=3, help="対象Top-N投稿（デフォルト: 3）")
    parser.add_argument("--variants", type=int, default=3, help="1投稿あたりの生成数（デフォルト: 3）")
    parser.add_argument("--dry-run",  action="store_true",  help="CSV書き込みなし（プレビューのみ）")
    args = parser.parse_args()

    total_target = args.top * args.variants
    print(f"[バズ番頭] Top-{args.top}投稿 x {args.variants}変形 = 最大{total_target}件を生成します")
    if args.dry_run:
        print("[dry-run] CSV書き込みはスキップします")
    print()

    top_posts = load_top_posts(args.top)
    rag_text  = load_rag_context()

    total_added = 0
    for rank, post in enumerate(top_posts, 1):
        print(f"[Top-{rank}] AlgoScore={post['score']} / カテゴリ={post['category']}")
        print(f"  手本: {post['text'][:70]}...")
        print()

        kt        = rag_text if post["category"] not in NO_RAG_CATEGORIES else None
        generated = 0
        attempts  = 0
        max_tries = args.variants * 2

        while generated < args.variants and attempts < max_tries:
            attempts += 1
            text = _generate_variant(post["text"], post["category"], post["score"], kt)
            if text:
                generated += 1
                post_id = uuid.uuid4().hex[:6].upper()
                print(f"  [PASS] バリアント{generated}: {text[:70]}...")
                if not args.dry_run:
                    _append_to_draft(post_id, post["category"], text)
                    total_added += 1
            time.sleep(1)

        if generated < args.variants:
            print(f"  [WARN] {generated}/{args.variants}件のみ生成（QC失敗または試行上限）")
        print()

    if not args.dry_run:
        print(f"[完了] {total_added}件を {DRAFT_CSV.name} に追記しました")
    else:
        print("[dry-run完了] CSV書き込みはスキップしました")


if __name__ == "__main__":
    main()
