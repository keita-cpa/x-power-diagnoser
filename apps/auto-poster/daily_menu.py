"""
daily_menu.py -- 今日の交流メニュー生成（毎朝1回・タスクスケジューラから自動起動）

3つの交流エンジンの起案結果を1つのHTMLメニューに集約する:
  1. 返信し返し   -- 自分の投稿に来た返信(メンション)へのリプライ案(2026アルゴ最重量 +75)
  2. リプライ     -- sniper_radar.py の新規起案
  3. 引用リポスト -- quote_reposter.py の新規起案
  4. 新規ターゲット候補 -- keyword_scout.py(月曜のみ自動実行)

起案は自動・投稿は手動承認(凍結回避規約は変更しない)。
メニューの「返信画面を開く」を押すと、案がプリセットされたXの投稿画面が開く。

使い方:
    venv/Scripts/python daily_menu.py                # フル実行
    venv/Scripts/python daily_menu.py --skip-sniper --skip-quote --skip-mentions
    venv/Scripts/python daily_menu.py --with-scout   # keyword_scout も強制実行
"""

import csv
import html
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

# Windows コンソールの文字化け対策
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time

import tweepy
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
from post_generator import SAFETY_SETTINGS
from prompts import SYSTEM_PROMPT, _TONE_REPLY
from sniper_radar import (
    DATETIME_FMT,
    REPLY_TEMP_MAX,
    REPLY_TEMP_MIN,
    SCOUT_CSV,
    append_to_scout_csv,
    load_existing_urls,
)

# ──────────────────────────────────────────
# 定数
# ──────────────────────────────────────────

BASE_DIR     = Path(__file__).parent
MENU_DIR     = BASE_DIR / "data" / "menus"
MENTION_CSV  = str(BASE_DIR / "data" / "logs" / "mention_drafts.csv")
QUOTE_CSV    = str(BASE_DIR / "data" / "logs" / "quote_drafts.csv")
RESULTS_CSV  = str(BASE_DIR / "data" / "logs" / "keyword_scout_results.csv")
STATE_FILE   = BASE_DIR / "data" / "logs" / "mention_state.txt"
SELF_ID_FILE = BASE_DIR / "data" / "config" / "self_user_id.txt"

REPLY_MODEL        = "gemini-3-flash-preview"  # 短文生成(model-routing.md 準拠)
MAX_MENTION_FETCH  = 20   # 1回の取得上限
MAX_MENTION_DRAFTS = 10   # 1ランの起案上限(コスト暴走防止)
MAX_RETRIES        = 3
RETRY_WAIT         = 2    # 秒
ENGINE_TIMEOUT     = 900  # サブエンジン(sniper/quote/scout)のタイムアウト(秒)


# ──────────────────────────────────────────
# 共通ヘルパー
# ──────────────────────────────────────────

def read_csv_rows(path: str) -> list[dict]:
    """CSVを全行読み込む。ファイルが無ければ空リスト。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def tweet_id_from_url(url: str) -> str:
    """ツイートURL末尾のステータスIDを返す。"""
    return url.rstrip("/").split("/")[-1]


def run_engine(script_name: str) -> bool:
    """サブエンジンを同一インタプリタで実行する。失敗してもメニュー生成は続行する。"""
    print(f"\n[RUN] {script_name} を実行中...")
    try:
        proc = subprocess.run(
            [sys.executable, script_name],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=ENGINE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(f"  [WARN] {script_name} がタイムアウト({ENGINE_TIMEOUT}秒)。スキップして続行します")
        return False
    tail = "\n".join((proc.stdout or "").splitlines()[-8:])
    print("  " + tail.replace("\n", "\n  "))
    if proc.returncode != 0:
        err_tail = "\n".join((proc.stderr or "").splitlines()[-5:])
        print(f"  [WARN] {script_name} が異常終了(code={proc.returncode})")
        print("  " + err_tail.replace("\n", "\n  "))
        return False
    return True


# ──────────────────────────────────────────
# 1. 返信し返し(メンション取得 → リプライ案起案)
# ──────────────────────────────────────────

def get_user_client() -> tweepy.Client:
    """OAuth 1.0a ユーザーコンテキストのクライアント(メンション取得用)。"""
    return tweepy.Client(
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=False,
    )


def get_self_user_id(client: tweepy.Client) -> str:
    """自分のユーザーIDを返す。初回のみAPIで取得しファイルにキャッシュする。"""
    if SELF_ID_FILE.exists():
        cached = SELF_ID_FILE.read_text(encoding="utf-8").strip()
        if cached:
            return cached
    for attempt in range(MAX_RETRIES):
        try:
            me = client.get_me(user_auth=True)
            break
        except tweepy.errors.TweepyException as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
                continue
            raise RuntimeError(f"get_me 失敗({MAX_RETRIES}回): {e}") from e
    user_id = str(me.data.id)
    SELF_ID_FILE.write_text(user_id, encoding="utf-8")
    return user_id


def load_since_id() -> str | None:
    if STATE_FILE.exists():
        val = STATE_FILE.read_text(encoding="utf-8").strip()
        return val or None
    return None


def save_since_id(newest_id: str):
    STATE_FILE.write_text(str(newest_id), encoding="utf-8")


def fetch_new_mentions(client: tweepy.Client, self_id: str, since_id: str | None) -> tuple[list[dict], str | None]:
    """
    自分宛てメンション(=自分の投稿への返信を含む)を取得する。
    返り値: ([{"id", "text", "username", "parent_id"}], newest_id)
    """
    kwargs = dict(
        id=self_id,
        max_results=MAX_MENTION_FETCH,
        tweet_fields=["text", "created_at", "author_id", "referenced_tweets"],
        expansions=["author_id"],
        user_fields=["username"],
        user_auth=True,
    )
    if since_id:
        kwargs["since_id"] = since_id

    resp = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.get_users_mentions(**kwargs)
            break
        except tweepy.errors.TweepyException as e:
            if attempt < MAX_RETRIES - 1:
                print(f"  [RETRY {attempt + 1}/{MAX_RETRIES}] メンション取得失敗: {e}")
                time.sleep(RETRY_WAIT)
            else:
                print(f"  [WARN] メンション取得を断念: {e}")
                return [], None

    if resp is None or not resp.data:
        return [], (resp.meta.get("newest_id") if resp and resp.meta else None)

    users = {u.id: u.username for u in (resp.includes or {}).get("users", [])}
    mentions = []
    for tweet in resp.data:
        if str(tweet.author_id) == self_id:
            continue  # 自分の投稿は除外
        parent_id = None
        for ref in tweet.referenced_tweets or []:
            if ref.type == "replied_to":
                parent_id = str(ref.id)
        mentions.append({
            "id":        str(tweet.id),
            "text":      tweet.text,
            "username":  users.get(tweet.author_id, str(tweet.author_id)),
            "parent_id": parent_id,
        })
    newest_id = resp.meta.get("newest_id") if resp.meta else None
    return mentions, newest_id


def fetch_parent_texts(client: tweepy.Client, parent_ids: list[str]) -> dict[str, str]:
    """返信元(自分の投稿)の本文をまとめて取得する。失敗しても空dictで続行。"""
    ids = [i for i in dict.fromkeys(parent_ids) if i]
    if not ids:
        return {}
    try:
        resp = client.get_tweets(ids=ids[:100], tweet_fields=["text"], user_auth=True)
    except tweepy.errors.TweepyException as e:
        print(f"  [WARN] 返信元ツイート取得失敗(文脈なしで起案): {e}")
        return {}
    return {str(t.id): t.text for t in (resp.data or [])}


def draft_mention_reply(reply_text: str, parent_text: str, gemini_client) -> str:
    """自分の投稿に来た返信への「返信し返し」案を起案する。"""
    context = f"ぼくの元の投稿:\n{parent_text}\n\n" if parent_text else ""
    prompt = f"""以下は、ぼく(@Keita_CPA)の投稿に届いた返信です。
この返信への「返信し返し」の案を1つ起案してください。

【大前提(最優先・例外なし)】
相手はわざわざ時間を使って返信をくれた人です。
まず「ちゃんと受け取った」ことが伝わる一言から入ること。
指摘・訂正・求められていないアドバイスは1文たりとも書かないこと。

【書き方】
1. 相手の返信の中の【具体的な言葉】をひとつ拾って受け止める(定型のお礼だけで終えない)
2. 会話が半歩だけ続く余白を残す(質問攻めにしない。軽い一言でよい)
3. 140字以内。「〜ですよね」「〜な気がする」と言い切らない柔らかい語尾
4. 締めは温度のしっぽ(半歩の気づかい・自分を下げる一言・先の楽しみ)を一筆

---
{context}届いた返信:
{reply_text}
"""
    try:
        response = gemini_client.models.generate_content(
            model=REPLY_MODEL,
            contents=prompt,
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


def process_mentions(gemini_client) -> int:
    """メンション取得→起案→mention_drafts.csv 追記。新規起案数を返す。"""
    print("\n[RUN] 返信し返し(メンション)を確認中...")
    client  = get_user_client()
    try:
        self_id = get_self_user_id(client)
    except RuntimeError as e:
        print(f"  [WARN] {e} → 返信し返しをスキップします")
        return 0

    mentions, newest_id = fetch_new_mentions(client, self_id, load_since_id())
    print(f"  新規メンション: {len(mentions)} 件")
    if newest_id:
        save_since_id(newest_id)
    if not mentions:
        return 0

    parent_texts  = fetch_parent_texts(client, [m["parent_id"] for m in mentions])
    existing_urls = load_existing_urls(MENTION_CSV)
    saved = 0
    for m in mentions:
        if saved >= MAX_MENTION_DRAFTS:
            print(f"  [STOP] 起案上限({MAX_MENTION_DRAFTS}件)に到達")
            break
        url = f"https://twitter.com/{m['username']}/status/{m['id']}"
        if url in existing_urls:
            continue
        draft = draft_mention_reply(m["text"], parent_texts.get(m["parent_id"] or "", ""), gemini_client)
        append_to_scout_csv({
            "取得日時":     datetime.now(timezone.utc).strftime(DATETIME_FMT),
            "対象URL":      url,
            "ユーザー名":   m["username"],
            "対象ツイート": m["text"].replace("\n", " "),
            "AIリプライ案": draft,
        }, MENTION_CSV)
        existing_urls.add(url)
        saved += 1
        print(f"  [SAVED] @{m['username']}: {draft[:40]}...")
    return saved


# ──────────────────────────────────────────
# 2. HTMLメニュー生成
# ──────────────────────────────────────────

def _card(username: str, target_text: str, target_url: str, draft: str,
          intent_url: str, intent_label: str, idx: str) -> str:
    return f"""
<div class="card">
  <div class="meta"><span class="user">@{html.escape(username)}</span>
    <a href="{html.escape(target_url)}" target="_blank">元ポストを見る</a></div>
  <blockquote>{html.escape(target_text)}</blockquote>
  <textarea id="{idx}" rows="3">{html.escape(draft)}</textarea>
  <div class="actions">
    <a class="btn primary" href="{html.escape(intent_url)}" target="_blank">{intent_label}</a>
    <button class="btn" onclick="copyText('{idx}')">案をコピー</button>
  </div>
</div>"""


def build_menu_html(mention_rows: list[dict], sniper_rows: list[dict],
                    quote_rows: list[dict], scout_rows: list[dict]) -> str:
    today = datetime.now().strftime("%Y-%m-%d (%a)")
    total = len(mention_rows) + len(sniper_rows) + len(quote_rows)

    sections = []

    def section(title: str, note: str, cards: list[str], empty_msg: str) -> str:
        body = "\n".join(cards) if cards else f'<p class="empty">{empty_msg}</p>'
        return f'<section><h2>{title}</h2><p class="note">{note}</p>{body}</section>'

    # 1. 返信し返し
    cards = []
    for i, r in enumerate(mention_rows):
        tid = tweet_id_from_url(r["対象URL"])
        intent = f"https://twitter.com/intent/tweet?in_reply_to_tweet_id={tid}&text={quote(r['AIリプライ案'])}"
        cards.append(_card(r["ユーザー名"], r["対象ツイート"], r["対象URL"],
                           r["AIリプライ案"], intent, "この案で返信画面を開く", f"m{i}"))
    sections.append(section(
        "1. 返信し返し(最優先)",
        "自分の投稿に返信をくれた人への返信。2026年アルゴリズムで最も重い加点(+75)。ここだけは全件返すこと。",
        cards, "新しい返信はありません。"))

    # 2. リプライ
    cards = []
    for i, r in enumerate(sniper_rows):
        tid = tweet_id_from_url(r["対象URL"])
        intent = f"https://twitter.com/intent/tweet?in_reply_to_tweet_id={tid}&text={quote(r['AIリプライ案'])}"
        cards.append(_card(r["ユーザー名"], r["対象ツイート"], r["対象URL"],
                           r["AIリプライ案"], intent, "この案で返信画面を開く", f"s{i}"))
    sections.append(section(
        "2. リプライ(セラピストとの接点づくり)",
        "実測でメイン投稿の8.1倍のIMP効率。関係構築の主戦場。1日3〜6件でよい。",
        cards, "今日の新規リプライ案はありません。"))

    # 3. 引用リポスト
    cards = []
    for i, r in enumerate(quote_rows):
        draft = r.get("AI引用コメント案", "")
        intent = f"https://twitter.com/intent/tweet?text={quote(draft)}&url={quote(r['対象URL'])}"
        cards.append(_card(r["ユーザー名"], r["対象ツイート"], r["対象URL"],
                           draft, intent, "この案で引用画面を開く", f"q{i}"))
    sections.append(section(
        "3. 引用リポスト(実測最高フォーマット AlgoScore=44)",
        "相手が「リポストで返したくなる」代弁・承認コメント。1日1〜2件でよい。",
        cards, "今日の新規引用案はありません。"))

    # 4. 新規ターゲット候補(月曜のみ)
    if scout_rows:
        items = "\n".join(
            f'<li><a href="https://twitter.com/{html.escape(r["ユーザー名"])}" target="_blank">'
            f'@{html.escape(r["ユーザー名"])}</a> ({html.escape(str(r["フォロワー数"]))}F) '
            f'{html.escape(r["bio"][:60])}</li>'
            for r in scout_rows)
        sections.append(
            f'<section><h2>4. 新規ターゲット候補(週次)</h2>'
            f'<p class="note">プロフィールを見て「個人セラピスト」なら data/config/target_accounts.txt に追記。</p>'
            f'<ul>{items}</ul></section>')

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>今日の交流メニュー {today}</title>
<style>
  body {{ font-family: "Yu Gothic UI", "Hiragino Sans", sans-serif; max-width: 720px;
         margin: 0 auto; padding: 16px; background: #f5f6f8; color: #1a1a2e; }}
  h1 {{ font-size: 1.3rem; }} h2 {{ font-size: 1.05rem; border-left: 4px solid #4a6fa5;
         padding-left: 8px; margin-top: 28px; }}
  .lead {{ background: #fff; border-radius: 8px; padding: 12px 16px; font-size: .9rem; }}
  .note {{ color: #555; font-size: .82rem; }}
  .card {{ background: #fff; border-radius: 8px; padding: 12px 16px; margin: 10px 0;
           box-shadow: 0 1px 2px rgba(0,0,0,.06); }}
  .meta {{ font-size: .85rem; margin-bottom: 6px; }} .user {{ font-weight: 600; margin-right: 8px; }}
  blockquote {{ margin: 6px 0; padding: 6px 10px; background: #f0f2f5; border-radius: 6px;
               font-size: .88rem; color: #333; }}
  textarea {{ width: 100%; box-sizing: border-box; font-size: .9rem; border: 1px solid #ccd;
             border-radius: 6px; padding: 8px; background: #fbfcff; }}
  .actions {{ margin-top: 6px; display: flex; gap: 8px; }}
  .btn {{ display: inline-block; padding: 6px 14px; border-radius: 6px; font-size: .85rem;
         border: 1px solid #4a6fa5; color: #4a6fa5; background: #fff; cursor: pointer;
         text-decoration: none; }}
  .btn.primary {{ background: #4a6fa5; color: #fff; }}
  .empty {{ color: #888; font-size: .85rem; }}
  .footer {{ margin-top: 32px; font-size: .78rem; color: #777; }}
</style>
</head>
<body>
<h1>今日の交流メニュー {today}</h1>
<div class="lead">
  合計 <b>{total}件</b>。所要時間の目安は5〜10分。上から順に。<br>
  案は下書きです。<b>一読して、違和感があれば直すか捨てる</b>(あなたの声が主・AIは下書き係)。<br>
  ルール: 全肯定・共感のみ / 説教・指摘・未要求アドバイス禁止 / 迷ったら送らない。
</div>
{"".join(sections)}
<div class="footer">
  生成: daily_menu.py / 履歴は data/logs/*.csv で自動管理(送信後の記録作業は不要)。<br>
  全体像と「なぜこれをやるのか」は docs/system_overview.html を参照。
</div>
<script>
function copyText(id) {{
  const el = document.getElementById(id);
  el.select();
  if (navigator.clipboard) {{ navigator.clipboard.writeText(el.value); }}
  else {{ document.execCommand('copy'); }}
}}
</script>
</body>
</html>"""


# ──────────────────────────────────────────
# 3. メイン処理
# ──────────────────────────────────────────

def main():
    args = sys.argv[1:]
    skip_mentions = "--skip-mentions" in args
    skip_sniper   = "--skip-sniper" in args
    skip_quote    = "--skip-quote" in args
    # keyword_scout は月曜のみ自動実行(X API読み取りクォータの節約)
    run_scout = ("--with-scout" in args) or (
        datetime.now().weekday() == 0 and "--skip-scout" not in args)

    print("=" * 60)
    print("daily_menu.py 起動(今日の交流メニュー生成)")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    MENU_DIR.mkdir(parents=True, exist_ok=True)
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    # 実行前の行数スナップショット(このランで増えた分だけをメニューに載せる)
    before = {p: len(read_csv_rows(p)) for p in (MENTION_CSV, SCOUT_CSV, QUOTE_CSV, RESULTS_CSV)}

    if not skip_mentions:
        process_mentions(gemini_client)
    if not skip_sniper:
        run_engine("sniper_radar.py")
    if not skip_quote:
        run_engine("quote_reposter.py")
    if run_scout:
        run_engine("keyword_scout.py")

    mention_rows = read_csv_rows(MENTION_CSV)[before[MENTION_CSV]:]
    sniper_rows  = read_csv_rows(SCOUT_CSV)[before[SCOUT_CSV]:]
    quote_rows   = read_csv_rows(QUOTE_CSV)[before[QUOTE_CSV]:]
    scout_rows   = read_csv_rows(RESULTS_CSV)[before[RESULTS_CSV]:]

    html_text = build_menu_html(mention_rows, sniper_rows, quote_rows, scout_rows)
    menu_path = MENU_DIR / f"exchange_menu_{datetime.now().strftime('%Y%m%d')}.html"
    menu_path.write_text(html_text, encoding="utf-8")
    (MENU_DIR / "latest.html").write_text(html_text, encoding="utf-8")

    print("\n" + "=" * 60)
    print("[実行サマリー]")
    print(f"  返信し返し案 : {len(mention_rows)} 件")
    print(f"  リプライ案   : {len(sniper_rows)} 件")
    print(f"  引用案       : {len(quote_rows)} 件")
    print(f"  新規候補     : {len(scout_rows)} 件" + ("" if run_scout else "(scout未実行)"))
    print(f"  メニュー     : {menu_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
