"""
analyze_my_account.py — 自分のXアカウントのパフォーマンス自己分析ツール

X API（OAuth 1.0a User Context）で自分の過去ポストと public_metrics /
non_public_metrics を直接取得し、data/analytics/my_performance.csv に蓄積。
カテゴリ別の AlgoScore_api 集計と、AI定性分析用プロンプトの生成までを行う。

使い方:
    python analyze_my_account.py                          # 取得 → CSV更新 → 統計サマリー
    python analyze_my_account.py --max 100                # 取得件数の上限（既定200）
    python analyze_my_account.py --no-fetch               # 取得せず既存CSVで集計のみ
    python analyze_my_account.py --print-analysis-prompt  # 定額LLM用の分析プロンプトを出力（0円）
    python analyze_my_account.py --ai                     # Gemini Proで定性分析レポート生成（約3〜5円）

注意（APIの限界 — レポート解釈時に必ず意識すること）:
- AlgoScore_api は Detail Click（API v2に存在しない）を除外した参考値。
  X Analytics CSV 由来の正式 AlgoScore とは別物として扱うこと。
- non_public_metrics（プロフクリック等）は直近30日の自分のポストのみ取得可能。
  それ以前のポストは profile_clicks=0 として集計される。
- weight改定の一次根拠は月次の X Analytics CSV（SOP §11）。本ツールは中間チェック・
  テーマ発見・bookmark補完のためのオンデマンド分析に使う。
"""

import argparse
import csv
import io
import re
import shutil
import statistics
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows cp932 対策: 標準出力を UTF-8 に強制（mini_bulk_generator.py と同一）
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_BASE_DIR   = Path(__file__).parent
PERF_CSV    = _BASE_DIR / "data" / "analytics" / "my_performance.csv"
HISTORY_CSV = _BASE_DIR / "data" / "logs" / "posted_history.csv"

PERF_FIELDS = [
    "tweet_id", "created_at", "type", "カテゴリ", "投稿文",
    "impressions", "likes", "replies", "retweets", "quotes", "bookmarks",
    "profile_clicks", "algo_score_api", "fetched_at",
]
_NUM_FIELDS = ["impressions", "likes", "replies", "retweets", "quotes",
               "bookmarks", "profile_clicks", "algo_score_api"]

# カテゴリ判定キーワード（.claude/commands/monthly-analytics.md と同期・新カテゴリ優先）
CATEGORY_KEYWORDS = {
    "お金と法律のお守り":           ["確定申告", "経費", "節税", "控除", "所得", "消費税", "源泉", "帳簿", "税務調査", "リスク", "勘違い", "誤解", "ガチレス"],
    "施術中のワンシーン・そっと解決": ["施術中", "会話", "聞かれ", "ポロッ", "相談され", "答えた", "そうなんですか"],
    "良客の目線・メンエス愛":       ["気遣い", "救われ", "癒や", "入室", "タオル", "照明", "通", "お店", "セラピストさん"],
    "痛みの代弁・がんばりの承認":   ["誰にも言えない", "孤独", "消耗", "笑顔", "演技", "がんばり", "承認", "しんどい", "疲れ"],
    "趣味・人間味・日常":           ["小説", "本", "映画", "読んだ", "コンビニ", "帰り道", "季節", "失敗"],
    "マインド・喝":                 ["メンタル", "マインド", "覚悟", "逃げる", "稼げ"],
    "防衛実績・事例":               ["事例", "実績", "依頼", "立ち会"],
    "日常・利用者としての共感":     ["今日", "ちょっと", "なんか", "気持ち"],
}


# ──────────────────────────────────────────
# X API クライアント・取得
# ──────────────────────────────────────────

def get_client(wait_on_rate_limit=True):
    """OAuth 1.0a User Context クライアント（non_public_metrics の取得に必須）。"""
    import tweepy
    from config import X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
    return tweepy.Client(
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=wait_on_rate_limit,
    )


def _fetch_pages(client, uid, max_count, tweet_fields, start_time=None):
    """ページネーションで自分のポストを最大 max_count 件取得する。"""
    collected, token = [], None
    while len(collected) < max_count:
        page_size = min(100, max(5, max_count - len(collected)))
        resp = client.get_users_tweets(
            id=uid,
            max_results=page_size,
            tweet_fields=tweet_fields,
            exclude=["retweets"],
            pagination_token=token,
            start_time=start_time,
            user_auth=True,
        )
        if not resp.data:
            break
        collected.extend(resp.data)
        token = (resp.meta or {}).get("next_token")
        if not token:
            break
    return collected[:max_count]


def fetch_my_tweets(max_count):
    """
    二段取得（400エラー回避）:
      パス1: 全期間の public_metrics（最大 max_count 件）
      パス2: 直近29日のみ non_public_metrics（profile_clicks 等）
    Returns: (tweets, non_public_map, user_metrics)
      user_metrics: {"followers": int, "following": int, "ff_ratio": float}
    """
    client = get_client()
    me = client.get_me(user_auth=True, user_fields=["public_metrics"])
    uid = me.data.id
    print(f"[FETCH] @{me.data.username} の直近 {max_count} 件を取得中...")

    # FF比率の収集
    user_pm = getattr(me.data, "public_metrics", None) or {}
    followers = int(user_pm.get("followers_count", 0))
    following = int(user_pm.get("following_count", 0))
    ff_ratio = round(followers / following, 2) if following > 0 else 0.0
    user_metrics = {"followers": followers, "following": following, "ff_ratio": ff_ratio}

    tweets = _fetch_pages(
        client, uid, max_count,
        tweet_fields=["created_at", "public_metrics", "referenced_tweets"],
    )
    print(f"[FETCH] public_metrics: {len(tweets)} 件")

    non_public_map = {}
    try:
        start = (datetime.now(timezone.utc) - timedelta(days=29)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent = _fetch_pages(
            client, uid, max_count,
            tweet_fields=["non_public_metrics"],
            start_time=start,
        )
        for t in recent:
            np = getattr(t, "non_public_metrics", None) or {}
            non_public_map[str(t.id)] = np
        print(f"[FETCH] non_public_metrics（直近29日）: {len(non_public_map)} 件")
    except Exception as e:
        print(f"[WARN] non_public_metrics の取得に失敗（profile_clicks=0で続行）: {e}")

    return tweets, non_public_map, user_metrics


# ──────────────────────────────────────────
# カテゴリ突合・スコア計算
# ──────────────────────────────────────────

def _normalize(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s)))[:60]


def load_history_category_map() -> dict[str, str]:
    """posted_history.csv から 正規化投稿文(先頭60字) → カテゴリ の辞書を作る。"""
    mapping: dict[str, str] = {}
    if not HISTORY_CSV.exists():
        return mapping
    try:
        with open(HISTORY_CSV, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                text = (row.get("投稿文") or "").strip()
                cat = (row.get("カテゴリ") or "").strip()
                if text and cat:
                    mapping[_normalize(text)] = cat
    except (OSError, UnicodeDecodeError) as e:
        print(f"[WARN] posted_history.csv の読み込みに失敗（キーワード分類のみで続行）: {e}")
    return mapping


def classify(text: str, history_map: dict[str, str], post_type: str) -> str:
    if post_type == "reply":
        return "リプライ"
    hit = history_map.get(_normalize(text))
    if hit:
        return hit
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return cat
    return "未分類"


def build_row(tweet, non_public_map, history_map, fetched_at):
    pm = tweet.public_metrics or {}
    np = non_public_map.get(str(tweet.id), {})

    refs = getattr(tweet, "referenced_tweets", None) or []
    post_type = "reply" if any(getattr(r, "type", "") == "replied_to" for r in refs) else "post"

    likes     = int(pm.get("like_count", 0))
    replies   = int(pm.get("reply_count", 0))
    retweets  = int(pm.get("retweet_count", 0))
    quotes    = int(pm.get("quote_count", 0))
    bookmarks = int(pm.get("bookmark_count", 0))
    pclicks   = int(np.get("user_profile_clicks", 0))

    # AlgoScore_api = Reply×5 + PClick×4 + Bookmark×3 + RT×3 + Like×1
    # ※ Detail×2 はAPI v2に存在しないため除外（正式AlgoScoreとは別物）。quotes はRTに含めず参考記録のみ
    score = replies * 5 + pclicks * 4 + bookmarks * 3 + retweets * 3 + likes * 1

    created = tweet.created_at.strftime("%Y-%m-%d %H:%M") if tweet.created_at else ""
    return {
        "tweet_id": str(tweet.id),
        "created_at": created,
        "type": post_type,
        "カテゴリ": classify(tweet.text, history_map, post_type),
        "投稿文": tweet.text,
        "impressions": int(pm.get("impression_count", 0)),
        "likes": likes, "replies": replies, "retweets": retweets,
        "quotes": quotes, "bookmarks": bookmarks,
        "profile_clicks": pclicks,
        "algo_score_api": score,
        "fetched_at": fetched_at,
    }


# ──────────────────────────────────────────
# CSV upsert（冪等）
# ──────────────────────────────────────────

def load_perf_rows() -> list[dict]:
    if not PERF_CSV.exists():
        return []
    with open(PERF_CSV, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def upsert_perf_csv(new_rows: list[dict]) -> tuple[int, int]:
    """tweet_id キーで upsert する（再取得時はメトリクスを上書き更新）。"""
    existing = {r["tweet_id"]: r for r in load_perf_rows()}
    added = sum(1 for r in new_rows if r["tweet_id"] not in existing)
    updated = len(new_rows) - added
    for r in new_rows:
        existing[r["tweet_id"]] = r

    merged = sorted(existing.values(), key=lambda r: r.get("created_at", ""), reverse=True)

    PERF_CSV.parent.mkdir(parents=True, exist_ok=True)
    if PERF_CSV.exists():
        backup = PERF_CSV.with_name(f"my_performance_backup_{datetime.now():%Y%m%d_%H%M%S}.csv")
        shutil.copy2(PERF_CSV, backup)

    with open(PERF_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PERF_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged)

    # アサーション: 列構成と行数
    with open(PERF_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == PERF_FIELDS, f"列構成エラー: {header}"
        count = sum(1 for _ in reader)
    assert count == len(merged), f"行数エラー: {count} != {len(merged)}"
    return added, updated


# ──────────────────────────────────────────
# 集計サマリー（純Python）
# ──────────────────────────────────────────

def _to_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def summarize(rows: list[dict], user_metrics: dict = None) -> str:
    if not rows:
        return "[INFO] データがありません"
    lines = []

    # ── FF比率セクション ──────────────────────────────
    if user_metrics:
        followers = user_metrics.get("followers", 0)
        following = user_metrics.get("following", 0)
        ff_ratio  = user_metrics.get("ff_ratio", 0.0)
        ff_warn   = " [WARNING: FF比率 < 1.0 = フォローが多すぎる]" if ff_ratio < 1.0 and following > 0 else ""
        ff_ideal  = " [GOOD: 健全なFF比率]" if ff_ratio >= 2.0 else ""
        lines.append(f"FF比率: フォロワー {followers:,} / フォロー {following:,} = {ff_ratio:.2f}{ff_warn}{ff_ideal}")
        lines.append("")

    # ── 基本統計 ──────────────────────────────────────
    post_rows  = [r for r in rows if r["type"] == "post"]
    reply_rows = [r for r in rows if r["type"] == "reply"]
    lines.append(f"対象: {len(rows)} 件（post {len(post_rows)} / reply {len(reply_rows)}）")
    lines.append("")

    # ── IMPトレンド・スパム検知 ───────────────────────
    now = datetime.now(timezone.utc)
    cutoff_7d  = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    cutoff_30d = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    recent_7d  = [r for r in post_rows if (r.get("created_at") or "") >= cutoff_7d]
    recent_30d = [r for r in post_rows if (r.get("created_at") or "") >= cutoff_30d]
    if recent_7d and recent_30d:
        avg_7d  = statistics.mean(_to_int(r["impressions"]) for r in recent_7d)
        avg_30d = statistics.mean(_to_int(r["impressions"]) for r in recent_30d)
        trend_pct = (avg_7d / avg_30d * 100) if avg_30d > 0 else 0
        trend_str = f"{trend_pct:.0f}%（直近7日平均 {avg_7d:.0f} vs 30日平均 {avg_30d:.0f}）"
        if trend_pct < 50:
            lines.append(f"[WARNING] IMP急落を検知: 7日平均が30日平均の {trend_pct:.0f}% にとどまる")
            lines.append("  → スパム判定・著者多様性ペナルティ・Shadow Banの可能性あり")
            lines.append(f"  IMP推移: {trend_str}")
        elif trend_pct < 75:
            lines.append(f"[CAUTION] IMP低下傾向: {trend_str}")
        else:
            lines.append(f"IMP推移（健全）: {trend_str}")
        lines.append("")

    # ── エンゲージ率サマリー ─────────────────────────
    if post_rows:
        total_imp  = sum(_to_int(r["impressions"]) for r in post_rows)
        total_rep  = sum(_to_int(r["replies"])     for r in post_rows)
        total_bkm  = sum(_to_int(r["bookmarks"])   for r in post_rows)
        total_pclk = sum(_to_int(r["profile_clicks"]) for r in post_rows)
        if total_imp > 0:
            lines.append("エンゲージ率（post のみ・参考値）:")
            lines.append(f"  リプライ率  : {total_rep  / total_imp * 100:.3f}%  （{total_rep} / {total_imp} IMP）")
            lines.append(f"  ブックマーク率: {total_bkm  / total_imp * 100:.3f}%  （{total_bkm} / {total_imp} IMP）")
            lines.append(f"  プロフクリック率: {total_pclk / total_imp * 100:.3f}%  （{total_pclk} / {total_imp} IMP・直近29日のみ有効）")
            lines.append("")

    # ── カテゴリ別集計 ─────────────────────────────
    lines.append("カテゴリ別 AlgoScore_api（Detail除外の参考値）:")
    lines.append(f"{'カテゴリ':<22} {'件数':>4} {'平均':>8} {'中央値':>8} {'平均IMP':>10}")

    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["カテゴリ"], []).append(r)
    for cat, group in sorted(by_cat.items(), key=lambda kv: -statistics.mean(_to_int(r["algo_score_api"]) for r in kv[1])):
        scores = [_to_int(r["algo_score_api"]) for r in group]
        imps   = [_to_int(r["impressions"])    for r in group]
        note   = " ※少数" if len(group) < 5 else ""
        lines.append(f"{cat:<22} {len(group):>4} {statistics.mean(scores):>8.1f} {statistics.median(scores):>8.1f} {statistics.mean(imps):>10.1f}{note}")

    posts = sorted(rows, key=lambda r: -_to_int(r["algo_score_api"]))
    lines.append("")
    lines.append("TOP 5:")
    for r in posts[:5]:
        lines.append(f"  [{_to_int(r['algo_score_api']):>4}] ({r['カテゴリ']}/{r['type']}) {r['投稿文'][:60]}...")
    lines.append("WORST 5:")
    for r in posts[-5:]:
        lines.append(f"  [{_to_int(r['algo_score_api']):>4}] ({r['カテゴリ']}/{r['type']}) {r['投稿文'][:60]}...")
    return "\n".join(lines)


# ──────────────────────────────────────────
# AI定性分析（プロンプト生成 / Gemini実行）
# ──────────────────────────────────────────

def build_analysis_prompt(rows: list[dict], user_metrics: dict = None) -> str:
    posts = sorted(rows, key=lambda r: -_to_int(r["algo_score_api"]))
    top = posts[:10]
    worst = [r for r in posts[-10:] if r not in top]

    def fmt(items):
        out = []
        for r in items:
            out.append(
                f"--- score={_to_int(r['algo_score_api'])} / カテゴリ={r['カテゴリ']} / type={r['type']} / "
                f"imp={_to_int(r['impressions'])} / reply={_to_int(r['replies'])} / "
                f"pclick={_to_int(r['profile_clicks'])} / bookmark={_to_int(r['bookmarks'])}\n"
                f"{r['投稿文'][:500]}"
            )
        return "\n\n".join(out)

    ff_section = ""
    if user_metrics:
        followers = user_metrics.get("followers", 0)
        following = user_metrics.get("following", 0)
        ff_ratio  = user_metrics.get("ff_ratio", 0.0)
        ff_section = f"\n【FF比率】フォロワー {followers:,} / フォロー {following:,} = {ff_ratio:.2f}"

    return f"""あなたはSNSグロースに精通したデータアナリストです。
以下は、メンエスセラピスト向けに発信するX（Twitter）アカウント @Keita_CPA
（ペルソナ: メンエスを愛する良客 × Big4出身CPA × 話すと楽しい人）の実測パフォーマンスデータです。
データに基づき、客観的に分析レポートを作成してください。

【スコアの定義】
AlgoScore_api = リプライ数×5 + プロフクリック×4 + ブックマーク×3 + リポスト×3 + いいね×1
（注: 詳細クリックは含まれない参考値。プロフクリックは直近29日の投稿のみ計測）{ff_section}

【統計サマリー】
{summarize(rows, user_metrics)}

【高エンゲージメント投稿（TOP10・全文）】
{fmt(top)}

【低エンゲージメント投稿（WORST10・全文）】
{fmt(worst)}

【分析してほしいこと（この構成でレポート出力）】
1. 高エンゲ投稿に共通するトピック・トーン・フックの型
   （分類軸の参考: 誤解フック型 / 深層心理代弁型 / ガチレス型 / Quote型 / 情景描写型）
2. 低エンゲ投稿に共通するパターン（避けるべき型）
3. カテゴリ別の所見（読者に求められているカテゴリはどれか）
4. 配信比率（weight）調整の示唆 — ただし提案のみ。適用判断は運用者が別ルールで行う
5. 読者に求められている新しい投稿テーマ候補を5つ（データ上の根拠を添えて）

【制約（厳守）】
- データにない結論を創作しないこと。すべての主張に上記データの根拠を添えること
- サンプル数が5件未満のカテゴリは「判断保留（データ不足）」と明記すること
- リプライ（type=reply）とメイン投稿は性質が異なるため分けて論じること"""


def run_gemini_analysis(prompt: str) -> str:
    """Gemini Pro で定性分析を実行する（約3〜5円）。"""
    from post_generator import client, MODEL_NAME, SAFETY_SETTINGS
    from google.genai import types
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS),
    )
    return response.text.strip() if response.text else "（分析APIエラー: 出力なし）"


# ──────────────────────────────────────────
# メイン
# ──────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="自分のXアカウントのパフォーマンス自己分析")
    parser.add_argument("--max", type=int, default=200, help="取得件数の上限（既定200）")
    parser.add_argument("--no-fetch", action="store_true", help="API取得せず既存CSVで集計のみ")
    parser.add_argument("--print-analysis-prompt", action="store_true", help="定額LLM用の分析プロンプトを出力")
    parser.add_argument("--ai", action="store_true", help="Gemini Proで定性分析（約3〜5円）")
    args = parser.parse_args()

    user_metrics = None
    if not args.no_fetch:
        try:
            tweets, non_public_map, user_metrics = fetch_my_tweets(args.max)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "Too Many" in msg:
                print(f"[ERROR] レート制限です。15分以上待って再実行してください: {e}")
            elif "403" in msg or "Forbidden" in msg:
                print(f"[ERROR] APIティアの権限不足の可能性があります（読み取り権限を確認）: {e}")
            else:
                print(f"[ERROR] 取得に失敗しました: {e}")
            sys.exit(1)

        if tweets:
            history_map = load_history_category_map()
            fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M")
            new_rows = [build_row(t, non_public_map, history_map, fetched_at) for t in tweets]
            added, updated = upsert_perf_csv(new_rows)
            print(f"[CSV] {PERF_CSV.name}: 追加 {added} 件 / 更新 {updated} 件")
        else:
            print("[WARN] 取得結果が0件でした")

    rows = load_perf_rows()
    if not rows:
        print("[INFO] my_performance.csv にデータがありません。まず取得を実行してください")
        return

    print()
    print("=" * 60)
    print(summarize(rows, user_metrics))
    print("=" * 60)

    if args.print_analysis_prompt:
        print()
        print("----- 以下を NotebookLM / Gemini ULTRA に貼り付けてください -----")
        print(build_analysis_prompt(rows, user_metrics))

    if args.ai:
        print()
        print("[AI] Gemini Pro で定性分析中...")
        report = run_gemini_analysis(build_analysis_prompt(rows, user_metrics))
        out = PERF_CSV.parent / f"self_analysis_{datetime.now():%Y-%m-%d}.md"
        out.write_text(f"# 自己アカウント分析レポート（{datetime.now():%Y-%m-%d}）\n\n{report}\n", encoding="utf-8")
        print(f"[AI] レポート保存: {out}")
        print()
        print(report)


if __name__ == "__main__":
    main()
