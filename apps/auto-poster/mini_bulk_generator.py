"""
ストック投稿文 一括生成ツール（ハイブリッド版）
- Excel（knowledge.xlsx）をベース知識として必ず読み込む
- 追加でテキストファイル（.txt）を任意に結合できる
- 指定件数分の投稿文を生成し stock_posts_draft.csv に追記
- 無料枠レート制限（15 req/min）対応: 1件ごとに 60 秒待機
"""

import csv
import io
import os
import random
import sys
import time
import uuid
from pathlib import Path

# Windows cp932 対策: 標準出力を UTF-8 に強制
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd

from config import AUTO_RAG_DIR
from post_generator import generate_post, evaluate_post
from prompts import POST_CATEGORIES

_BASE_DIR     = Path(__file__).parent
DRAFT_CSV     = str(_BASE_DIR / "data/drafts/stock_posts_draft.csv")
EXCEL_FILE    = os.path.join(AUTO_RAG_DIR, "knowledge.xlsx")
SLEEP_SECONDS = 0


# ──────────────────────────────────────────
# [Excel] 読み込み・テキスト抽出
# ──────────────────────────────────────────

def load_excel_knowledge():
    """
    knowledge.xlsx を読み込んで DataFrame を返す。
    列構成: No, 重要度, カテゴリ, 関連法令, 関連法令の原文, ルールの要約, 影響と対策
    """
    if not os.path.exists(EXCEL_FILE):
        print(f"[エラー] Excelファイルが見つかりません: {EXCEL_FILE}")
        return None

    df = pd.read_excel(EXCEL_FILE, header=0)
    df.columns = ["No", "重要度", "カテゴリ", "関連法令", "関連法令の原文", "ルールの要約", "影響と対策"]

    df = df.dropna(subset=["カテゴリ", "ルールの要約"]).reset_index(drop=True)
    return df


def extract_knowledge_text_from_excel(df):
    """全行をLLMが理解しやすい構造化テキストとして結合して返す。"""
    blocks = []
    for _, row in df.iterrows():
        block = (
            f"■ 関連法令：{row['関連法令']}\n"
            f"■ 原文抜粋：{row['関連法令の原文']}\n"
            f"■ ルールの要約：{row['ルールの要約']}\n"
            f"■ セラピストへの影響・対策：{row['影響と対策']}"
        )
        blocks.append(block)
    return "\n\n".join(blocks)


def load_base_dataframe():
    """
    knowledge.xlsx を読み込んでベースの DataFrame を返す。
    ループ外で1回だけ呼び出す用。
    Returns:
        pd.DataFrame | None: 有効データの DataFrame、失敗時は None
    """
    df = load_excel_knowledge()
    if df is None:
        return None

    if len(df) == 0:
        print("[エラー] knowledge.xlsx に有効なデータがありません。")
        return None

    print(f"\nknowledge.xlsx を読み込みました（合計 {len(df)} 行）")
    return df


def load_past_topics(draft_csv: str, history_csv: str, limit: int = 40) -> list[str]:
    """
    stock_posts_draft.csv と posted_history.csv から投稿文の冒頭60字を読み込む。
    生成ループ開始前に recent_topics を初期化するために使用する。

    Args:
        draft_csv:   stock_posts_draft.csv のパス
        history_csv: posted_history.csv のパス
        limit:       読み込む最大件数（新しい順）

    Returns:
        list[str]: 投稿文の冒頭60字のリスト（新しい順、最大 limit 件）
    """
    topics: list[str] = []

    # posted_history.csv（投稿済み）
    if os.path.exists(history_csv):
        try:
            with open(history_csv, encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    text = (row.get("投稿文") or "").strip()
                    if text:
                        topics.append(text[:60])
        except Exception as e:
            print(f"[警告] posted_history.csv の読み込みに失敗: {e}")

    # stock_posts_draft.csv（ストック済み・未投稿）
    if os.path.exists(draft_csv):
        try:
            with open(draft_csv, encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    text = (row.get("投稿文") or "").strip()
                    if text:
                        topics.append(text[:60])
        except Exception as e:
            print(f"[警告] stock_posts_draft.csv の読み込みに失敗: {e}")

    # 重複除去（同一テキストが複数回入るのを防ぐ）
    seen: set[str] = set()
    unique_topics: list[str] = []
    for t in topics:
        if t not in seen:
            seen.add(t)
            unique_topics.append(t)

    # 新しい順で最大 limit 件に絞る（末尾が最新）
    return unique_topics[-limit:]


def sample_knowledge_text(base_df, extra_text="", used_indices: set | None = None):
    """
    同一カテゴリ内からサンプリングしてナレッジテキストを生成する。
    カテゴリをランダムに1つ選び、そのカテゴリ内で2〜3件を抽出することで
    文脈の近いナレッジのみを組み合わせ、こじつけ掛け合わせを防ぐ。
    ループ内で毎回呼び出す用。

    Args:
        base_df (pd.DataFrame): 全ナレッジ行を含む DataFrame
        extra_text (str): 追加テキスト資料（空文字列の場合は結合しない）
        used_indices (set | None): 今セッションで使用済みの行インデックス集合。
                                    渡すと未使用行を優先してサンプリングする。

    Returns:
        (str, str): (knowledge_text, source_label)
    """
    if used_indices is None:
        used_indices = set()

    # ① ターゲットカテゴリをランダムに1つ選択（dropna で欠損除外し毎回確実に選び直す）
    categories = base_df["カテゴリ"].dropna().unique()
    selected_category = random.choice(categories)

    # ② 選択カテゴリでフィルタリング（元の行インデックスを保持）
    filtered_df = base_df[base_df["カテゴリ"] == selected_category]

    # ③ 未使用行を優先。未使用行がなければ全行から選ぶ（全消費後のフォールバック）
    unused_df = filtered_df[~filtered_df.index.isin(used_indices)]
    pool_df = unused_df if len(unused_df) >= 2 else filtered_df

    sample_size = min(random.randint(2, 3), len(pool_df))
    df_sampled = pool_df.sample(n=sample_size)
    used_indices.update(df_sampled.index.tolist())

    knowledge_text = extract_knowledge_text_from_excel(df_sampled.reset_index(drop=True))

    if extra_text.strip():
        knowledge_text += "\n\n【追加テキスト資料】\n\n" + extra_text

    unused_note = f"（未使用優先、残 {len(unused_df)}行）" if len(unused_df) >= 2 else "（全行使用済み・再利用）"
    source_label = f"[{selected_category}] からランダム抽出 {sample_size}件 {unused_note}"
    return knowledge_text, source_label


# ──────────────────────────────────────────
# [テキスト] ファイル一覧・選択・読み込み
# ──────────────────────────────────────────

def list_knowledge_files():
    """AUTO_RAG_DIR 内の .txt ファイルをリストアップして返す。"""
    if not os.path.exists(AUTO_RAG_DIR):
        print(f"[エラー] ナレッジフォルダが見つかりません: {AUTO_RAG_DIR}")
        return []
    files = [
        os.path.join(AUTO_RAG_DIR, fname)
        for fname in sorted(os.listdir(AUTO_RAG_DIR))
        if os.path.isfile(os.path.join(AUTO_RAG_DIR, fname))
        and fname.lower().endswith(".txt")
    ]
    return files


def prompt_select_files(all_files):
    """番号入力でテキストファイルを追加選択させる（all・Enter スキップも可）。"""
    print("\n【追加テキスト資料】フォルダ内のテキストファイル:")
    for i, fpath in enumerate(all_files, 1):
        print(f"  {i}. {os.path.basename(fpath)}")

    while True:
        ans = input(
            "\n追加で読み込むテキストファイルを選択してください"
            "（番号カンマ区切り、all、または【不要な場合はそのままEnter】）: "
        ).strip()

        if ans == "":
            return []

        if ans.lower() == "all":
            return all_files

        try:
            indices  = [int(x.strip()) for x in ans.split(",") if x.strip()]
            selected = [all_files[i - 1] for i in indices if 1 <= i <= len(all_files)]
            if selected:
                return selected
            print("  有効な番号を入力してください。")
        except (ValueError, IndexError):
            print("  入力形式が正しくありません。例: 1,3  または  all")


def read_text_files(file_paths):
    """選択されたテキストファイルの内容を読み込んで結合して返す。"""
    texts = []
    for fpath in file_paths:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                texts.append(f.read())
        except Exception as e:
            print(f"  [警告] ファイル読み込みスキップ ({os.path.basename(fpath)}): {e}")
    return "\n\n".join(texts)


# ──────────────────────────────────────────
# [Excel追加] フォルダ内の追加Excelファイル選択・読み込み
# ──────────────────────────────────────────

# knowledge.xlsx と同じ列構成（マージ可能と判定するための必須列）
_REQUIRED_MERGE_COLS = {"カテゴリ", "関連法令", "関連法令の原文", "ルールの要約", "影響と対策"}
_RENAME_MAP = {
    "No": "No", "重要度": "重要度", "カテゴリ": "カテゴリ",
    "関連法令": "関連法令", "関連法令の原文": "関連法令の原文",
    "ルールの要約": "ルールの要約", "影響と対策": "影響と対策",
}


def list_extra_excel_files():
    """
    AUTO_RAG_DIR 内の .xlsx / .xls ファイルを列挙する。
    ベースの knowledge.xlsx は除外する。
    """
    if not os.path.exists(AUTO_RAG_DIR):
        return []
    base_name = os.path.basename(EXCEL_FILE).lower()
    files = [
        os.path.join(AUTO_RAG_DIR, fname)
        for fname in sorted(os.listdir(AUTO_RAG_DIR))
        if os.path.isfile(os.path.join(AUTO_RAG_DIR, fname))
        and fname.lower().endswith((".xlsx", ".xls"))
        and fname.lower() != base_name
    ]
    return files


def prompt_select_extra_excels(all_files):
    """番号入力で追加Excelファイルを選択させる（all・Enter スキップも可）。"""
    print("\n【追加Excelナレッジ】フォルダ内の追加Excelファイル:")
    for i, fpath in enumerate(all_files, 1):
        print(f"  {i}. {os.path.basename(fpath)}")

    while True:
        ans = input(
            "\n追加で読み込むExcelファイルを選択してください"
            "（番号カンマ区切り、all、または【不要な場合はそのままEnter】）: "
        ).strip()

        if ans == "":
            return []
        if ans.lower() == "all":
            return all_files
        try:
            indices  = [int(x.strip()) for x in ans.split(",") if x.strip()]
            selected = [all_files[i - 1] for i in indices if 1 <= i <= len(all_files)]
            if selected:
                return selected
            print("  有効な番号を入力してください。")
        except (ValueError, IndexError):
            print("  入力形式が正しくありません。例: 1,3  または  all")


def load_extra_excel_files(file_paths, base_df):
    """
    追加Excelファイルを読み込む。

    - knowledge.xlsx と同じ列構成（_REQUIRED_MERGE_COLS が揃っている）の場合:
        base_df にマージして返す（ランダムサンプリング・used_indices の対象になる）
    - 列構成が異なる場合:
        全セルをテキスト変換して extra_text のフォールバックとして返す

    Args:
        file_paths (list[str]): 選択された追加Excelのパスリスト
        base_df (pd.DataFrame): 現在のベース DataFrame

    Returns:
        (pd.DataFrame, str): (マージ後の base_df, フォールバック用テキスト)
    """
    fallback_texts = []

    for fpath in file_paths:
        fname = os.path.basename(fpath)
        try:
            df_extra = pd.read_excel(fpath, header=0)
        except Exception as e:
            print(f"  [警告] Excelファイル読み込みスキップ ({fname}): {e}")
            continue

        # 列名の前後スペースを除去して判定
        df_extra.columns = [str(c).strip() for c in df_extra.columns]

        if _REQUIRED_MERGE_COLS.issubset(set(df_extra.columns)):
            # ---- 同一列構成: base_df にマージ ----
            # knowledge.xlsx と同じ列順に揃える（余剰列は無視）
            merge_cols = ["No", "重要度", "カテゴリ", "関連法令", "関連法令の原文", "ルールの要約", "影響と対策"]
            for col in merge_cols:
                if col not in df_extra.columns:
                    df_extra[col] = ""
            df_extra = df_extra[merge_cols].dropna(subset=["カテゴリ", "ルールの要約"])
            df_extra = df_extra.reset_index(drop=True)
            before = len(base_df)
            base_df = pd.concat([base_df, df_extra], ignore_index=True)
            print(f"  [マージ] {fname}: {len(df_extra)} 行を追加 (合計 {len(base_df)} 行)")
        else:
            # ---- 異なる列構成: テキスト変換してフォールバック ----
            lines = []
            for _, row in df_extra.iterrows():
                row_text = " / ".join(
                    f"{col}: {val}"
                    for col, val in row.items()
                    if pd.notna(val) and str(val).strip()
                )
                if row_text:
                    lines.append(row_text)
            if lines:
                fallback_texts.append(f"【{fname} より】\n" + "\n".join(lines))
            print(f"  [テキスト変換] {fname}: 列構成が異なるためフォールバック ({len(lines)} 行)")

    return base_df, "\n\n".join(fallback_texts)


# ──────────────────────────────────────────
# [共通] フォーマット・件数・CSV保存
# ──────────────────────────────────────────

def prompt_select_output_mode():
    """出力フォーマット（article / tweet）を選択させる。"""
    print("\nどのフォーマットで生成しますか？")
    print("  [1] X記事機能用（マークダウン形式・手動コピペ前提）")
    print("  [2] 通常の長文ツイート用（プレーンテキスト・自動投稿前提）")
    while True:
        ans = input("番号を入力: ").strip()
        if ans == "1":
            return "article"
        if ans == "2":
            return "tweet"
        print("  1 または 2 を入力してください。")


def prompt_select_count():
    """生成件数を入力させる。"""
    while True:
        ans = input("何件のストックを生成しますか？（推奨: 15〜21件 ※約1週間分）: ").strip()
        try:
            count = int(ans)
            if count > 0:
                return count
            print("  1以上の数値を入力してください。")
        except ValueError:
            print("  数値を入力してください。")


def append_to_draft_csv(post_id, category, output_mode, text, reply_text="", image_title="", alt_text=""):
    """
    stock_posts_draft.csv に8列構成で追記する。
    列: 管理ID, カテゴリ, フォーマット, 投稿文, リプライ文, 画像タイトル, ALT, ステータス
    エンコーディングは utf-8-sig（Excel で文字化けしない BOM 付き UTF-8）。
    """
    file_exists = os.path.exists(DRAFT_CSV)
    with open(DRAFT_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["管理ID", "カテゴリ", "フォーマット", "投稿文", "リプライ文", "画像タイトル", "ALT", "ステータス"])
        writer.writerow([post_id, category, output_mode, text, reply_text, image_title, alt_text, ""])


# ──────────────────────────────────────────
# カテゴリスケジュール構築
# ──────────────────────────────────────────

# 6投稿に1回は必ずこのカテゴリを配置する（実データ検証: 日常・共感はAlgoScore貢献ゼロのため実効16.7%に削減）
_DAILY_SYMPATHY_CATEGORY = "日常・利用者としての共感"


def build_category_schedule(post_categories, weights, count):
    """
    count 件分のカテゴリ配列を事前構築する。

    ルール:
    - 6投稿を1グループとして扱い、各グループに必ず
      「日常・利用者としての共感」を1件含める。
    - グループ内のどの位置に配置するかはランダム（パターン化を防ぐ）。
    - 残り5枠は「日常」を除いた重み付きランダムで選択する。

    Returns:
        list[str]: length == count のカテゴリ名リスト
    """
    other_categories = [c for c in post_categories if c != _DAILY_SYMPATHY_CATEGORY]
    other_weights    = [POST_CATEGORIES[c]["weight"] for c in other_categories]

    schedule = []
    for group_start in range(0, count, 6):
        group_size = min(6, count - group_start)
        daily_pos  = random.randint(0, group_size - 1)

        other_picks = random.choices(other_categories, weights=other_weights, k=group_size - 1)
        other_iter  = iter(other_picks)

        for pos in range(group_size):
            if pos == daily_pos:
                schedule.append(_DAILY_SYMPATHY_CATEGORY)
            else:
                schedule.append(next(other_iter))

    return schedule


# ──────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────

def main():
    print("=" * 55)
    print("  ストック投稿文 一括生成ツール（ハイブリッド版）")
    print("  モデル: gemini-3.1-pro  |  有料プラン(Pay-as-you-go)適用")
    print("=" * 55)

    # ① ベース知識: Excel を全件読み込む（ループ外で1回だけ）
    base_df = load_base_dataframe()
    if base_df is None:
        print("終了します。")
        return

    # ② 追加知識: テキストファイルを任意で読み込む（ループ外で1回だけ）
    all_files      = list_knowledge_files()
    selected_files = prompt_select_files(all_files) if all_files else []

    extra_text = ""
    if selected_files:
        extra_text = read_text_files(selected_files)
        if not extra_text.strip():
            print("  [警告] 選択したテキストファイルの本文が空でした。Excelのみで続行します。")
            extra_text = ""
        else:
            print("  追加テキスト資料を読み込みました。")

    # ②-2 追加知識: フォルダ内の追加Excelファイルを任意で読み込む
    extra_xl_files = list_extra_excel_files()
    if extra_xl_files:
        selected_xls = prompt_select_extra_excels(extra_xl_files)
        if selected_xls:
            base_df, xl_fallback_text = load_extra_excel_files(selected_xls, base_df)
            if xl_fallback_text:
                extra_text = (extra_text + "\n\n" + xl_fallback_text).strip()
    else:
        print("  (追加Excelファイルなし -- knowledge.xlsx のみ使用)")

    # ③ フォーマット・件数・テーマ狙い撃ちの選択
    output_mode  = prompt_select_output_mode()
    count        = prompt_select_count()
    focus_theme  = input("特に入れたいテーマやキーワードはありますか？（空欄で完全ランダム）: ").strip()

    # ④ 生成ループ（1件ごとにナレッジをサンプリング）
    post_categories   = list(POST_CATEGORIES.keys())
    weights           = [POST_CATEGORIES[c]["weight"] for c in post_categories]
    # 4投稿に1回「日常・利用者としての共感」を確実に配置するスケジュール
    category_schedule = build_category_schedule(post_categories, weights, count)

    mode_label = "X記事（マークダウン）" if output_mode == "article" else "長文ツイート（プレーンテキスト）"
    print(f"\n--- 生成開始: {count}件 | モード: {mode_label} ---\n")
    daily_slots = [i + 1 for i, c in enumerate(category_schedule) if c == _DAILY_SYMPATHY_CATEGORY]
    print(f"  日常投稿スロット（確定）: {daily_slots}\n")

    # 過去の投稿（ストック＋投稿済み）を重複回避リストに読み込む
    HISTORY_CSV = str(_BASE_DIR / "data/logs/posted_history.csv")
    recent_topics = load_past_topics(DRAFT_CSV, HISTORY_CSV, limit=40)
    print(f"  重複回避リスト: 過去 {len(recent_topics)} 件の投稿テキストを読み込みました\n")

    # セッション内ナレッジ使用済みインデックス（同じ行の再サンプリングを抑制）
    used_knowledge_indices: set[int] = set()

    for i in range(1, count + 1):
        print(f"{i}/{count} 件目を生成中...")

        # 毎回異なるナレッジをサンプリング（使用済みインデックスを渡す）
        knowledge_text, source_label = sample_knowledge_text(base_df, extra_text, used_knowledge_indices)
        print(f"  ナレッジ: {source_label}")

        post_category  = category_schedule[i - 1]
        generate_reply = (random.random() < 0.6)
        active_focus   = focus_theme if (i == 1 and focus_theme) else None

        text, reply_text, image_title, alt_text = "", "", "", ""
        in_tok, out_tok = 0, 0
        max_retries = 3
        retry_wait  = 2

        for attempt in range(1, max_retries + 1):
            try:
                text, reply_text, image_title, alt_text, in_tok, out_tok = generate_post(
                    category=post_category,
                    day_number=i,
                    output_mode=output_mode,
                    knowledge_text=knowledge_text,
                    recent_topics=recent_topics,
                    generate_reply=generate_reply,
                    focus_theme=active_focus,
                )
                # 審査官による品質チェック（本編テキストで審査）
                eval_result = evaluate_post(text, knowledge_text)
                if "[PASS]" in eval_result:
                    print("      ✓ QC審査クリア")
                    break
                else:
                    print(f"      ⚠️ QCリジェクト（試行 {attempt}/{max_retries}）: {eval_result}")
                    if attempt < max_retries:
                        print(f"      ⏳ 修正のため再生成します...")
                        time.sleep(retry_wait)
                    else:
                        raise Exception(f"品質審査を通過できませんでした: {eval_result}")
            except Exception as e:
                if attempt < max_retries:
                    print(f"  ⚠️  APIエラー発生（試行 {attempt}/{max_retries}）: {e}")
                    print(f"  ⏳ {retry_wait}秒待機後に再試行します...")
                    time.sleep(retry_wait)
                else:
                    print(f"  ❌ {max_retries}回試行しましたが失敗しました。この件はスキップします。")
                    print(f"     エラー内容: {e}")
                    text        = f"生成エラー（{max_retries}回失敗）: {e}"
                    reply_text  = ""
                    image_title = ""
                    alt_text    = ""

        if not text or text.startswith("生成エラー"):
            print(f"  [スキップ] エラーのためCSVへの保存をスキップしました。\n")
            continue

        post_id = uuid.uuid4().hex[:6].upper()
        append_to_draft_csv(post_id, post_category, output_mode, text, reply_text, image_title, alt_text)

        # 生成成功した投稿の冒頭をテーマ重複回避リストに追加（最大20件保持）
        if text and not text.startswith("生成エラー"):
            recent_topics.append(text[:60])
            recent_topics = recent_topics[-20:]

        # API利用料（Proモデル目安: Input 187.5円/1M, Output 750.0円/1M ※1ドル150円換算）
        input_cost  = (in_tok  / 1_000_000) * 300.0
        output_cost = (out_tok / 1_000_000) * 1800.0
        total_cost  = input_cost + output_cost

        reply_label = f"{len(reply_text)}字" if reply_text else "なし"
        title_label = image_title if image_title else "（なし）"
        print(f"  → [{post_category}] 本編 {len(text)}字 / リプライ {reply_label} | {DRAFT_CSV} に追記しました")
        print(f"  🖼  画像タイトル: {title_label}")
        print(f"  📊 トークン消費: In {in_tok:,} / Out {out_tok:,}")
        print(f"  💰 API利用料目安: 約 {total_cost:.2f}円")

        if i < count:
            print(f"  ⏳ レート制限対策: {SLEEP_SECONDS}秒待機中...\n")
            time.sleep(SLEEP_SECONDS)

    print(f"\n{'=' * 55}")
    print(f"完了！ {count}件の投稿文を {DRAFT_CSV} に保存しました。")
    print(f"{'=' * 55}")


if __name__ == "__main__":
    main()
