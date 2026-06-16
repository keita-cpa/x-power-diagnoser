"""
quote_reposter.py -- 引用リポスト起案システム

指定したターゲットの最新ツイートを取得し、
gemini-2.5-flash-lite でスクリーニング -> gemini-3-flash-preview で
「相手がリポストで返したくなる代弁コメント」を起案 -> CSV出力する。

実測で最もスコアが高いフォーマット（Quote Tweet形式 / AlgoScore=44）の起案専用ツール。
投稿は手動承認フロー（CSVを目視 → 手で引用リポスト）。

設計思想（.claude/rules/persona.md・skills/x-algorithm 準拠）:
  - 全肯定・共感・事実の承認のみ。指摘・説教・求められないアドバイスは完全禁止。
  - 相手の見えない努力・気遣いを「代弁」し、相手が自分のフォロワーに見せたくなる内容にする。
  - 同一アカウントへの過剰接触を防ぐため、リプライ(scouted_targets.csv)と引用(本CSV)の
    両方の接触履歴を参照して 72h インターバル制御をかける。

使い方:
    venv/Scripts/python quote_reposter.py                 # target_accounts.txt を巡回
    venv/Scripts/python quote_reposter.py --target <id>   # 単一アカウントを即時スキャン（間隔無視）
"""

import csv
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows コンソールの文字化け対策
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from google import genai
from google.genai import types

from config import GEMINI_API_KEY
from post_generator import SAFETY_SETTINGS
from prompts import SYSTEM_PROMPT, _TONE_QUOTE

# sniper_radar の取得・スクリーニング・インターバル基盤を再利用する
from sniper_radar import (
    DATETIME_FMT,
    MIN_RECONTACT_HOURS,
    REPLY_TEMP_MAX,
    REPLY_TEMP_MIN,
    SCOUT_CSV,
    fetch_recent_tweets,
    get_bearer_token,
    is_within_recontact_window,
    load_account_last_contact,
    load_existing_urls,
    load_target_accounts,
    screen_tweet,
)

# ──────────────────────────────────────────
# 定数
# ──────────────────────────────────────────

QUOTE_CSV   = str(Path(__file__).parent / "data" / "logs" / "quote_drafts.csv")
CSV_COLUMNS = ["取得日時", "対象URL", "ユーザー名", "対象ツイート", "AI引用コメント案"]

REPLY_MODEL = "gemini-3-flash-preview"  # 短文生成（model-routing.md 準拠）

# 1ランの起案上限。リプライ(sniper=6)と合わせて1日5〜10件が目安
MAX_NEW_DRAFTS_PER_RUN = 4
# 1ラン・1アカウントあたりの起案上限（接触を多様な相手に分散）
MAX_DRAFTS_PER_ACCOUNT = 1


# ──────────────────────────────────────────
# 接触履歴のマージ（リプライ＋引用の両方を見る）
# ──────────────────────────────────────────

def merged_last_contact() -> dict:
    """
    引用(quote_drafts.csv)とリプライ(scouted_targets.csv)の両方から
    各アカウントの最終接触日時を集計し、新しい方を採用して返す。
    同一人物への横断的な過剰接触を防ぐための真実源。
    """
    merged = load_account_last_contact(QUOTE_CSV)
    for name, dt in load_account_last_contact(SCOUT_CSV).items():
        if name not in merged or dt > merged[name]:
            merged[name] = dt
    return merged


# ──────────────────────────────────────────
# 引用コメント起案
# ──────────────────────────────────────────

def draft_quote(tweet_text: str, gemini_client) -> str:
    """
    gemini-3-flash-preview で引用リポストのコメント案を起案する。
    system_instruction に SYSTEM_PROMPT + _TONE_QUOTE を適用。
    温度はラン毎にランダム化し、AI定型文の固定化を防ぐ。
    返り値: 引用コメント案テキスト（100字以内）
    """
    prompt = f"""以下のツイートを引用リポストする際の「コメント案」を1つ起案してください。
書き手は @Keita_CPA（業界を愛する一人の良客で、たまたまBig4出身の公認会計士・税理士）です。

【大前提（最優先・例外なし）】
これは相手への贈り物です。指摘・説教・採点・求められていないアドバイスは1文たりとも書かないこと。
全肯定・共感・事実の承認のみ。

【「リポストで返したくなる」3パターン（いずれか1つを選び、元ツイートに最も合うものを採用）】

パターンA: 承認型（努力の言語化）
  元ツイートに書かれた「誰も見ていないのに続けていること」や「当たり前のようにしている気遣い」を
  取り上げ、それが持つ意味を本人より少しだけ的確に言語化する。
  相手が「この人、わかってくれてる」と感じると自分のフォロワーに見せたくなる。

パターンB: 代弁型（哲学の要約）
  元ツイートの奥に流れる「相手の芯・哲学・信念」を一行で要約する。
  相手が「そう、これが言いたかった」と膝を打つ精度が目標。
  「〜なんだなぁ」「〜が好きだなぁ」と言い切らず、余韻を残すこと（中距離維持）。

パターンC: 紹介型（第三者への橋渡し）
  元ツイートを読んだ第三者が「このセラピストさん、素敵だな」と自然に感じるよう、
  相手を主役・上座に置いて紹介する。
  自分（引用側）は一歩引き、手柄話・評価者のトーンに転落しないこと。

【書き方の原則（書籍エッセンス）】
・言い切らない: 「〜なのかな」「〜な気がする」と語尾を少し濁し、共感を得やすくする。
  断定しすぎると「上から目線」になり相手がリポストしにくくなる。
・元ツイート固有のディテールから書き起こす: 毎回同じ書き出し・語尾にしない。
  汎用的な「頑張ってますね」は禁止。元ツイートの具体的な一言・シーンを起点にすること。
・相手を上座に置く（逆マウント）: 「自分は一歩引いて見ていた良客」の立場を維持。

【専門知識の扱い】
法・税・お金の専門知識は、元ツイートが明確に質問・相談している時だけ「お守り」の温度で。
それ以外では一切出さないこと。

---
引用元ツイート:
{tweet_text}
"""
    try:
        response = gemini_client.models.generate_content(
            model=REPLY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT + "\n\n" + _TONE_QUOTE,
                safety_settings=SAFETY_SETTINGS,
                temperature=random.uniform(REPLY_TEMP_MIN, REPLY_TEMP_MAX),
            ),
        )
        return (response.text or "").strip()
    except Exception as e:
        print(f"  [QUOTE ERROR] Gemini呼び出し失敗: {e}")
        return f"[起案失敗: {e}]"


# ──────────────────────────────────────────
# CSV追記
# ──────────────────────────────────────────

def append_to_quote_csv(row: dict, csv_path: str):
    """CSVに1行追記する。ファイル未存在時はヘッダー付きで新規作成。"""
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ──────────────────────────────────────────
# メイン処理
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
            print("  例: python quote_reposter.py --target nyakomiya")
            sys.exit(1)
    if target_accounts is None:
        target_accounts = load_target_accounts()

    print("=" * 60)
    print("quote_reposter.py 起動（引用リポスト起案）")
    print(f"実行日時: {datetime.now(timezone.utc).strftime(DATETIME_FMT)}")
    print(f"監視対象: {target_accounts}")
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

    # 既存URL・接触履歴（リプライ＋引用の両方）を読み込む
    existing_urls = load_existing_urls(QUOTE_CSV)
    last_contact  = merged_last_contact()
    now_utc       = datetime.now(timezone.utc)
    is_targeted   = "--target" in args
    print(f"\n[2/4] 既存CSV確認: 引用URL {len(existing_urls)} 件 / "
          f"接触済みアカウント(リプライ+引用) {len(last_contact)} 件")

    # 集計用
    total_fetched  = 0
    total_passed   = 0
    total_saved    = 0
    total_skipped  = 0
    total_interval = 0

    print("\n[3/4] ツイート取得・スクリーニング・引用起案を開始...")
    print(f"  制御: 再接触間隔 {MIN_RECONTACT_HOURS}h / 1アカウント上限 {MAX_DRAFTS_PER_ACCOUNT}件 / "
          f"1ラン上限 {MAX_NEW_DRAFTS_PER_RUN}件" + ("（--target: 間隔無視）" if is_targeted else ""))

    for username in target_accounts:
        if total_saved >= MAX_NEW_DRAFTS_PER_RUN:
            print(f"\n[STOP] 1ランの起案上限（{MAX_NEW_DRAFTS_PER_RUN}件）に到達。残りはスキップします。")
            break

        print(f"\n--- @{username} ---")

        # 再接触インターバル: 直近72h以内にリプライ or 引用で接触済みならスキップ
        if not is_targeted and is_within_recontact_window(username, last_contact, now_utc):
            dt = last_contact.get(username.lower())
            print(f"  [INTERVAL] {MIN_RECONTACT_HOURS}h以内に接触済み（最終: {dt:%Y-%m-%d %H:%M UTC}）→ スキップ")
            total_interval += 1
            continue

        tweets = fetch_recent_tweets(username, bearer_token)
        print(f"  取得: {len(tweets)} 件（RT・リプライ除外済み）")
        total_fetched += len(tweets)

        account_saved = 0
        for tweet in tweets:
            if account_saved >= MAX_DRAFTS_PER_ACCOUNT:
                break
            if total_saved >= MAX_NEW_DRAFTS_PER_RUN:
                break

            url = tweet["url"]

            if url in existing_urls:
                print(f"  [SKIP] 既存URL: {url}")
                total_skipped += 1
                continue

            is_pass, reason = screen_tweet(tweet["text"], gemini_client)
            if not is_pass:
                print(f"  [REJECT] {reason[:40]} | {url}")
                continue

            total_passed += 1
            print(f"  [PASS]  スクリーニング通過: {url}")

            quote_draft = draft_quote(tweet["text"], gemini_client)
            char_count  = len(quote_draft)
            print(f"  [DRAFT] {char_count}字: {quote_draft[:60]}...")

            row = {
                "取得日時":       datetime.now(timezone.utc).strftime(DATETIME_FMT),
                "対象URL":        url,
                "ユーザー名":     username,
                "対象ツイート":   tweet["text"].replace("\n", " "),
                "AI引用コメント案": quote_draft,
            }
            append_to_quote_csv(row, QUOTE_CSV)
            existing_urls.add(url)
            account_saved += 1
            total_saved   += 1
            print(f"  [SAVED] {QUOTE_CSV} に追記しました")

    # サマリー
    print("\n" + "=" * 60)
    print("[実行サマリー]")
    print(f"  監視アカウント数      : {len(target_accounts)}")
    print(f"  ツイート取得数        : {total_fetched}")
    print(f"  間隔スキップ(アカウント): {total_interval}")
    print(f"  重複スキップ数        : {total_skipped}")
    print(f"  スクリーニング通過    : {total_passed}")
    print(f"  CSV書き込み数         : {total_saved}")
    print(f"  出力先                : {QUOTE_CSV}")
    print("=" * 60)
    if total_saved:
        print("\n[次のアクション] CSVを目視確認し、問題なければ手動で引用リポストしてください。")
        print("  指摘・説教・未要求のアドバイスになっていないか必ずチェックすること。")


if __name__ == "__main__":
    main()
