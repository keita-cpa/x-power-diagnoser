"""
X 自動投稿スクリプト（画像自動生成・LLMO対策ALT付き）
- stock_posts_draft.csv から「フォーマット=tweet」かつ「ステータスが空欄」の
  最初の1件を取り出してXに投稿し、投稿完了行を posted_history.csv に移動する。
- base_image.jpg をベースに画像タイトルを描画した OGP 画像を動的生成して添付する。
- ALT テキストを設定して LLMO 対策を実施する。
"""

import csv
import os
import sys
from datetime import datetime
from pathlib import Path

import tweepy
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from config import (
    X_API_KEY,
    X_API_SECRET,
    X_ACCESS_TOKEN,
    X_ACCESS_TOKEN_SECRET,
)
from x_poster import get_client, post_reply

_BASE_DIR = Path(__file__).parent

DRAFT_CSV    = str(_BASE_DIR / "data/drafts/stock_posts_draft.csv")
HISTORY_CSV  = str(_BASE_DIR / "data/logs/posted_history.csv")
ENCODING     = "utf-8-sig"

BASE_IMAGE   = str(_BASE_DIR / "assets/base_image.jpg")
FONT_PATH    = str(_BASE_DIR / "assets/font.otf")
TEMP_IMAGE   = str(_BASE_DIR / "temp_post_image.jpg")

COL_ID        = "管理ID"
COL_CATEGORY  = "カテゴリ"
COL_FORMAT    = "フォーマット"
COL_TEXT      = "投稿文"
COL_REPLY     = "リプライ文"
COL_IMG_TITLE = "画像タイトル"
COL_ALT       = "ALT"
COL_STATUS    = "ステータス"
COL_POSTED_AT = "投稿日時"

FIELDNAMES = [
    COL_ID, COL_CATEGORY, COL_FORMAT, COL_TEXT,
    COL_REPLY, COL_IMG_TITLE, COL_ALT, COL_STATUS,
]
HISTORY_FIELDNAMES = [
    COL_ID, COL_CATEGORY, COL_FORMAT, COL_TEXT,
    COL_REPLY, COL_IMG_TITLE, COL_ALT, COL_STATUS, COL_POSTED_AT,
]


# ──────────────────────────────────────────
# Tweepy クライアント（v2: 投稿）・API（v1: メディアアップロード）
# get_client() は x_poster.get_client() を使用（重複定義を廃止）
# ──────────────────────────────────────────

def get_api_v1():
    """tweepy.API (v1.1) を返す。メディアアップロード・ALT設定に使用。"""
    auth = tweepy.OAuth1UserHandler(
        X_API_KEY, X_API_SECRET,
        X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET,
    )
    return tweepy.API(auth)


# ──────────────────────────────────────────
# テキスト折り返しユーティリティ
# ──────────────────────────────────────────

def wrap_text_japanese(text, font, max_width):
    """
    日本語テキストをピクセル幅に基づいて自動改行する。
    font.getbbox() でピクセル幅を測定し、max_width を超えたら改行を挿入する。

    Args:
        text (str): 改行を挿入するテキスト
        font: PIL の ImageFont オブジェクト
        max_width (int): 1行あたりの最大ピクセル幅

    Returns:
        list[str]: 改行済みの行リスト
    """
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current_line = ""
        for char in paragraph:
            candidate = current_line + char
            bbox = font.getbbox(candidate)
            line_width = bbox[2] - bbox[0]
            if line_width <= max_width:
                current_line = candidate
            else:
                if current_line:
                    lines.append(current_line)
                current_line = char
        if current_line:
            lines.append(current_line)
    return lines


# ──────────────────────────────────────────
# OGP 画像の動的生成
# ──────────────────────────────────────────

def generate_image_with_text(base_image_path, text, output_path):
    """
    ベース画像に文字を描画した OGP 画像を生成して保存する。

    Args:
        base_image_path (str): ベース画像のパス（base_image.jpg）
        text (str): 描画する画像タイトル文字列
        output_path (str): 出力先ファイルパス
    """
    img = Image.open(base_image_path).convert("RGB")
    width, height = img.size

    # 全体を少し暗くして文字を読みやすくする
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(0.6)

    draw = ImageDraw.Draw(img)

    # フォント設定（サイズを画像幅に応じて調整）
    font_size = max(72, width // 18)
    try:
        font = ImageFont.truetype(FONT_PATH, font_size)
    except Exception:
        font = ImageFont.load_default()

    # 描画可能エリア（左右マージンを除いた幅）に収まるよう自動改行
    margin = 80
    max_text_width = width - margin * 2
    wrapped_lines = wrap_text_japanese(text, font, max_text_width)

    # 各行の描画サイズを測定してテキストブロック全体の高さを算出
    line_height = font_size + 12
    total_height = line_height * len(wrapped_lines)

    # テキストブロックを画像中央に配置
    start_y = (height - total_height) // 2

    for i, line in enumerate(wrapped_lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        x = (width - line_width) // 2
        y = start_y + i * line_height

        # 視認性向上のためわずかなドロップシャドウを描画
        draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0, 180))
        # メイン白文字
        draw.text((x, y), line, font=font, fill=(255, 255, 255))

    img.save(output_path, "JPEG", quality=92)
    print(f"  [IMAGE] 画像生成完了: {output_path} ({width}x{height})")


# ──────────────────────────────────────────
# メディアアップロードと画像付き投稿
# ──────────────────────────────────────────

def post_tweet_with_image(text, image_path, alt_text):
    """
    画像をアップロードし、ALT を設定して画像付きツイートを投稿する。

    Args:
        text (str): 投稿本文
        image_path (str): アップロードする画像ファイルのパス
        alt_text (str): 画像の ALT テキスト（LLMO・アクセシビリティ対策）

    Returns:
        dict: {"success": bool, "tweet_id": str|None, "error": str|None}
    """
    try:
        api    = get_api_v1()
        client = get_client()

        # v1.1 でメディアをアップロード
        media = api.media_upload(filename=image_path)
        media_id = media.media_id

        # ALT テキストを設定（失敗しても投稿は続行する）
        if alt_text:
            try:
                api.create_media_metadata(media_id, alt_text=alt_text[:1000])
            except Exception as alt_e:
                print(f"  [WARN] ALT設定失敗（投稿は続行）: {alt_e}")

        # v2 で画像付きツイートを投稿
        response = client.create_tweet(
            text=text,
            media_ids=[media_id],
            user_auth=True,
        )
        tweet_id = response.data["id"]

        # ← ここで成功を確定させる（get_me の失敗で誤って失敗扱いにしない）
        print(f"  投稿成功: tweet_id={tweet_id}")
        try:
            me = client.get_me()
            handle = me.data.username
            print(f"  URL: https://x.com/{handle}/status/{tweet_id}")
        except Exception:
            pass  # URL表示は補助情報。失敗しても投稿の成否に影響しない

        return {"success": True, "tweet_id": tweet_id, "error": None}

    except tweepy.TooManyRequests:
        msg = "レート制限に達しました。15分後に再試行してください。"
        print(f"  {msg}")
        return {"success": False, "tweet_id": None, "error": "rate_limit"}
    except tweepy.Forbidden as e:
        msg = f"投稿が拒否されました: {e}"
        print(f"  [ERROR] {msg}")
        return {"success": False, "tweet_id": None, "error": f"forbidden: {e}"}
    except Exception as e:
        print(f"  [ERROR] 予期しないエラー: {type(e).__name__}: {e}")
        return {"success": False, "tweet_id": None, "error": str(e)}


def post_tweet_text_only(text):
    """画像なしでテキストのみ投稿する（フォールバック用）。"""
    try:
        client = get_client()
        response = client.create_tweet(text=text, user_auth=True)
        tweet_id = response.data["id"]

        # ← ここで成功を確定させる（get_me の失敗で誤って失敗扱いにしない）
        print(f"  投稿成功（テキストのみ）: tweet_id={tweet_id}")
        try:
            me = client.get_me()
            handle = me.data.username
            print(f"  URL: https://x.com/{handle}/status/{tweet_id}")
        except Exception:
            pass  # URL表示は補助情報。失敗しても投稿の成否に影響しない

        return {"success": True, "tweet_id": tweet_id, "error": None}
    except tweepy.TooManyRequests:
        print("  レート制限に達しました。15分後に再試行してください。")
        return {"success": False, "tweet_id": None, "error": "rate_limit"}
    except tweepy.Forbidden as e:
        print(f"  [ERROR] 投稿が拒否されました: {e}")
        return {"success": False, "tweet_id": None, "error": f"forbidden: {e}"}
    except Exception as e:
        print(f"  [ERROR] 予期しないエラー: {type(e).__name__}: {e}")
        return {"success": False, "tweet_id": None, "error": str(e)}


# ──────────────────────────────────────────
# CSV の読み込みとステータス列の自動補完
# ──────────────────────────────────────────

def load_csv():
    """CSV を読み込んで rows (list[dict]) を返す。不足列は空文字で補完。"""
    if not os.path.exists(DRAFT_CSV):
        print(f"[エラー] {DRAFT_CSV} が見つかりません。")
        sys.exit(1)

    with open(DRAFT_CSV, "r", encoding=ENCODING, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for row in rows:
        for col in (COL_STATUS, COL_IMG_TITLE, COL_ALT):
            if col not in row:
                row[col] = ""

    return rows


# ──────────────────────────────────────────
# 投稿対象の抽出
# ──────────────────────────────────────────

def find_target(rows):
    """「フォーマット=tweet」かつ「ステータスが空欄」の最初の行を返す。"""
    for idx, row in enumerate(rows):
        if row.get(COL_FORMAT, "").strip() == "tweet" \
                and row.get(COL_STATUS, "").strip() == "":
            return idx, row
    return None, None


# ──────────────────────────────────────────
# CSV の上書き保存
# ──────────────────────────────────────────

def save_csv(rows):
    with open(DRAFT_CSV, "w", encoding=ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ──────────────────────────────────────────
# 投稿履歴への追記
# ──────────────────────────────────────────

def append_history(row, posted_at):
    """投稿済み行を posted_history.csv に追記する。ファイルがなければ作成。"""
    write_header = not os.path.exists(HISTORY_CSV)
    with open(HISTORY_CSV, "a", encoding=ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDNAMES, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        history_row = {**row, COL_STATUS: "済", COL_POSTED_AT: posted_at}
        writer.writerow(history_row)


# ──────────────────────────────────────────
# 投稿フルフロー（画像生成・投稿・ツリー・履歴移動・CSV保存）
# conoha_worker.py からも呼び出される共通関数
# ──────────────────────────────────────────

def execute_single_post(rows, target_idx, target_row):
    """
    1件分の投稿フルフローを実行する。
    OGP画像生成 → X投稿 → ツリー投稿（リプライ文あり時）
    → 履歴CSV追記 → draft CSVから削除

    Args:
        rows (list[dict]): load_csv() で得た全行
        target_idx (int): 投稿対象の行インデックス
        target_row (dict): 投稿対象の行データ

    Returns:
        (bool, str): (成功フラグ, メッセージ or エラー内容)
    """
    category    = target_row.get(COL_CATEGORY, "")
    text        = target_row.get(COL_TEXT, "").strip()
    reply_text  = target_row.get(COL_REPLY, "").strip()
    image_title = target_row.get(COL_IMG_TITLE, "").strip()
    alt_text    = target_row.get(COL_ALT, "").strip()

    print(f"  対象カテゴリ : {category}")
    print(f"  文字数       : {len(text)}字")
    print(f"  冒頭30字     : {text[:30]}...")
    print(f"  画像タイトル : {image_title if image_title else '(なし)'}")
    print("-" * 55)

    # 画像生成と投稿
    use_image = (
        image_title
        and os.path.exists(BASE_IMAGE)
        and os.path.exists(FONT_PATH)
    )

    if use_image:
        print("  OGP 画像を生成中...")
        try:
            generate_image_with_text(BASE_IMAGE, image_title, TEMP_IMAGE)
            result = post_tweet_with_image(text, TEMP_IMAGE, alt_text)
        except Exception as e:
            print(f"  [WARN] 画像生成・アップロードに失敗しました: {e}")
            print("  -> テキストのみで投稿します...")
            result = post_tweet_text_only(text)
        finally:
            if os.path.exists(TEMP_IMAGE):
                os.remove(TEMP_IMAGE)
                print(f"  [DEL] 一時画像を削除: {TEMP_IMAGE}")
    else:
        if not image_title:
            print("  画像タイトルがないためテキストのみで投稿します。")
        elif not os.path.exists(BASE_IMAGE):
            print(f"  [WARN] {BASE_IMAGE} が見つかりません。テキストのみで投稿します。")
        result = post_tweet_text_only(text)

    if not result["success"]:
        print(f"  [ERROR] 投稿に失敗しました。ステータスを『エラー』にしてスキップします。")
        # 失敗した理由をステータスに書き込んで上書き保存
        target_row[COL_STATUS] = f"エラー: {result['error']}"
        save_csv(rows)
        return False, str(result["error"])

    posted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # リプライ文があればツリー投稿
    if reply_text:
        print(f"  リプライ文を検出 ({len(reply_text)}字) -> ツリー投稿を実行します...")
        reply_result = post_reply(reply_text, result["tweet_id"])
        if reply_result["success"]:
            print("  [OK] リプライ投稿成功")
        else:
            print(f"  [WARN] リプライ投稿に失敗しました（本編は投稿済み）: {reply_result['error']}")

    # 投稿済み行を履歴 CSV に追記し draft から削除
    append_history(target_row, posted_at)
    del rows[target_idx]
    save_csv(rows)
    print(f"  [OK] {HISTORY_CSV} に移動し、{DRAFT_CSV} から削除しました。")

    return True, f"[{category}] {len(text)}字 tweet_id={result['tweet_id']}"


# ──────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────

def main():
    print("=" * 55)
    print("  X 自動投稿スクリプト（OGP画像付き）")
    print("=" * 55)

    rows = load_csv()
    target_idx, target_row = find_target(rows)

    if target_row is None:
        print("投稿対象の原稿がありません。ストックを補充してください。")
        sys.exit(0)

    success, message = execute_single_post(rows, target_idx, target_row)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
