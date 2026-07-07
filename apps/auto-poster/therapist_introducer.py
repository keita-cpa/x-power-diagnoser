"""
therapist_introducer.py -- セラピスト紹介長文ポスト生成スクリプト（v5.5 会わない紹介・v2制度対応版）

指定したXアカウントのプロフィール・直近ポスト・リプライを取得し、
Gemini API で5段構成の紹介長文ポストを生成してターミナルに出力・保存する。
v5.4: 「気くばり手帖」シリーズの自動採番と8列台帳（introductions_log.csv）への記録を追加。
v5.5: 制度v2対応（対面・施術経験者の紹介禁止の注意表示・再紹介用 --reintroduce フラグ）。
制度設計は docs/introduction_system.md を参照。

使い方:
    venv/Scripts/python therapist_introducer.py --target 対象ID [--force | --reintroduce]
    --force       : 推敲・テスト用の再生成（台帳に記録しない）
    --reintroduce : 制度v2 §5 の再紹介条件（3か月以上・新素材・年1回）を満たす正式な再紹介
                    （履歴ブロックを外し、台帳に新しい通し番号で記録する）
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

SERIES_NAME  = "気くばり手帖"  # シリーズ名（2026-07-06確定。docs/introduction_system.md §3・変更時はドキュメントも同期）
LOG_FIELDS   = ["Date", "Target_ID", "シリーズ番号", "ポストURL",
                "本人反応", "資産採用", "紹介後の変化", "波及メモ"]

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
    with open(LOG_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) > 1 and row[1].lower() == username.lower():
                return True
    return False

def get_next_series_no() -> int:
    """台帳のデータ行数からシリーズの次の通し番号を返す"""
    if not os.path.exists(LOG_FILE):
        return 1
    with open(LOG_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        data_rows = [row for row in reader if row and row[0] != "Date"]
    return len(data_rows) + 1

def record_history(username: str, series_no: int):
    """8列台帳に記録する（ポストURL以降の計測列は投稿後に手動記入）"""
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(LOG_FIELDS)
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username,
                         str(series_no), "", "", "", "", ""])

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

    # 引数パース（--target / --force / --reintroduce オプションの検知）
    args = sys.argv[1:]
    force_mode = "--force" in args
    reintroduce_mode = "--reintroduce" in args

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
    print(f"therapist_introducer.py (v5.5 会わない紹介・v2制度対応版)")
    print(f"対象: @{username}")
    print("[RULE] 制度v2: 会った人・施術を受けた人は紹介禁止（introduction_system.md §2）。")
    print("       対象が該当しないことを確認してから進めてください。")
    print("[RULE] 紹介した人との関係（会ったか等）は、投稿後も一切公言しないこと。")
    if force_mode:
        print("[WARN] [--force] モードが有効です。履歴チェックをスキップします（台帳に記録しません）。")
    if reintroduce_mode:
        print("[WARN] [--reintroduce] 再紹介モードです。実行前に制度v2 §5 の3条件を確認してください:")
        print("       ①前回から3か月以上 ②前回と重複しない新素材 ③同一人物への再紹介は年1回まで")
        print("       サブ垢での再紹介は、投稿後に台帳の波及メモへ関連IDを記入すること。")
    print("=" * 60)

    # 再紹介のブロック（--force / --reintroduce で解除。意味の違いはdocstring参照）
    if not force_mode and not reintroduce_mode and check_history(username):
        print(f"\n[WARN] @{username} は過去に紹介済みです！")
        print("  再紹介には条件があります（introduction_system.md §5: 3か月以上・新素材・年1回）。")
        print("  [HINT] 条件を満たす正式な再紹介は --reintroduce、推敲・テスト目的の再生成は --force を付けてください。")
        print(f"  例: python therapist_introducer.py --target {username} --reintroduce")
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

    # シリーズ行の付与（生成本文には含めず、ここで機械的に採番して先頭に足す）
    series_no = get_next_series_no()
    final_post = f"{SERIES_NAME} その{series_no}\n\n{introduction_with_mention}"

    # 履歴記録とドラフト保存（--forceのときは履歴に二重登録しない）
    if not force_mode:
        record_history(username, series_no)
    draft_path = save_draft(username, final_post)

    char_count = len(final_post)
    print(f"\n  生成完了: {char_count} 文字（シリーズ行・@{username} のメンション含む）")
    print("\n" + "=" * 60)
    print(f"[生成された紹介長文ポスト（{SERIES_NAME} その{series_no}）]")
    print("=" * 60)
    print(final_post)
    print("=" * 60)
    print(f"\n[OK] ドラフト保存完了: {draft_path}")
    print(f"文字数: {char_count} 文字")
    print("[NEXT] 投稿後の制度運用（docs/introduction_system.md §3・§6・§7）:")
    print("  1. 内容を確認し、Xプレミアム長文ポストとして投稿する")
    print(f"  2. 目次ポスト「{SERIES_NAME}」に自己リプライで1行追記する")
    print(f"     形式: その{series_no} 「（紹介文中の言葉から6〜12字）」 @{username} さん")
    print("  3. data/logs/introductions_log.csv にポストURLを記入する")
    print("  4. 本人の反応への返信し返しを最優先で行い、反応した同業セラピスト個人を確認する")
    print("  5. 1週間後に台帳の「本人反応」列を記入する")


if __name__ == "__main__":
    main()