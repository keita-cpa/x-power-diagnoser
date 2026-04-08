"""
1回限りのCSV移行スクリプト
stock_posts_draft.csv に「画像タイトル」「ALT」列を追加し、
Gemini API で各行の投稿文からタイトルとALTを自動生成して埋め込む。
"""

from pathlib import Path

import pandas as pd
from google import genai
from google.genai import types
from config import GEMINI_API_KEY

CSV_PATH = str(Path(__file__).parent.parent / "data" / "drafts" / "stock_posts_draft.csv")
MODEL_NAME = "gemini-3.1-pro-preview"

SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",         threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT",  threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT",  threshold="BLOCK_NONE"),
]

client = genai.Client(api_key=GEMINI_API_KEY)


def generate_title_and_alt(post_text: str) -> tuple[str, str]:
    prompt = f"""以下の投稿文をもとに、SNS投稿に添付する画像のメタ情報を2つだけ生成してください。

【投稿文】
{post_text[:800]}

【出力ルール（絶対厳守）】
・1行目：「タイトル：」に続けて、15文字以内のキャッチーな画像タイトルを出力すること。
・2行目：「ALT：」に続けて、LLMO（大規模言語モデル最適化）対策を意識した、投稿内容を的確に要約した100文字程度のALTテキストを出力すること。
・上記2行のみを出力すること。それ以外の説明・コメント・空行は一切出力禁止。

出力例：
タイトル：税務調査から身を守る
ALT：メンエスセラピストが税務調査で「指摘されない」ための記帳方法と経費処理の実態を、所得税法と実際の裁決事例をもとに公認会計士が解説。正しい申告で安心を手に入れよう。"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            safety_settings=SAFETY_SETTINGS,
        ),
    )

    raw = (response.text or "").strip()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    title = ""
    alt = ""
    for line in lines:
        if line.startswith("タイトル：") or line.startswith("タイトル:"):
            title = line.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif line.startswith("ALT：") or line.startswith("ALT:"):
            alt = line.split("：", 1)[-1].split(":", 1)[-1].strip()

    return title, alt


def main():
    print("=== CSV移行スクリプト起動 ===")
    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    print(f"読み込み完了: {len(df)}行 / 列: {list(df.columns)}")

    # 列追加（未存在の場合のみ）
    if "画像タイトル" not in df.columns:
        df["画像タイトル"] = ""
        print("→ 「画像タイトル」列を追加しました")
    if "ALT" not in df.columns:
        df["ALT"] = ""
        print("→ 「ALT」列を追加しました")

    print(f"\n処理対象: {len(df)}行\n")

    for i, row in df.iterrows():
        post_text = str(row.get("投稿文", ""))
        existing_title = str(row.get("画像タイトル", "")).strip()
        existing_alt = str(row.get("ALT", "")).strip()

        # すでに両方埋まっている行はスキップ（エラーや未設定は再生成）
        skip_values = {"", "nan", "エラー"}
        if existing_title not in skip_values and existing_alt not in skip_values:
            print(f"[{i+1:2d}/{len(df)}] スキップ（生成済み）: {existing_title}")
            continue

        if not post_text or post_text == "nan":
            print(f"[{i+1:2d}/{len(df)}] スキップ（投稿文なし）")
            continue

        try:
            title, alt = generate_title_and_alt(post_text)
            df.at[i, "画像タイトル"] = title
            df.at[i, "ALT"] = alt
            print(f"[{i+1:2d}/{len(df)}] 生成完了")
            print(f"         タイトル: {title}")
            print(f"         ALT({len(alt)}字): {alt[:60]}...")
        except Exception as e:
            print(f"[{i+1:2d}/{len(df)}] エラー: {e}")
            df.at[i, "画像タイトル"] = "エラー"
            df.at[i, "ALT"] = "エラー"

    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    print(f"\n=== 完了: {CSV_PATH} に上書き保存しました ===")
    print(f"最終列構成（{len(df.columns)}列）: {list(df.columns)}")


if __name__ == "__main__":
    main()
