"""
sniper_radar.py -- VIPアカウント監視・リプライ起案システム

指定したVIPアカウントの最新ツイートをBearerTokenで取得し、
gemini-2.5-flash-lite でスクリーニング -> gemini-3-flash-preview でリプライ起案 -> CSV出力する。
"""

import base64
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows コンソールの文字化け対策
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
import tweepy
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, X_API_KEY, X_API_SECRET
from post_generator import SAFETY_SETTINGS
from prompts import SYSTEM_PROMPT, _TONE_REPLY

# ──────────────────────────────────────────
# 定数
# ──────────────────────────────────────────

# ※ セラピスト/業界系アカウントを優先（プロフィールクリック率1.4〜2.4% vs 一般0.1%）
# ※ ペルソナv2選定基準: 哲学・人間味・仕事への姿勢を発信しているセラピストを優先する。
#    リプライは実測AlgoScoreがメイン投稿の8.3倍の主戦場であり、
#    「具体的な事実への言及で自己重要感を満たす」相手（発信に固有のディテールがある人）ほど効果が高い。
# 監視対象は data/config/target_accounts.txt（1行1アカウント・#コメント可）で管理する。
# ファイルが存在しない場合のみ、以下のフォールバックリストを使う。
DEFAULT_TARGET_ACCOUNTS = [
    # セラピスト系（高コンバージョン・優先）
    "sub20250209", "jibunmigakuzo", "uDonshi9532", "kkk_cun",
    # 既存VIPアカウント
    "nekokoroconsul1", "mensaesthet", "sugawara11", "765naruko", "96yurisub", "doki_doki_ryuga", "rin_ring_ange", "nyakomiya",
]
TARGETS_FILE = Path(__file__).parent / "data" / "config" / "target_accounts.txt"
SCOUT_CSV   = str(Path(__file__).parent / "data" / "logs" / "scouted_targets.csv")
CSV_COLUMNS = ["取得日時", "対象URL", "ユーザー名", "対象ツイート", "AIリプライ案"]

SCREEN_MODEL = "gemini-2.5-flash-lite"
REPLY_MODEL  = "gemini-3-flash-preview"

MAX_RESULTS = 10  # 1アカウントあたりの取得ツイート数

# ──────────────────────────────────────────
# Step 0: 監視対象の読み込み
# ──────────────────────────────────────────

def load_target_accounts() -> list[str]:
    """
    data/config/target_accounts.txt から監視対象を読み込む。
    形式: 1行1アカウント（@は付けても付けなくてもよい）。# 以降はコメント。
    ファイルが無い・有効な行が1つもない場合は DEFAULT_TARGET_ACCOUNTS にフォールバック。
    """
    if not TARGETS_FILE.exists():
        return list(DEFAULT_TARGET_ACCOUNTS)
    accounts = []
    for line in TARGETS_FILE.read_text(encoding="utf-8-sig").splitlines():
        name = line.split("#", 1)[0].strip().lstrip("@")
        if name:
            accounts.append(name)
    if not accounts:
        print(f"[WARN] {TARGETS_FILE} に有効なアカウントがありません。フォールバックを使用します")
        return list(DEFAULT_TARGET_ACCOUNTS)
    return accounts


# ──────────────────────────────────────────
# Step 1: Bearer Token 動的生成
# ──────────────────────────────────────────

def get_bearer_token() -> str:
    """X_API_KEY と X_API_SECRET から Bearer Token を動的生成する。"""
    credentials = f"{X_API_KEY}:{X_API_SECRET}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    resp = requests.post(
        "https://api.twitter.com/oauth2/token",
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        data="grant_type=client_credentials",
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"Bearer Token 取得失敗: {resp.text}")
    return token


# ──────────────────────────────────────────
# Step 2: Twitter データ取得
# ──────────────────────────────────────────

def fetch_recent_tweets(username: str, bearer_token: str) -> list[dict]:
    """
    指定ユーザーの最新ツイートを取得する（RT・他人へのリプライを除外）。
    返り値: [{"id": str, "text": str, "created_at": str, "url": str}, ...]
    """
    client = tweepy.Client(bearer_token=bearer_token, wait_on_rate_limit=False)

    # ユーザーID取得
    try:
        user_resp = client.get_user(username=username)
    except tweepy.errors.BadRequest as e:
        print(f"[WARN] ユーザー取得失敗（不正なユーザー名?）: @{username} - {e}")
        return []
    except tweepy.errors.TweepyException as e:
        print(f"[WARN] ユーザー取得失敗: @{username} - {e}")
        return []

    if not user_resp.data:
        print(f"[WARN] ユーザーが見つかりません: @{username} スキップします")
        return []

    user_id = user_resp.data.id

    # ツイート取得
    try:
        tweets_resp = client.get_users_tweets(
            id=user_id,
            max_results=MAX_RESULTS,
            tweet_fields=["text", "created_at", "referenced_tweets"],
            exclude=["retweets", "replies"],
        )
    except tweepy.errors.TweepyException as e:
        print(f"[WARN] ツイート取得失敗: @{username} - {e}")
        return []

    if not tweets_resp.data:
        print(f"[INFO] @{username}: 取得できるツイートがありません")
        return []

    results = []
    for tweet in tweets_resp.data:
        # 念のため他人へのリプライ（referenced_tweets に replied_to が含まれる）を弾く
        if tweet.referenced_tweets:
            types_list = [ref.type for ref in tweet.referenced_tweets]
            if "replied_to" in types_list:
                continue

        results.append({
            "id":         str(tweet.id),
            "text":       tweet.text,
            "created_at": str(tweet.created_at),
            "url":        f"https://twitter.com/{username}/status/{tweet.id}",
        })

    return results


# ──────────────────────────────────────────
# Step 3: 1次スクリーニング
# ──────────────────────────────────────────

def screen_tweet(tweet_text: str, gemini_client) -> tuple[bool, str]:
    """
    gemini-2.5-flash-lite でツイートをスクリーニングする。
    返り値: (is_pass: bool, reason: str)
    """
    prompt = f"""以下のツイートを1つの観点で審査してください。

【審査観点①（必須）】炎上リスク・攻撃的な内容・他者への誹謗中傷・極端なゴシップ要素がないか？
【審査観点②（優先加点）】以下のいずれかに該当する場合は優先的に [PASS] を出力すること:
  - メンズエステ・セラピスト・風俗業界・性的労働に関するツイート
  - 労働環境・職場の悩み・お金・節税・税務に関するツイート
  - 体験談・感情吐露・悩み相談・業界の理不尽さへの共感を求める内容

この観点①に該当せず、観点②に該当するツイートは最優先で [PASS] を出力してください。
観点①に該当しなければ、日常のつぶやきや趣味の話であっても [PASS] を出力してください。
観点①に該当する場合のみ [REJECT: 理由を30字以内で] を出力してください。

出力は必ず [PASS] または [REJECT: 〇〇] の形式のみで返してください。説明文は不要です。

---
ツイート:
{tweet_text}
"""
    try:
        response = gemini_client.models.generate_content(
            model=SCREEN_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                safety_settings=SAFETY_SETTINGS,
            ),
        )
        raw = (response.text or "").strip()
    except Exception as e:
        print(f"  [SCREEN ERROR] Gemini呼び出し失敗: {e}")
        return False, f"APIエラー: {e}"

    if raw.startswith("[PASS]"):
        return True, "PASS"
    elif raw.startswith("[REJECT"):
        reason = raw.replace("[REJECT:", "").replace("]", "").strip()
        return False, reason or "REJECT"
    else:
        # パース失敗 -> 安全側に倒してREJECT
        print(f"  [SCREEN WARN] パース失敗、REJECTとして扱います: {raw[:60]}")
        return False, "パースエラー(安全側REJECT)"


# ──────────────────────────────────────────
# Step 4: リプライ起案
# ──────────────────────────────────────────

def draft_reply(tweet_text: str, gemini_client) -> str:
    """
    gemini-3-flash-preview でリプライ案を起案する。
    system_instruction に SYSTEM_PROMPT + _TONE_REPLY を適用。
    ツイートの話題に応じて2モードを使い分ける（判定はプロンプト内でGeminiが行う）:
      A) お金・法律・労務の話題 → 法的ファクトによる客観的擁護
      B) 感情・日常・体験談     → 受けの一拍＋具体的事実の承認（法律ファクトは出さない）
    返り値: リプライ案テキスト（140字以内）
    """
    prompt = f"""以下のツイートに対して、@Keita_CPA（Big4出身の公認会計士・税理士）として
リプライ案を1つ起案してください。

【最初にやること: モード判定】
対象ツイートの話題を読み、以下のどちらか1つを内部で選ぶこと（判定結果は出力しない）。

■ モードA【ファクト擁護型】— お金・税務・契約・労務・店との取り分・罰則など、
  法律や数字が絡む話題のとき:
  相手の工夫・愚痴・苦労を、法律や税務の客観的なファクト（条文・判例・数字）を使って
  「客観的に擁護・正当化」する。
  直接褒めることは禁止。「法律から見ても、あなたのやり方は正しい」という
  客観的事実でそっと背中を押すこと。
  ファクトを提示する際は必ず「中学生でも直感的にわかる」平易な言葉に翻訳を添えること。

■ モードB【共感・承認型】— 感情の吐露・日常の出来事・体験談・季節の話など、
  法律や数字が絡まない話題のとき:
  法律・税務のファクトを無理にこじつけることを【絶対禁止】する。
  まず相手の言葉を「そうなんですね」「それは〜ですよね」と一拍受け止め（全肯定リズム）、
  そのうえでツイートに書かれた【具体的な事実・言葉・行動】をひとつ取り上げて、
  それが持つ意味や気遣いを言語化する（ありきたりな褒め言葉での置き換えは禁止）。
  解決策の提示・アドバイスは不要。隣に座る一言でよい。

【共通の目的】
このリプライを読んだ第三者が「このセラピスト、ちゃんとしてるんだな」と
自然に感じる空間を作ること。

---
対象ツイート:
{tweet_text}
"""
    try:
        response = gemini_client.models.generate_content(
            model=REPLY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT + "\n\n" + _TONE_REPLY,
                safety_settings=SAFETY_SETTINGS,
            ),
        )
        return (response.text or "").strip()
    except Exception as e:
        print(f"  [REPLY ERROR] Gemini呼び出し失敗: {e}")
        return f"[起案失敗: {e}]"


# ──────────────────────────────────────────
# Step 5: CSV追記
# ──────────────────────────────────────────

def load_existing_urls(csv_path: str) -> set[str]:
    """既存CSVに存在するURLのセットを返す。"""
    if not os.path.exists(csv_path):
        return set()
    urls = set()
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get("対象URL", "").strip()
            if url:
                urls.add(url)
    return urls


def append_to_scout_csv(row: dict, csv_path: str):
    """CSVに1行追記する。ファイル未存在時はヘッダー付きで新規作成。"""
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ──────────────────────────────────────────
# Step 6: メイン処理
# ──────────────────────────────────────────

def main():
    # 引数パース: --target ユーザー名 が指定されたらそのアカウントだけを即時スキャン
    args = sys.argv[1:]
    target_accounts = None
    if "--target" in args:
        idx = args.index("--target")
        if idx + 1 < len(args):
            target_accounts = [args[idx + 1].lstrip("@")]
        else:
            print("[ERROR] --target の後にユーザー名を指定してください。")
            print("  例: python sniper_radar.py --target nyakomiya")
            sys.exit(1)
    if target_accounts is None:
        target_accounts = load_target_accounts()

    print("=" * 60)
    print("sniper_radar.py 起動")
    print(f"実行日時: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    source = "--target指定" if "--target" in args else (
        f"{TARGETS_FILE.name}" if TARGETS_FILE.exists() else "フォールバック(コード内蔵)")
    print(f"監視対象（{source}）: {target_accounts}")
    print("=" * 60)

    # Gemini クライアント初期化
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    # Bearer Token 取得
    print("\n[1/4] Bearer Token を生成中...")
    try:
        bearer_token = get_bearer_token()
        print("  Bearer Token: 取得成功")
    except Exception as e:
        print(f"  [FATAL] Bearer Token 取得失敗: {e}")
        sys.exit(1)

    # 既存URLを読み込んで重複防止
    existing_urls = load_existing_urls(SCOUT_CSV)
    print(f"\n[2/4] 既存CSV確認: {len(existing_urls)} 件のURLを読み込み済み")

    # 集計用
    total_fetched  = 0
    total_passed   = 0
    total_saved    = 0
    total_skipped  = 0

    print("\n[3/4] ツイート取得・スクリーニング・起案を開始...")

    for username in target_accounts:
        print(f"\n--- @{username} ---")

        tweets = fetch_recent_tweets(username, bearer_token)
        print(f"  取得: {len(tweets)} 件（RT・リプライ除外済み）")
        total_fetched += len(tweets)

        for tweet in tweets:
            url = tweet["url"]

            # 重複チェック
            if url in existing_urls:
                print(f"  [SKIP] 既存URL: {url}")
                total_skipped += 1
                continue

            # スクリーニング
            is_pass, reason = screen_tweet(tweet["text"], gemini_client)
            if not is_pass:
                print(f"  [REJECT] {reason[:40]} | {url}")
                continue

            total_passed += 1
            print(f"  [PASS]  スクリーニング通過: {url}")

            # リプライ起案
            reply_draft = draft_reply(tweet["text"], gemini_client)
            char_count  = len(reply_draft)
            print(f"  [DRAFT] {char_count}字: {reply_draft[:60]}...")

            # CSV追記
            row = {
                "取得日時":     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "対象URL":      url,
                "ユーザー名":   username,
                "対象ツイート": tweet["text"].replace("\n", " "),
                "AIリプライ案": reply_draft,
            }
            append_to_scout_csv(row, SCOUT_CSV)
            existing_urls.add(url)
            total_saved += 1
            print(f"  [SAVED] {SCOUT_CSV} に追記しました")

    # サマリー
    print("\n" + "=" * 60)
    print("[実行サマリー]")
    print(f"  監視アカウント数  : {len(target_accounts)}")
    print(f"  ツイート取得数    : {total_fetched}")
    print(f"  重複スキップ数    : {total_skipped}")
    print(f"  スクリーニング通過: {total_passed}")
    print(f"  CSV書き込み数     : {total_saved}")
    print(f"  出力先            : {SCOUT_CSV}")
    print("=" * 60)


if __name__ == "__main__":
    main()
