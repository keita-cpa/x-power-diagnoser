"""
sniper_radar.py -- VIPアカウント監視・リプライ起案システム

指定したVIPアカウントの最新ツイートをBearerTokenで取得し、
gemini-2.5-flash-lite でスクリーニング -> gemini-3-flash-preview でリプライ起案 -> CSV出力する。
"""

import base64
import csv
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows コンソールの文字化け対策
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
import tweepy
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
from post_generator import SAFETY_SETTINGS
from prompts import SYSTEM_PROMPT, _TONE_REPLY, _TONE_INFLUENCER_REPLY

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
TARGETS_FILE            = Path(__file__).parent / "data" / "config" / "target_accounts.txt"
INFLUENCER_TARGETS_FILE = Path(__file__).parent / "data" / "config" / "influencer_accounts.txt"
SCOUT_CSV   = str(Path(__file__).parent / "data" / "logs" / "scouted_targets.csv")
CSV_COLUMNS = ["取得日時", "対象URL", "ユーザー名", "対象ツイート", "AIリプライ案"]

SCREEN_MODEL = "gemini-2.5-flash-lite"
REPLY_MODEL  = "gemini-3-flash-preview"

MAX_RESULTS = 10  # 1アカウントあたりの取得ツイート数（通常モード）

# ── 炎上・スパム判定回避の制御（通常モード）──
MIN_RECONTACT_HOURS    = 72    # 同一アカウントへの再接触の最短間隔（3日）。「監視されている感」を消す
MAX_DRAFTS_PER_ACCOUNT = 1     # 1ラン・1アカウントあたりの新規起案上限（接触を多様な相手に分散）
MAX_NEW_DRAFTS_PER_RUN = 6     # 1ランの新規起案上限（引用リポストと合わせ1日5〜10件が目安）
REPLY_TEMP_MIN = 0.85          # 温度ランダム化の下限（AI定型文の固定化を防ぐ）
REPLY_TEMP_MAX = 1.05          # 温度ランダム化の上限

# ── インフルエンサーモード専用定数 ──
LIST_ID                        = "2006127804023546152"  # XリストID（influencerモード用・タイムライン一括取得）
INFLUENCER_LIST_MAX_RESULTS    = 20  # リストから取得する最大ツイート数（上限100）
INFLUENCER_MAX_DRAFTS_PER_RUN  = 3   # 1ランの起案上限（吟味が必要なため少なめ）

# 日時フォーマット（CSV 取得日時列）
DATETIME_FMT = "%Y-%m-%d %H:%M UTC"

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


def load_influencer_accounts() -> list[str]:
    """
    data/config/influencer_accounts.txt からインフルエンサーアカウントを読み込む。
    形式: 1行1アカウント（@は付けても付けなくてもよい）。# 以降はコメント。
    """
    if not INFLUENCER_TARGETS_FILE.exists():
        print(f"[WARN] {INFLUENCER_TARGETS_FILE} が見つかりません。")
        print("  apps/auto-poster/data/config/influencer_accounts.txt を作成してください。")
        return []
    accounts = []
    for line in INFLUENCER_TARGETS_FILE.read_text(encoding="utf-8-sig").splitlines():
        name = line.split("#", 1)[0].strip().lstrip("@")
        if name:
            accounts.append(name)
    return accounts


def _load_image_part(media_urls: list):
    """media_urls の先頭1枚をダウンロードして types.Part を返す。失敗時は None。"""
    if not media_urls:
        return None
    try:
        r = requests.get(media_urls[0], timeout=8)
        r.raise_for_status()
        mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        return types.Part.from_bytes(data=r.content, mime_type=mime)
    except Exception as e:
        print(f"  [WARN] 画像読み込み失敗（テキストのみで起案）: {e}")
        return None


def draft_influencer_reply(tweet_text: str, gemini_client, media_urls: list = None) -> str:
    """
    インフルエンサー（大型アカウント）向けのリプライ案を起案する。
    同業リスペクト型: 全肯定 + 現場共鳴1文 でプロフィールへの自然な誘導を狙う。
    画像が添付されている場合はマルチモーダルで Gemini に渡す。
    """
    image_notice = "\n※ このツイートには画像が添付されています。画像の内容も踏まえてリプライを起案してください。" if media_urls else ""
    prompt = f"""以下のツイートに対して、@Keita_CPA（業界を愛する一人の良客で、たまたまBig4出身の
公認会計士・税理士）として、リプライ案を1つ起案してください。

【大前提（最優先・例外なし）】
相手は大きな影響力を持つアカウントです。
補足・訂正・求められていないアドバイスは1文たりとも書かないこと。
「全肯定 + 現場の共鳴1文」の構造のみ。

【書き方（同業リスペクト型）】
Step1 全肯定: 相手の投稿の「具体的な言葉・主張・場面」をひとつ取り上げ、
  まず丸ごと受け止める。「〜ですよね」「〜な気がする」と柔らかい語尾で受ける。
  嘘くさい絶賛（「完璧」「最高」「すごい」）は禁止。

Step2 現場共鳴を1文添える: 自分のリアルな現場経験・感覚から
  「ぼくも同じことを現場で感じていて」「これ、実際に見てきたので刺さりました」
  のような体温ある1文を自然に添える。
  手柄話・肩書き誇示・上から目線は禁止（醸し出すだけでよい）。

【絶対禁止】
・補足・訂正・未要求アドバイス
・「詳しくはプロフへ」「DMください」の直接的な自己宣伝
・毎回同じ書き出し・語尾（対象ツイート固有のディテールから書き起こすこと）

---
対象ツイート:
{tweet_text}{image_notice}
"""
    image_part = _load_image_part(media_urls)
    contents   = [image_part, types.Part.from_text(text=prompt)] if image_part else prompt
    try:
        response = gemini_client.models.generate_content(
            model=REPLY_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT + "\n\n" + _TONE_INFLUENCER_REPLY,
                safety_settings=SAFETY_SETTINGS,
                temperature=random.uniform(REPLY_TEMP_MIN, REPLY_TEMP_MAX),
            ),
        )
        return (response.text or "").strip()
    except Exception as e:
        print(f"  [INFLUENCER REPLY ERROR] Gemini呼び出し失敗: {e}")
        return f"[起案失敗: {e}]"


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

def fetch_recent_tweets(username: str, bearer_token: str, max_results: int = MAX_RESULTS) -> list[dict]:
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
            max_results=max(5, min(max_results, 100)),
            tweet_fields=["text", "created_at", "referenced_tweets", "attachments"],
            expansions=["attachments.media_keys"],
            media_fields=["url", "preview_image_url", "type"],
            exclude=["retweets", "replies"],
        )
    except tweepy.errors.TweepyException as e:
        print(f"[WARN] ツイート取得失敗: @{username} - {e}")
        return []

    if not tweets_resp.data:
        print(f"[INFO] @{username}: 取得できるツイートがありません")
        return []

    # media_key → 画像URL のマッピング
    t_includes = tweets_resp.includes or {}
    media_map = {}
    for m in t_includes.get("media", []):
        url = getattr(m, "url", None) or getattr(m, "preview_image_url", None)
        if url:
            media_map[m.media_key] = url

    results = []
    for tweet in tweets_resp.data:
        # 念のため他人へのリプライ（referenced_tweets に replied_to が含まれる）を弾く
        if tweet.referenced_tweets:
            types_list = [ref.type for ref in tweet.referenced_tweets]
            if "replied_to" in types_list:
                continue

        media_urls = []
        if tweet.attachments and tweet.attachments.get("media_keys"):
            media_urls = [media_map[k] for k in tweet.attachments["media_keys"] if k in media_map]

        results.append({
            "id":         str(tweet.id),
            "text":       tweet.text,
            "created_at": str(tweet.created_at),
            "url":        f"https://twitter.com/{username}/status/{tweet.id}",
            "media_urls": media_urls,
        })

    return results


def fetch_list_tweets(list_id: str, bearer_token: str, max_results: int = INFLUENCER_LIST_MAX_RESULTS) -> list[dict]:
    """
    XリストのタイムラインからN件の最新ツイートを取得する（リストメンバー全員の合算・時系列降順）。
    per-account N回のAPI呼び出しを1回に集約し、author_id → username を expansions で解決する。
    プライベートリストにアクセス可能なよう OAuth 1.0a ユーザー認証を使用する。
    返り値: [{"id": str, "text": str, "created_at": str, "url": str, "username": str}, ...]
    """
    client = tweepy.Client(
        bearer_token=bearer_token,
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=False,
    )
    try:
        resp = client.get_list_tweets(
            id=list_id,
            max_results=max(1, min(max_results, 100)),
            tweet_fields=["text", "created_at", "author_id", "attachments"],
            expansions=["author_id", "attachments.media_keys"],
            user_fields=["username"],
            media_fields=["url", "preview_image_url", "type"],
            user_auth=True,  # OAuth 1.0a でプライベートリストにアクセス
        )
    except tweepy.errors.TweepyException as e:
        print(f"[ERROR] リストタイムライン取得失敗: {e}")
        return []

    if not resp.data:
        print("[INFO] リストタイムライン: ツイートが見つかりませんでした")
        return []

    # includes から author_id → username / media_key → URL をマッピング
    includes = resp.includes or {}
    users     = {u.id: u.username for u in includes.get("users", [])}
    media_map = {}
    for m in includes.get("media", []):
        url = getattr(m, "url", None) or getattr(m, "preview_image_url", None)
        if url:
            media_map[m.media_key] = url

    results = []
    for tweet in resp.data:
        username = users.get(tweet.author_id, str(tweet.author_id))

        media_urls = []
        if tweet.attachments and tweet.attachments.get("media_keys"):
            media_urls = [media_map[k] for k in tweet.attachments["media_keys"] if k in media_map]

        results.append({
            "id":         str(tweet.id),
            "text":       tweet.text,
            "created_at": str(tweet.created_at),
            "url":        f"https://twitter.com/{username}/status/{tweet.id}",
            "username":   username,
            "media_urls": media_urls,
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
    prompt = f"""以下のツイートを審査してください。

【審査観点①（必須・REJECT基準）】炎上リスク・攻撃的な内容・他者への誹謗中傷・極端なゴシップ要素がないか？
【審査観点②（優先PASS）】以下のいずれかに該当する場合は最優先で [PASS] を出力すること:
  - メンズエステ・セラピスト・風俗業界・性的労働に関するツイート
  - 労働環境・職場の悩み・お金・節税・税務に関するツイート
  - 体験談・感情吐露・悩み相談・業界の理不尽さへの共感を求める内容
  - 「固有の体験・感情・ジレンマ」が書かれており、共感リプライの余地があるツイート
    （例: 「今日こんなことがあって…」「正直しんどい」「こう感じてしまう自分がいる」）

審査ルール:
  観点①に非該当かつ観点②に該当 → 最優先で [PASS]
  観点①に非該当で観点②にも非該当（日常・趣味のつぶやき）→ [PASS]
  観点①に該当する場合のみ → [REJECT: 理由を30字以内で]

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

def draft_reply(tweet_text: str, gemini_client, media_urls: list = None) -> str:
    """
    gemini-3-flash-preview でリプライ案を起案する。
    system_instruction に SYSTEM_PROMPT + _TONE_REPLY を適用。

    デフォルトは「共感・承認のみ」。専門知識（法・税・お金）は相手が明確に質問・相談
    している時だけ「お守り」の温度で添える（未要求のアドバイス・指摘・説教は完全禁止）。
    温度はラン毎にランダム化し、AI定型文の固定化を防ぐ。
    画像が添付されている場合はマルチモーダルで Gemini に渡す。
    返り値: リプライ案テキスト（140字以内）
    """
    image_notice = "\n※ このツイートには画像が添付されています。画像の内容も踏まえてリプライを起案してください。" if media_urls else ""
    prompt = f"""以下のツイートに対して、@Keita_CPA（業界を愛する一人の良客で、たまたまBig4出身の
公認会計士・税理士）として、リプライ案を1つ起案してください。

【大前提（最優先・例外なし）】
このリプライは「解決の場」ではなく「共感と承認の場」です。
指摘・説教・「〜すべき」・求められていないアドバイスは1文たりとも書かないこと。

【書き方の3原則（書籍エッセンス・最重要）】
1. 言い切らない（中距離の温度を保つ）
   断定の「〜だ」「〜だよ！」は距離を詰めすぎる。
   「〜ですよね」「〜なのかもな」「〜な気がする」と語尾をわずかに濁し、
   共感を得やすく・外れても大きくすべらない退路を残すこと。
2. 強い感想は行動に落とす
   「すごい」「素敵」で終えるのではなく、「また読みたくなった」「これ、手元に置いておきたい」
   のように自分ならどうしたいかまで言うと記憶に残る。
   ただしありきたりな褒め言葉の代わりに使う場合のみ。媚びへの転落は禁止。
3. 対象ツイート固有のディテールから書き起こす
   毎回同じ書き出し・語尾にしない。元ツイートの具体的な一言・シーン・感情を
   ひとつ取り上げ、そこから書き始めること。
   「うんうん、そうだよね」と頷いているテンポで受けること（全肯定リズム）。

【基本の振る舞い（デフォルト＝これで書く）】
まず相手の言葉を一拍受け止め、
ツイートに書かれた【具体的な事実・言葉・行動・気遣い】をひとつ取り上げて、
それが持つ意味をそっと言語化すること（ありきたりな褒め言葉での置き換えは禁止）。
隣に座る一言でよい。解決策やアドバイスは不要。

【例外: 専門の「お守り」を添えてよい唯一の条件】
対象ツイートが、お金・税務・契約・労務などについて
【明確に質問・相談・助けを求めている】場合に限り、
法・税の客観的な事実を「指摘」ではなく「知っておくと安心なお守り」の温度で、
中学生でも直感的にわかる平易な言葉に翻訳して、そっと一言添えてよい。
少しでも「未要求のアドバイス」に傾きそうなら、専門知識は出さず共感だけで終えること。
（判定は内部で行い、判定結果は出力しない）

【目的】
このリプライを読んだ第三者が「このセラピストさん、ちゃんとしてるんだな」と
自然に感じる空間を作ること。

---
対象ツイート:
{tweet_text}{image_notice}
"""
    image_part = _load_image_part(media_urls)
    contents   = [image_part, types.Part.from_text(text=prompt)] if image_part else prompt
    try:
        response = gemini_client.models.generate_content(
            model=REPLY_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT + "\n\n" + _TONE_REPLY,
                safety_settings=SAFETY_SETTINGS,
                temperature=random.uniform(REPLY_TEMP_MIN, REPLY_TEMP_MAX),
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


def load_account_last_contact(csv_path: str) -> dict:
    """
    既存CSVから各アカウントの「最終接触日時（最新の取得日時）」を返す。
    返り値: {ユーザー名(小文字): datetime(aware UTC)}
    パース不能な行は無視する（安全側）。
    """
    last_contact: dict = {}
    if not os.path.exists(csv_path):
        return last_contact
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("ユーザー名") or "").strip().lstrip("@").lower()
            raw  = (row.get("取得日時") or "").strip()
            if not name or not raw:
                continue
            try:
                dt = datetime.strptime(raw, DATETIME_FMT).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if name not in last_contact or dt > last_contact[name]:
                last_contact[name] = dt
    return last_contact


def is_within_recontact_window(username: str, last_contact: dict, now: datetime) -> bool:
    """直近 MIN_RECONTACT_HOURS 時間以内に接触済みなら True（=スキップすべき）。"""
    dt = last_contact.get(username.lower())
    if dt is None:
        return False
    return (now - dt) < timedelta(hours=MIN_RECONTACT_HOURS)


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
    # 引数パース
    args = sys.argv[1:]
    target_accounts = None
    influencer_mode = "--mode" in args and args[args.index("--mode") + 1] == "influencer" if "--mode" in args else False

    if "--target" in args:
        idx = args.index("--target")
        if idx + 1 < len(args):
            target_accounts = [args[idx + 1].lstrip("@")]
        else:
            print("[ERROR] --target の後にユーザー名を指定してください。")
            print("  例: python sniper_radar.py --target nyakomiya")
            sys.exit(1)

    is_targeted = "--target" in args

    if influencer_mode:
        if is_targeted:
            # --target指定: 単一アカウントを per-account 方式で処理
            max_results_per_account = MAX_RESULTS
        max_new_drafts = INFLUENCER_MAX_DRAFTS_PER_RUN
    else:
        if target_accounts is None:
            target_accounts = load_target_accounts()
        max_results_per_account = MAX_RESULTS
        max_new_drafts           = MAX_NEW_DRAFTS_PER_RUN

    mode_label = "influencer（同業リスペクト型）" if influencer_mode else "通常（セラピスト共感型）"
    print("=" * 60)
    print("sniper_radar.py 起動")
    print(f"実行日時: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"モード: {mode_label}")
    if influencer_mode:
        if is_targeted:
            print(f"  方式: per-account（--target指定）: {target_accounts}")
        else:
            print(f"  方式: リストタイムライン（LIST_ID={LIST_ID}）")
    else:
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

    # 既存URL・各アカウントの最終接触日時を読み込む（重複防止＋再接触インターバル制御）
    existing_urls = load_existing_urls(SCOUT_CSV)
    last_contact  = load_account_last_contact(SCOUT_CSV)
    now_utc       = datetime.now(timezone.utc)
    # --target 手動指定時はインターバルを無視（人間の意図的な単一スキャン）
    is_targeted   = "--target" in args
    print(f"\n[2/4] 既存CSV確認: URL {len(existing_urls)} 件 / 接触済みアカウント {len(last_contact)} 件")

    # 集計用
    total_fetched  = 0
    total_passed   = 0
    total_saved    = 0
    total_skipped  = 0
    total_interval = 0

    if influencer_mode and not is_targeted:
        # ── リストタイムライン方式（N per-account API calls → 1 list API call）──
        print(f"\n[3/4] リストタイムライン取得中... (LIST_ID={LIST_ID})")
        print(f"  制御: 再接触間隔 {MIN_RECONTACT_HOURS}h / 1アカウント上限 {MAX_DRAFTS_PER_ACCOUNT}件 / "
              f"1ラン上限 {max_new_drafts}件")

        all_tweets = fetch_list_tweets(LIST_ID, bearer_token, INFLUENCER_LIST_MAX_RESULTS)
        total_fetched = len(all_tweets)
        print(f"  取得: {total_fetched} 件（時系列降順）")

        per_account_count: dict = {}  # {username: count}（1ラン1アカウント起案上限の制御）

        for tweet in all_tweets:
            if total_saved >= max_new_drafts:
                print(f"\n[STOP] 1ランの起案上限（{max_new_drafts}件）に到達。")
                break

            username = tweet["username"]

            # 1ラン・1アカウント起案上限
            if per_account_count.get(username, 0) >= MAX_DRAFTS_PER_ACCOUNT:
                continue

            # 72hインターバル
            if is_within_recontact_window(username, last_contact, now_utc):
                dt = last_contact.get(username.lower())
                print(f"  [INTERVAL] @{username}: {MIN_RECONTACT_HOURS}h以内接触済み（最終: {dt:%Y-%m-%d %H:%M UTC}）→ スキップ")
                total_interval += 1
                continue

            url = tweet["url"]

            # 重複チェック
            if url in existing_urls:
                total_skipped += 1
                continue

            print(f"\n--- @{username} ---")
            print(f"  {tweet['text'][:60]}...")

            # スクリーニング
            is_pass, reason = screen_tweet(tweet["text"], gemini_client)
            if not is_pass:
                print(f"  [REJECT] {reason[:40]} | {url}")
                continue

            total_passed += 1
            print(f"  [PASS]  スクリーニング通過: {url}")

            # インフルエンサーリプライ起案（画像ありの場合はマルチモーダル）
            m_urls = tweet.get("media_urls", [])
            if m_urls:
                print(f"  [IMAGE]  画像あり({len(m_urls)}枚) → マルチモーダル起案")
            reply_draft = draft_influencer_reply(tweet["text"], gemini_client, media_urls=m_urls)
            char_count  = len(reply_draft)
            print(f"  [DRAFT] {char_count}字: {reply_draft[:60]}...")

            # CSV追記
            row = {
                "取得日時":     datetime.now(timezone.utc).strftime(DATETIME_FMT),
                "対象URL":      url,
                "ユーザー名":   username,
                "対象ツイート": tweet["text"].replace("\n", " "),
                "AIリプライ案": reply_draft,
            }
            append_to_scout_csv(row, SCOUT_CSV)
            existing_urls.add(url)
            per_account_count[username] = per_account_count.get(username, 0) + 1
            total_saved += 1
            print(f"  [SAVED] {SCOUT_CSV} に追記しました")

    else:
        # ── per-account ループ方式（通常モード OR influencer --target 指定）──
        print("\n[3/4] ツイート取得・スクリーニング・起案を開始...")
        print(f"  制御: 再接触間隔 {MIN_RECONTACT_HOURS}h / 1アカウント上限 {MAX_DRAFTS_PER_ACCOUNT}件 / "
              f"1ラン上限 {max_new_drafts}件" + ("（--target: 間隔無視）" if is_targeted else ""))

        for username in target_accounts:
            if total_saved >= max_new_drafts:
                print(f"\n[STOP] 1ランの起案上限（{max_new_drafts}件）に到達。残りのアカウントはスキップします。")
                break

            print(f"\n--- @{username} ---")

            # 再接触インターバル: 直近72h以内に接触済みならアカウントごとスキップ
            if not is_targeted and is_within_recontact_window(username, last_contact, now_utc):
                dt = last_contact.get(username.lower())
                print(f"  [INTERVAL] {MIN_RECONTACT_HOURS}h以内に接触済み（最終: {dt:%Y-%m-%d %H:%M UTC}）→ スキップ")
                total_interval += 1
                continue

            tweets = fetch_recent_tweets(username, bearer_token, max_results=max_results_per_account)
            print(f"  取得: {len(tweets)} 件（RT・リプライ除外済み）")
            total_fetched += len(tweets)

            account_saved = 0
            for tweet in tweets:
                if account_saved >= MAX_DRAFTS_PER_ACCOUNT:
                    break
                if total_saved >= max_new_drafts:
                    break

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

                # リプライ起案（モードで分岐・画像ありの場合はマルチモーダル）
                m_urls = tweet.get("media_urls", [])
                if m_urls:
                    print(f"  [IMAGE]  画像あり({len(m_urls)}枚) → マルチモーダル起案")
                if influencer_mode:
                    reply_draft = draft_influencer_reply(tweet["text"], gemini_client, media_urls=m_urls)
                else:
                    reply_draft = draft_reply(tweet["text"], gemini_client, media_urls=m_urls)
                char_count  = len(reply_draft)
                print(f"  [DRAFT] {char_count}字: {reply_draft[:60]}...")

                # CSV追記
                row = {
                    "取得日時":     datetime.now(timezone.utc).strftime(DATETIME_FMT),
                    "対象URL":      url,
                    "ユーザー名":   username,
                    "対象ツイート": tweet["text"].replace("\n", " "),
                    "AIリプライ案": reply_draft,
                }
                append_to_scout_csv(row, SCOUT_CSV)
                existing_urls.add(url)
                account_saved += 1
                total_saved   += 1
                print(f"  [SAVED] {SCOUT_CSV} に追記しました")

    # サマリー
    print("\n" + "=" * 60)
    print("[実行サマリー]")
    if influencer_mode and not is_targeted:
        print(f"  取得方式              : リストタイムライン（LIST_ID={LIST_ID}）")
    else:
        print(f"  監視アカウント数      : {len(target_accounts)}")
    print(f"  ツイート取得数        : {total_fetched}")
    print(f"  間隔スキップ(アカウント): {total_interval}")
    print(f"  重複スキップ数        : {total_skipped}")
    print(f"  スクリーニング通過    : {total_passed}")
    print(f"  CSV書き込み数         : {total_saved}")
    print(f"  出力先                : {SCOUT_CSV}")
    print("=" * 60)


if __name__ == "__main__":
    main()
