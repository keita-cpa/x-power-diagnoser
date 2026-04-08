"""
therapist_introducer.py -- セラピスト紹介長文ポスト生成スクリプト（v5.3 洗練・温度最適化版）

指定したXアカウントのプロフィール・直近ポスト・リプライを取得し、
Gemini API で5段構成の紹介長文ポストを生成してターミナルに出力・保存する。

使い方:
    venv/Scripts/python therapist_introducer.py --target 対象ID [--force]
"""

import os
import sys
import time
import re
import csv
from datetime import datetime

# Windows コンソールの文字化け対策
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tweepy
from google import genai
from google.genai import types

from config import GEMINI_API_KEY
from post_generator import MODEL_NAME, SAFETY_SETTINGS
from sniper_radar import get_bearer_token

# ──────────────────────────────────────────
# 定数
# ──────────────────────────────────────────

MAX_RETRIES  = 3
RETRY_WAIT   = 2   # 秒
MAX_POSTS    = 15  # ノイズ除去で減るため少し多めに取得
MAX_REPLIES  = 15  # ノイズ除去で減るため少し多めに取得

_BASE_DIR  = os.path.dirname(__file__)
LOG_FILE   = os.path.join(_BASE_DIR, "data", "logs", "introductions_log.csv")
DRAFTS_DIR = os.path.join(_BASE_DIR, "drafts")

SKILL_PATH = os.path.join(
    os.path.dirname(__file__),
    ".claude", "skills", "therapist-introduction", "SKILL.md",
)


# ──────────────────────────────────────────
# ヘルパー: 運用レイヤー
# ──────────────────────────────────────────

def check_history(username: str) -> bool:
    """過去の紹介履歴をチェックし二重紹介をブロック"""
    if not os.path.exists(LOG_FILE):
        return False
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) > 1 and row[1].lower() == username.lower():
                return True
    return False

def record_history(username: str):
    """実行履歴を保存"""
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Date", "Target_ID"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username])

def save_draft(username: str, text: str) -> str:
    """後から推敲できるようにDraftフォルダに保存"""
    if not os.path.exists(DRAFTS_DIR):
        os.makedirs(DRAFTS_DIR)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_id = username.replace("@", "")
    filename = os.path.join(DRAFTS_DIR, f"intro_{clean_id}_{timestamp}.md")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(text)
    return filename

def clean_tweet_text(text: str) -> str:
    """ノイズデータのクレンジング"""
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'@\w+', '', text)
    return text.strip()

def post_process_article(text: str) -> str:
    """Markdownの物理的除去（AIのハルシネーション対策）"""
    text = text.replace('**', '')
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    return text.strip()


# ──────────────────────────────────────────
# ヘルパー: SKILL.md 読み込み
# ──────────────────────────────────────────

def _read_skill() -> str:
    try:
        with open(SKILL_PATH, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise RuntimeError(f"SKILL.md が見つかりません: {SKILL_PATH}")


# ──────────────────────────────────────────
# Step 1: X データ取得
# ──────────────────────────────────────────

def fetch_user_profile(username: str, bearer_token: str) -> dict:
    client = tweepy.Client(bearer_token=bearer_token, wait_on_rate_limit=False)
    try:
        resp = client.get_user(
            username=username,
            user_fields=["description", "name", "username"],
        )
    except tweepy.errors.NotFound:
        raise RuntimeError(f"ユーザーが見つかりません: @{username}")
    except tweepy.errors.BadRequest as e:
        raise RuntimeError(f"不正なユーザー名: @{username} - {e}")
    except tweepy.errors.Unauthorized as e:
        raise RuntimeError(f"認証エラー（Bearer Tokenを確認してください）: {e}")
    except tweepy.errors.TweepyException as e:
        raise RuntimeError(f"ユーザー取得失敗: @{username} - {e}")

    if not resp.data:
        raise RuntimeError(f"ユーザーが見つかりません: @{username}")

    return {
        "id":          str(resp.data.id),
        "username":    resp.data.username,
        "name":        resp.data.name or "",
        "description": resp.data.description or "",
    }


def fetch_recent_posts(user_id: str, bearer_token: str, max_results: int = MAX_POSTS) -> list[str]:
    client = tweepy.Client(bearer_token=bearer_token, wait_on_rate_limit=False)
    try:
        resp = client.get_users_tweets(
            id=user_id,
            max_results=30,
            tweet_fields=["text", "referenced_tweets"],
            exclude=["retweets", "replies"],
        )
    except tweepy.errors.TweepyException as e:
        print(f"[WARN] 通常ポスト取得失敗（続行します）: {e}")
        return []

    if not resp.data:
        return []

    posts = []
    for tweet in resp.data:
        if tweet.referenced_tweets:
            ref_types = [ref.type for ref in tweet.referenced_tweets]
            if "replied_to" in ref_types:
                continue
        
        cleaned = clean_tweet_text(tweet.text)
        if len(cleaned) > 20:
            posts.append(cleaned)
            
        if len(posts) >= max_results:
            break

    return posts


def fetch_recent_replies(user_id: str, bearer_token: str, max_results: int = MAX_REPLIES) -> list[str]:
    client = tweepy.Client(bearer_token=bearer_token, wait_on_rate_limit=False)
    try:
        resp = client.get_users_tweets(
            id=user_id,
            max_results=30,
            tweet_fields=["text", "referenced_tweets"],
            exclude=["retweets"],
        )
    except tweepy.errors.TweepyException as e:
        print(f"[WARN] リプライ取得失敗（続行します）: {e}")
        return []

    if not resp.data:
        return []

    replies = []
    for tweet in resp.data:
        if tweet.referenced_tweets:
            ref_types = [ref.type for ref in tweet.referenced_tweets]
            if "replied_to" in ref_types:
                cleaned = clean_tweet_text(tweet.text)
                if len(cleaned) > 20:
                    replies.append(cleaned)
                    
        if len(replies) >= max_results:
            break

    return replies


# ──────────────────────────────────────────
# Step 2: Gemini API で紹介文生成
# ──────────────────────────────────────────

def get_current_season_context() -> str:
    """現在の月から季節情報を動的生成してGeminiに渡すコンテキストを返す。"""
    month = datetime.now().month
    if month in (3, 4, 5):
        return "春。桜（または新緑）の季節で、日中は20度前後だが朝晩はまだ少し肌寒い。"
    elif month in (6, 7, 8):
        return "夏。蒸し暑く日差しが強い。夜も気温が下がりにくく、冷たい飲み物が恋しくなる季節。"
    elif month in (9, 10, 11):
        return "秋。涼しく乾いた風が吹き、日が短くなり始める。紅葉や夕暮れが美しい季節。"
    else:
        return "冬。空気が乾燥し、吐く息が白くなる。暖かい場所や人のぬくもりが恋しくなる季節。"


def generate_introduction(profile: dict, posts: list[str], replies: list[str]) -> str:
    skill_text = _read_skill()
    season_context = get_current_season_context()

    posts_block   = "\n".join(f"{i+1}. {t}" for i, t in enumerate(posts))   or "（取得できませんでした）"
    replies_block = "\n".join(f"{i+1}. {t}" for i, t in enumerate(replies)) or "（取得できませんでした）"

    user_prompt = f"""以下の情報をもとに、SKILL.md の5段構成の型に厳密に従って、紹介長文ポストを生成してください。

【現在の季節情報】
{season_context}
※書き出しの情景は必ずこの季節感をベースにすること。対象者の過去ポストが冬の投稿であっても、現在の季節（上記）に合わせた情景で書き始めること。

【対象アカウント】@{profile['username']}（{profile['name']}）
【プロフィール文】
{profile['description'] or '（プロフィール未設定）'}

【直近の通常ポスト（ノイズ除去済）】
{posts_block}

【直近のリプライ（ノイズ除去済）】
{replies_block}

---
出力はポスト本文のみ。前置き・説明・見出しは不要です。
プレーンテキストのみ（Markdownの太字・見出し禁止）。
"""

    gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    for attempt in range(MAX_RETRIES):
        try:
            response = gemini_client.models.generate_content(
                model=MODEL_NAME,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=skill_text,
                    temperature=0.85, # 固定フレーズ問題を解消するため0.7から0.85へ戻す（対象者固有の表現生成を優先）
                    safety_settings=SAFETY_SETTINGS,
                ),
            )
            if response.text:
                return post_process_article(response.text)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"[WARN] Gemini API呼び出し失敗 ({attempt + 1}/{MAX_RETRIES}回目): {e}")
                time.sleep(RETRY_WAIT)
                continue
            raise RuntimeError(f"Gemini API失敗（{MAX_RETRIES}回）: {e}") from e

    raise RuntimeError("Gemini API: レスポンスが空でした（MAX_RETRIESを超過）")


# ──────────────────────────────────────────
# Step 3: メイン処理
# ──────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python therapist_introducer.py --target 対象ID [--force]")
        print("  例:   python therapist_introducer.py --target mensaestherapist")
        sys.exit(1)

    # 引数パース（--target / --forceオプションの検知）
    args = sys.argv[1:]
    force_mode = "--force" in args

    target_value = None
    if "--target" in args:
        idx = args.index("--target")
        if idx + 1 < len(args):
            target_value = args[idx + 1].lstrip("@")

    if not target_value:
        print("[ERROR] --target 対象ID が指定されていません。")
        print("  例:   python therapist_introducer.py --target mensaestherapist")
        sys.exit(1)

    username = target_value

    print("=" * 60)
    print(f"therapist_introducer.py (v5.3 洗練・温度最適化版)")
    print(f"対象: @{username}")
    if force_mode:
        print("⚠️ [--force] モードが有効です。履歴チェックをスキップします。")
    print("=" * 60)

    # 二重紹介のブロック
    if not force_mode and check_history(username):
        print(f"\n⚠️ 警告: @{username} は過去に紹介済みです！")
        print("  ブランド毀損（二重紹介）を防ぐため処理を停止します。")
        print("  💡 ※テスト・推敲目的で強制的に再作成する場合は、末尾に --force を付けて実行してください。")
        print(f"  例: python therapist_introducer.py --target {username} --force")
        sys.exit(1)

    print("\n[1/4] Bearer Token を生成中...")
    try:
        bearer_token = get_bearer_token()
        print("  Bearer Token: 取得成功")
    except Exception as e:
        print(f"  [FATAL] Bearer Token 取得失敗: {e}")
        sys.exit(1)

    print(f"\n[2/4] @{username} のプロフィールを取得中...")
    try:
        profile = fetch_user_profile(username, bearer_token)
        print(f"  名前: {profile['name']}")
        print(f"  プロフィール: {profile['description'][:60]}..." if len(profile['description']) > 60 else f"  プロフィール: {profile['description']}")
    except RuntimeError as e:
        print(f"  [FATAL] {e}")
        sys.exit(1)

    print(f"\n[3/4] 直近ポスト・リプライを取得中...")
    posts = fetch_recent_posts(profile["id"], bearer_token)
    print(f"  通常ポスト: {len(posts)} 件抽出（ノイズ除去済）")

    replies = fetch_recent_replies(profile["id"], bearer_token)
    print(f"  リプライ  : {len(replies)} 件抽出（ノイズ除去済）")

    if len(posts) == 0 and len(replies) == 0:
        print("\n[WARN] 投稿が0件です。非公開アカウントの可能性があります。")
        print("  プロフィール文のみで生成を試みますが、品質が低下します。")
        if not profile["description"]:
            print("  [FATAL] プロフィールも空です。紹介文を生成できません。")
            sys.exit(1)

    print(f"\n[4/4] Gemini API ({MODEL_NAME}) で紹介文を生成中...")
    try:
        introduction = generate_introduction(profile, posts, replies)
    except RuntimeError as e:
        print(f"  [FATAL] {e}")
        sys.exit(1)

    # スマートメンション
    if f"@{username}".lower() not in introduction.lower():
        introduction_with_mention = f"{introduction}\n\n@{username}"
    else:
        introduction_with_mention = introduction

    # 履歴記録とドラフト保存（--forceのときは履歴に二重登録しない）
    if not force_mode:
        record_history(username)
    draft_path = save_draft(username, introduction_with_mention)

    char_count = len(introduction_with_mention)
    print(f"\n  生成完了: {char_count} 文字（@{username} のメンション含む）")
    print("\n" + "=" * 60)
    print("[生成された紹介長文ポスト]")
    print("=" * 60)
    print(introduction_with_mention)
    print("=" * 60)
    print(f"\n✨ ドラフト保存完了: {draft_path}")
    print(f"文字数: {char_count} 文字")
    print("📝 ターミナル、または保存されたドラフト（.mdファイル）の内容を確認し、Xに投下してください！")


if __name__ == "__main__":
    main()