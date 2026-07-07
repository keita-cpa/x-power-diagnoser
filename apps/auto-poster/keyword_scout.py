"""
keyword_scout.py -- キーワード検索による新規セラピスト発掘

watch_keywords.txt のキーワードで X API を検索し、
税・お金・将来の不安を投稿しているセラピスト系アカウントを発掘する。
発掘候補は data/logs/keyword_scout_results.csv に出力。
target_accounts.txt への追加は手動（目視確認後）。

使い方:
    venv/Scripts/python keyword_scout.py                     # 全キーワードをバッチ検索
    venv/Scripts/python keyword_scout.py --keyword 確定申告  # 単一キーワードで検索
    venv/Scripts/python keyword_scout.py --max 5             # 1バッチあたり最大採用件数（デフォルト5）
"""

import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Windows コンソールの文字化け対策
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tweepy

from sniper_radar import get_bearer_token

# ──────────────────────────────────────────
# 定数
# ──────────────────────────────────────────

KEYWORDS_FILE = Path(__file__).parent / "data" / "config" / "watch_keywords.txt"
TARGETS_FILE  = Path(__file__).parent / "data" / "config" / "target_accounts.txt"
SCOUT_CSV     = str(Path(__file__).parent / "data" / "logs" / "scouted_targets.csv")
RESULTS_CSV   = str(Path(__file__).parent / "data" / "logs" / "keyword_scout_results.csv")

CSV_COLUMNS = ["検索日時", "マッチキーワード", "ユーザー名", "表示名", "フォロワー数", "bio", "対象ツイート"]

# 5キーワード/バッチ → 約8バッチ = 8 API呼び出し（レート制限 15req/15min の範囲内）
BATCH_SIZE      = 5
MAX_PER_BATCH   = 5   # 1バッチあたりの最大採用件数
SEARCH_INTERVAL = 1   # バッチ間ウェイト（秒）
MAX_RETRIES     = 3   # 503など一時エラー時のリトライ回数
RETRY_WAIT      = 3   # リトライ間隔（秒）
DATETIME_FMT    = "%Y-%m-%d %H:%M UTC"

# セラピスト系判定キーワード（バイオ + ツイート本文でマッチング・Gemini 不使用）
THERAPIST_SCREEN_KEYWORDS = [
    "セラピスト", "施術", "メンエス", "メンズエステ", "メンズエスト",
    "サロン", "アロマ", "ボディケア", "指名", "エステ", "癒し",
]

# ノイズ除去フィルタ（2026-07-02追加）: 目的は「個人セラピスト」の発掘。
# クリニック・業者・求人・店舗公式アカウントは表示名+bioのキーワードで除外する。
BLOCK_KEYWORDS = [
    "クリニック", "美容外科", "美容皮膚科", "公式", "求人", "採用", "募集",
    "整体院", "スクール", "養成", "講座", "運営", "広告", "キャバ", "ホスト",
    "コンカフェ", "グループ", "店舗", "オープン記念",
]
MIN_FOLLOWERS = 20     # bot・作りたてアカウントを除外
MAX_FOLLOWERS = 5000   # 5000超は個人でなくインフルエンサー/業者の可能性大（influencer_accounts.txt の領分）


# ──────────────────────────────────────────
# ファイル読み込み
# ──────────────────────────────────────────

def load_watch_keywords() -> list[str]:
    """watch_keywords.txt からキーワードリストを読み込む。"""
    if not KEYWORDS_FILE.exists():
        print(f"[ERROR] {KEYWORDS_FILE} が見つかりません")
        return []
    keywords = []
    for line in KEYWORDS_FILE.read_text(encoding="utf-8-sig").splitlines():
        kw = line.split("#", 1)[0].strip()
        if kw:
            keywords.append(kw)
    return keywords


def load_known_usernames() -> set[str]:
    """
    target_accounts.txt + 過去のスカウト / 発掘 CSV から既知アカウントセットを返す。
    発掘済みのアカウントを再提案しないための除外リスト。
    """
    known: set[str] = set()

    if TARGETS_FILE.exists():
        for line in TARGETS_FILE.read_text(encoding="utf-8-sig").splitlines():
            name = line.split("#", 1)[0].strip().lstrip("@").lower()
            if name:
                known.add(name)

    for csv_path in (SCOUT_CSV, RESULTS_CSV):
        if os.path.exists(csv_path):
            with open(csv_path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    name = (row.get("ユーザー名") or "").strip().lstrip("@").lower()
                    if name:
                        known.add(name)

    return known


# ──────────────────────────────────────────
# セラピスト系判定
# ──────────────────────────────────────────

def is_therapist_related(bio: str, tweet_text: str) -> bool:
    """バイオ or ツイート本文にセラピスト系キーワードがあれば True。Gemini 不使用（コスト0）。"""
    combined = bio + " " + tweet_text
    return any(kw in combined for kw in THERAPIST_SCREEN_KEYWORDS)


def find_match_keyword(tweet_text: str, bio: str, batch_kws: list[str]) -> str:
    """バッチ内でどの検索キーワードがツイートまたはバイオにマッチしたかを返す。"""
    for kw in batch_kws:
        if kw in tweet_text or kw in bio:
            return kw
    return batch_kws[0]


# ──────────────────────────────────────────
# X API 検索
# ──────────────────────────────────────────

def search_batch(
    batch_kws: list[str],
    client: tweepy.Client,
    max_adopt: int,
    known: set[str],
    seen_in_run: set[str],
) -> list[dict]:
    """
    batch_kws を OR 結合したクエリで X を検索する。
    セラピスト判定・既知除外を行い、採用候補リストを返す。
    """
    query = " OR ".join(batch_kws) + " lang:ja -is:retweet"
    # 多めに取得してセラピスト判定で絞る（X API min=10 / max=100）
    fetch_count = max(10, min(max_adopt * 6, 100))

    resp = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.search_recent_tweets(
                query=query,
                max_results=fetch_count,
                tweet_fields=["text", "author_id"],
                expansions=["author_id"],
                user_fields=["username", "name", "description", "public_metrics"],
            )
            break
        except tweepy.errors.Forbidden:
            print("  [FORBIDDEN] 検索APIへのアクセス権がありません")
            print("  X API Basic プラン（$100/月）以上が必要です。現在のプランを確認してください")
            return []
        except tweepy.errors.TweepyException as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  [RETRY {attempt + 1}/{MAX_RETRIES}] {e} → {RETRY_WAIT}秒後に再試行...")
                time.sleep(RETRY_WAIT)
            else:
                print(f"  [ERROR] 検索失敗（{MAX_RETRIES}回）: {e}")
                return []

    if resp is None or not resp.data:
        return []

    if not resp.data:
        return []

    includes = resp.includes or {}
    users: dict = {u.id: u for u in includes.get("users", [])}

    results = []
    for tweet in resp.data:
        if len(results) >= max_adopt:
            break

        user = users.get(tweet.author_id)
        if not user:
            continue

        uname_lower = user.username.lower()
        if uname_lower in known or uname_lower in seen_in_run:
            continue

        bio       = (user.description or "").strip()
        tweet_txt = tweet.text.strip()

        if not is_therapist_related(bio, tweet_txt):
            continue

        # ノイズ除去: クリニック・業者・求人アカウント（表示名+bio）
        name_and_bio = f"{user.name} {bio}"
        if any(kw in name_and_bio for kw in BLOCK_KEYWORDS):
            continue

        metrics   = getattr(user, "public_metrics", {}) or {}
        followers = metrics.get("followers_count", 0)

        # フォロワー数レンジ: 個人セラピスト帯のみ採用
        if not (MIN_FOLLOWERS <= followers <= MAX_FOLLOWERS):
            continue

        results.append({
            "match_keyword": find_match_keyword(tweet_txt, bio, batch_kws),
            "username":  user.username,
            "name":      user.name,
            "followers": followers,
            "bio":       bio,
            "tweet":     tweet_txt.replace("\n", " "),
        })

    return results


# ──────────────────────────────────────────
# CSV 追記
# ──────────────────────────────────────────

def append_to_results_csv(rows: list[dict], csv_path: str):
    """keyword_scout_results.csv に追記する。ファイル未存在時はヘッダー付きで新規作成。"""
    now = datetime.now(timezone.utc).strftime(DATETIME_FMT)
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({
                "検索日時":         now,
                "マッチキーワード": row["match_keyword"],
                "ユーザー名":       row["username"],
                "表示名":           row["name"],
                "フォロワー数":     row["followers"],
                "bio":              row["bio"],
                "対象ツイート":     row["tweet"],
            })


# ──────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────

def main():
    args           = sys.argv[1:]
    single_keyword = None
    max_per_batch  = MAX_PER_BATCH

    if "--keyword" in args:
        idx = args.index("--keyword")
        if idx + 1 < len(args):
            single_keyword = args[idx + 1]
        else:
            print("[ERROR] --keyword の後にキーワードを指定してください")
            print("  例: python keyword_scout.py --keyword 確定申告")
            sys.exit(1)

    if "--max" in args:
        idx = args.index("--max")
        if idx + 1 < len(args):
            try:
                max_per_batch = int(args[idx + 1])
            except ValueError:
                print("[ERROR] --max の後に整数を指定してください")
                sys.exit(1)

    all_keywords = [single_keyword] if single_keyword else load_watch_keywords()
    if not all_keywords:
        print("[ERROR] キーワードが0件です。data/config/watch_keywords.txt を確認してください")
        sys.exit(1)

    # バッチ化
    batches: list[list[str]] = (
        [[single_keyword]] if single_keyword
        else [all_keywords[i:i + BATCH_SIZE] for i in range(0, len(all_keywords), BATCH_SIZE)]
    )

    print("=" * 60)
    print("keyword_scout.py 起動（キーワード検索・新規セラピスト発掘）")
    print(f"実行日時: {datetime.now(timezone.utc).strftime(DATETIME_FMT)}")
    print(f"キーワード数: {len(all_keywords)}件 / バッチ数: {len(batches)}件 ({BATCH_SIZE}件/バッチ)")
    print(f"1バッチあたり最大採用: {max_per_batch}件")
    print("=" * 60)

    # Bearer Token
    print("\n[1/4] Bearer Token を生成中...")
    try:
        bearer_token = get_bearer_token()
        print("  Bearer Token: 取得成功")
    except Exception as e:
        print(f"  [FATAL] Bearer Token 取得失敗: {e}")
        sys.exit(1)

    client = tweepy.Client(bearer_token=bearer_token, wait_on_rate_limit=True)

    # 既知アカウント
    print("\n[2/4] 既知アカウントを読み込み中...")
    known = load_known_usernames()
    print(f"  除外リスト: {len(known)}件（target_accounts + 過去スカウト結果）")

    # バッチ検索ループ
    print("\n[3/4] キーワードバッチ検索中...")
    total_new    = 0
    seen_in_run: set[str] = set()

    for i, batch in enumerate(batches):
        label = " / ".join(batch)
        print(f"\n  [{i+1}/{len(batches)}] {label}")

        candidates = search_batch(batch, client, max_per_batch, known, seen_in_run)

        if candidates:
            for c in candidates:
                seen_in_run.add(c["username"].lower())
            append_to_results_csv(candidates, RESULTS_CSV)
            total_new += len(candidates)
            for c in candidates:
                print(f"    [NEW] @{c['username']} ({c['followers']}F) "
                      f"KW:{c['match_keyword']} | {c['tweet'][:40]}...")
        else:
            print(f"    新規候補なし")

        if i < len(batches) - 1:
            time.sleep(SEARCH_INTERVAL)

    # サマリー
    print("\n" + "=" * 60)
    print("[実行サマリー]")
    print(f"  検索バッチ数        : {len(batches)}件（キーワード計 {len(all_keywords)}件）")
    print(f"  新規候補（既知除外）: {total_new}件")
    print(f"  出力先              : {RESULTS_CSV}")
    print("=" * 60)

    if total_new:
        print("\n[次のアクション]")
        print(f"  1. {RESULTS_CSV} を開いて目視確認する")
        print("  2. 有望なアカウントを data/config/target_accounts.txt に追記する")
        print("  3. /project:sniper-run でリプライ起案を実行する")


if __name__ == "__main__":
    main()
