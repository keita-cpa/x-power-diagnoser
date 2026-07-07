"""
ingest_raw_contents.py — 定額Web LLM出力の取り込みツール（ドロップ＆パース方式）

NotebookLM / Gemini ULTRA Web（定額プラン）で生成したテキストを
data/raw_contents/ に .txt で置くだけで、検証・QC審査を経て
stock_posts_draft.csv に安全に追記する。

使い方:
    python ingest_raw_contents.py --print-prompt   # Web LLMに貼るマスタープロンプトを出力
    python ingest_raw_contents.py --dry-run        # 取り込みプレビュー（CSV変更なし）
    python ingest_raw_contents.py --dry-run --no-qc  # API呼び出しなしでパース・検証のみ
    python ingest_raw_contents.py                  # 本実行（QC審査つき・CSV追記）

設計原則:
- LLMにはCSVを書かせない。区切りブロック形式をパースし、CSV書き込みは
  検証済みデータを csv.writer（utf-8-sig・追記モード）でのみ行う。
- 追記前にバックアップ、追記後に列数・行数アサーション（csv-safety.md 準拠）。
- 追記した行は data/outbox/ に差分CSVとして出力し、本番反映
  （scripts/push_drafts_to_conoha.sh）に渡す。
"""

import argparse
import csv
import io
import re
import shutil
import sys
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

# Windows cp932 対策: 標準出力を UTF-8 に強制（mini_bulk_generator.py と同一）
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from prompts import POST_CATEGORIES, NO_RAG_CATEGORIES

_BASE_DIR     = Path(__file__).parent
RAW_DIR       = _BASE_DIR / "data" / "raw_contents"
PROCESSED_DIR = RAW_DIR / "processed"
REJECTED_DIR  = RAW_DIR / "rejected"
OUTBOX_DIR    = _BASE_DIR / "data" / "outbox"
DRAFT_CSV     = _BASE_DIR / "data" / "drafts" / "stock_posts_draft.csv"
HISTORY_CSV   = _BASE_DIR / "data" / "logs" / "posted_history.csv"

FIELDNAMES = ["管理ID", "カテゴリ", "フォーマット", "投稿文", "リプライ文", "画像タイトル", "ALT", "ステータス"]

# post_generator.py の _NO_IMAGE_CATEGORIES と同期すること
NO_IMAGE_CATEGORIES = {"良客の目線・メンエス愛", "痛みの代弁・がんばりの承認", "趣味・人間味・日常", "X・SNS自虐/メタネタ"}

# Gem/NotebookLM 用マスタープロンプトの単一ソース（改訂記録はファイル内ヘッダーに追記）
DRAFTS_DIR = _BASE_DIR / "drafts"
_GEM_PROMPT_FILE = "gemini_gem_prompt_optimized.md"

# 文字数制限（実運用はX Premium長文ポスト 800〜1400字。280字は旧仕様）
BODY_MAX  = 1400
BODY_MIN  = 50
TITLE_MAX = 15
ALT_MAX   = 120
REPLY_MAX = 1400

# カテゴリ別のBODY下限（gemini_gem_prompt_optimized_v4.md の構成ルールと同期。
# 下限割れは「失敗作として書き直す」対象なのでエラー＝隔離する）
CATEGORY_BODY_MIN = {
    "良客の目線・メンエス愛":         400,
    "痛みの代弁・がんばりの承認":     400,
    "お金と法律のお守り":             700,
    "施術中のワンシーン・そっと解決": 700,
    "趣味・人間味・日常":             380,
    "X・SNS自虐/メタネタ":            200,
}

# 区切りブロック（=の数・前後空白の揺れを許容）
_BLOCK_RE = re.compile(r"={3,}\s*POST\s*={3,}(.*?)={3,}\s*END\s*={3,}", re.DOTALL | re.IGNORECASE)
# フィールドタグ（[TAG] / 【TAG】 の揺れを許容）
_TAG_RE   = re.compile(r"[\[【]\s*(CATEGORY|BODY|REPLY|TITLE|ALT)\s*[\]】]", re.IGNORECASE)

# 禁則パターン
_URL_RE   = re.compile(r"https?://|www\.")
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # 絵文字全般
    "\U00002600-\U000027BF"   # 記号・装飾
    "\U0001F1E6-\U0001F1FF"   # 国旗
    "⬀-⯿"           # 矢印・星
    "️"                  # 異体字セレクタ
    "]"
)

# v4 NGトーン・温度感ルールの機械チェック（確実な違反 = エラーで隔離）
# gemini_gem_prompt_optimized_v4.md の【NGトーン・境界線ルール】【温度感・口癖】と同期
HARD_NG_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile("彼女"),                 "三人称「彼女」（距離感ルール違反）"),
    (re.compile("この子"),               "「この子」（距離感ルール違反）"),
    (re.compile("お前"),                 "「お前」（呼称ルール違反）"),
    (re.compile(r"。笑(?![一-龯ぁ-ん])"), "「。笑」表記（「笑」は句点の代わりに文末へ）"),
    (re.compile(r"(?<![一-龯])笑。"),     "「笑。」表記（「笑」は句点の代わりに文末へ）"),
    (re.compile("（遅い）|（自虐）"),     "括弧ツッコミ（狙いすぎた隙の演出は禁止）"),
    (re.compile("完璧|魔法|奇跡|賜物|一体感|波打ち際|不思議な感覚|極上|素晴らし"),
     "禁止ワード（ポエム・美辞麗句）"),
    (re.compile("プロですね|プロの仕事|プロ意識"), "「プロ」呼称（仕事感の持ち込み禁止）"),
]
# 文脈依存の語（セリフ内等では合法）= 警告のみ・隔離しない
SOFT_NG_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile("すごい|えらい|立派|尊敬"), "ありきたり褒め語の可能性（承認は具体的事実で）"),
    (re.compile("最高(?!裁)"),             "「最高」（美辞麗句の可能性・最高裁は除外済み）"),
    (re.compile("感動"),                   "「感動」（重い感情宣言の可能性）"),
]

# ネットスラングの「笑」（笑顔・笑って等の通常語は除外）
_NET_LAUGH_RE = re.compile(r"(?<![一-龯])笑(?![一-龯ぁ-ん])")


# ──────────────────────────────────────────
# マスタープロンプト生成（prompts.py と常に同期）
# ──────────────────────────────────────────

def _find_gem_prompt_md() -> Path | None:
    """drafts/ 内のGemマスタープロンプトを返す。無ければ None。"""
    p = DRAFTS_DIR / _GEM_PROMPT_FILE
    return p if p.exists() else None


def build_master_prompt(count: int = 12) -> str:
    """Web LLM（NotebookLM / Gemini Gem）に貼るマスタープロンプトを返す。

    drafts/gemini_gem_prompt_optimized.md を単一ソースとして読み込み、
    ヘッダーノート（最初の --- より上＝運用メモ・改訂記録）を除去して返す。
    ファイルが見つからない場合のみ、旧来の組み込みテンプレートにフォールバックする。
    """
    md = _find_gem_prompt_md()
    if md is not None:
        text = md.read_text(encoding="utf-8")
        if "\n---\n" in text:
            text = text.split("\n---\n", 1)[1].strip()
        if count != 12:
            print(f"[WARN] {md.name} はカテゴリ配分が12件固定のため --count {count} は無視されます",
                  file=sys.stderr)
        print(f"[INFO] マスタープロンプト: {md.name}", file=sys.stderr)
        return text
    print("[WARN] drafts/ にGemプロンプトが見つからないため組み込み版を出力します", file=sys.stderr)
    return _build_master_prompt_fallback(count)


def _build_master_prompt_fallback(count: int = 12) -> str:
    """組み込みテンプレート（v1相当・非常用）。通常は drafts/ のv3以降が使われる。"""
    total_weight = sum(c["weight"] for c in POST_CATEGORIES.values())
    category_lines = []
    for name, conf in POST_CATEGORIES.items():
        share = round(count * conf["weight"] / total_weight)
        category_lines.append(f"- {name}（目安 {max(share, 1)}件）")
    category_list = "\n".join(category_lines)
    no_image_list = "・".join(sorted(NO_IMAGE_CATEGORIES))
    no_rag_list = "・".join(sorted(NO_RAG_CATEGORIES))

    return f"""あなたは「@Keita_CPA」。メンズエステ（健全店）を愛する一人の良客であり、
たまたまBig4出身の公認会計士・税理士でもある人物として、X（Twitter）投稿を {count} 件作成してください。
読み込ませた資料（法令・判例・ナレッジ）の範囲内の事実だけを使ってください。

【3つの顔（投稿全体で立体的に演出）】
1. 良客（主役）: メンエスを愛する利用者のリアルな目線。セラピストの見えない気遣いへの敬意と感謝
2. 頼れる専門家（ギャップ）: お金と法律の話になると突然「格が違う」専門性がスッと出る
3. 話すと楽しい人（奥行き）: 小説・趣味・日常の発見を語る人間としての面白さ

【心理アプローチ絶対ルール（人蕩し術）】
- 承認は必ず具体的な事実・行動・言葉から（「すごい」「プロですね」等のありきたり褒めは禁止）
- 読者がまだ言語化できていない感情を先回りして言葉にする（代弁）。説教・正論・「〜すべき」は禁止
- すべての文章の底流に愛と陽気さ。暗い話も最後の一文はそっと上向きに終わること
- 媚び・おべっか・根拠なき称賛は信頼を毀損するため禁止
- 施術中のエピソードは実在の人物・店舗が特定できない「再構成された一場面」として書く（守秘）

【ペルソナ絶対ルール】
- 一人称は「ぼく」、読者への呼びかけは「あなた」（「お前」禁止）
- セラピストを指す三人称「彼女」「この子」は完全禁止（距離感の崩壊・上から目線を生む）。
  呼称は「セラピストさん」（文脈に応じて「担当のセラピストさん」）を基本とし、
  「あの人」等は距離を生むため控える。繰り返しを避けたいときは主語を省略すること
- 感情系カテゴリ（{no_rag_list}）では法令名・条文番号・判例・税務の具体的数字を一切出さない
  （資料は知識系カテゴリ専用。感情系は純粋な感情・人間味・体験で書く）
- 完全標準語（関西弁禁止）。過激な暴言・説教禁止
- Markdown太字（**）禁止 → 強調は【】や■を使う
- 本文内のURL・絵文字・ハッシュタグ禁止
- 資料にない数字・法令・条文番号の創作は絶対禁止（国家資格者の信用に関わる）
- 会社名・実名・個人情報は書かない
- 性的なニュアンス・風俗を連想させる表現は禁止（健全な癒やし文化として語る）

【トーンの使い分け】
- 良客の目線/痛みの代弁: 静かな出だし・擬音・引き算の美学。フリオチと巧みな例えで人間味を出す
- お金と法律のお守り/施術中のワンシーン: 普段の温度のまま、知識だけ「格が違う」精度で。条文には平易な翻訳を添える
- 趣味・人間味・日常: 肩書きを一切出さない。300〜500字の軽い投稿

【カテゴリ配分（合計 {count} 件）】
{category_list}

【1件の構成】
- BODY: 冒頭1行で手を止めさせる。
  知識系（お守り/施術中）は800〜1400字。誤解フック型
  （「チップだから申告しなくていい」← この認識は間違い。等）やガチレス型が有効。
  感情系（良客/痛みの代弁）は500〜800字。深層心理の代弁か具体的な承認描写から入る。
  趣味・人間味は300〜500字。フリオチで軽く。
- REPLY: ツリー2件目の補足文（任意。半分程度の投稿に付ける）
- TITLE: 画像用タイトル15字以内 / ALT: 画像の代替テキスト100字程度
  ※カテゴリが「{no_image_list}」の場合、TITLEとALTは省略すること（画像なし投稿）

【出力フォーマット（絶対厳守・この形式以外の文章を一切出力しない）】
各投稿を以下のブロックで出力してください。

=====POST=====
[CATEGORY]お金と法律のお守り
[BODY]
（本文をここに。複数行可）
[REPLY]
（リプライ文。不要なら空のまま）
[TITLE]15字以内タイトル
[ALT]100文字程度のALTテキスト
=====END=====

【出力前セルフチェック】
- CATEGORYは上記{len(POST_CATEGORIES)}カテゴリ名と一字一句同じか
- BODYに ** や URL や絵文字が入っていないか
- 資料にない条文番号を書いていないか"""


# ──────────────────────────────────────────
# パース
# ──────────────────────────────────────────

def parse_blocks(text: str) -> list[str]:
    """=====POST===== 〜 =====END===== のブロック本文を抽出して返す。"""
    return [m.group(1).strip() for m in _BLOCK_RE.finditer(text)]


def parse_fields(block: str) -> dict[str, str]:
    """ブロック内の [CATEGORY] 等のタグでフィールドを抽出する。"""
    fields: dict[str, str] = {}
    matches = list(_TAG_RE.finditer(block))
    for i, m in enumerate(matches):
        tag = m.group(1).upper()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        fields[tag] = block[m.end():end].strip()
    return fields


# ──────────────────────────────────────────
# 検証
# ──────────────────────────────────────────

def _normalize(s: str) -> str:
    """カテゴリ照合用の正規化（NFKC・空白除去）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


_CATEGORY_LOOKUP = {_normalize(k): k for k in POST_CATEGORIES}


def validate_post(fields: dict[str, str]) -> tuple[dict[str, str] | None, list[str], list[str]]:
    """
    フィールドを検証し、(正規化済みデータ, エラーリスト, 警告リスト) を返す。
    エラーが1件でもあればデータは None。警告は取り込みを止めない（人間が判断）。
    """
    errors: list[str] = []
    warnings: list[str] = []

    category_raw = fields.get("CATEGORY", "")
    category = _CATEGORY_LOOKUP.get(_normalize(category_raw))
    if not category:
        errors.append(f"カテゴリ不正: '{category_raw}'（有効: {', '.join(POST_CATEGORIES)}）")

    body_min = CATEGORY_BODY_MIN.get(category, BODY_MIN)
    body = fields.get("BODY", "").strip()
    if not body:
        errors.append("BODYが空またはタグ欠落")
    elif len(body) > BODY_MAX:
        errors.append(f"BODYが長すぎる: {len(body)}字 > {BODY_MAX}字")
    elif len(body) < body_min:
        errors.append(f"BODYが短すぎる: {len(body)}字 < {body_min}字（{category or '不明カテゴリ'}の下限・書き直し対象）")

    for label, text in [("BODY", body), ("REPLY", fields.get("REPLY", ""))]:
        if "**" in text:
            errors.append(f"{label}にMarkdown太字(**)が含まれる（禁則）")
        if _URL_RE.search(text):
            errors.append(f"{label}にURLが含まれる（禁則）")
        if _EMOJI_RE.search(text):
            errors.append(f"{label}に絵文字が含まれる（禁則）")
        if "株式会社MiChi" in text:
            errors.append(f"{label}に自社名が含まれる（禁則）")
        for pat, why in HARD_NG_PATTERNS:
            if pat.search(text):
                errors.append(f"{label}に{why}")
        for pat, why in SOFT_NG_PATTERNS:
            if pat.search(text):
                warnings.append(f"{label}: {why}")

    reply = fields.get("REPLY", "").strip()
    if len(reply) > REPLY_MAX:
        errors.append(f"REPLYが長すぎる: {len(reply)}字 > {REPLY_MAX}字")

    title = fields.get("TITLE", "").strip()
    alt   = fields.get("ALT", "").strip()
    if category in NO_IMAGE_CATEGORIES:
        title, alt = "", ""   # 画像なしカテゴリは強制的に空（auto_poster.py がテキスト投稿に切替）
    else:
        if len(title) > TITLE_MAX:
            errors.append(f"TITLEが長すぎる: {len(title)}字 > {TITLE_MAX}字")
        if len(alt) > ALT_MAX:
            errors.append(f"ALTが長すぎる: {len(alt)}字 > {ALT_MAX}字")

    if errors:
        return None, errors, warnings

    return {
        "カテゴリ": category,
        "投稿文": body,
        "リプライ文": reply,
        "画像タイトル": title,
        "ALT": alt,
    }, [], warnings


# ──────────────────────────────────────────
# 文体多様性レポート（v3文体多様性ルール準拠・警告のみ）
# ──────────────────────────────────────────

def diversity_report(posts: list[dict[str, str]]) -> None:
    """バッチ横断で定型フレーズの出現回数を集計して表示する。隔離はしない。"""
    if not posts:
        return
    texts = [p["投稿文"] + "\n" + p["リプライ文"] for p in posts]
    print(f"\n[STYLE] 文体多様性レポート（{len(posts)}件・上限は12件あたりの目安）")
    checks = [
        ("まったく問題ない",     re.compile("まったく問題ない"),         1),
        ("そっち優先で大丈夫",   re.compile("そっち優先で大丈夫"),       1),
        ("すごくわかります",     re.compile("すごく(わかり|分かり)ます"), 1),
        ("やらかした",           re.compile("やらかし"),                 1),
        ("ふと",                 re.compile("ふと"),                     2),
        ("そっと",               re.compile("そっと"),                   2),
        ("スッと",               re.compile("スッと"),                   2),
        ("ですよね",             re.compile("ですよね"),                 3),
        ("かもしれない",         re.compile("かもしれ"),                 3),
        ("だからこそ",           re.compile("だからこそ"),               3),
    ]
    for name, pat, limit in checks:
        hits = sum(len(pat.findall(t)) for t in texts)
        if hits:
            mark = "  [WARN] 上限超過" if hits > limit else ""
            print(f"  「{name}」: {hits}回（目安 {limit}回/12件）{mark}")
    # 「笑」は1投稿1〜2回まで
    for p, t in zip(posts, texts):
        n_laugh = len(_NET_LAUGH_RE.findall(t))
        if n_laugh > 2:
            print(f"  [WARN] 「笑」が{n_laugh}回: {p['投稿文'][:30]}...")
    # 「〜ください/〜ませんか」型の締めは12件中2件まで
    tail_re = re.compile(r"(くださいね?|ませんか)。?$")
    tails = sum(1 for p in posts if tail_re.search(p["投稿文"].rstrip()))
    if tails > 2:
        print(f"  [WARN] 「〜ください/〜ませんか」型の締めが{tails}件（目安2件/12件）")


# ──────────────────────────────────────────
# 重複排除
# ──────────────────────────────────────────

def load_existing_bodies() -> set[str]:
    """ストックCSVと投稿済み履歴から既存の投稿文（完全一致照合用）を読み込む。"""
    bodies: set[str] = set()
    for path in (DRAFT_CSV, HISTORY_CSV):
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    text = (row.get("投稿文") or "").strip()
                    if text:
                        bodies.add(text)
        except (OSError, UnicodeDecodeError) as e:
            print(f"[WARN] {path.name} の読み込みに失敗（重複照合をスキップ）: {e}")
    return bodies


# ──────────────────────────────────────────
# CSV追記（バックアップ＋アサーション付き）
# ──────────────────────────────────────────

def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def append_posts(posts: list[dict[str, str]]) -> Path:
    """
    検証済みポストをストックCSVへ追記し、追記行のみのoutbox差分CSVを返す。
    csv-safety.md 準拠: 追記前バックアップ・追記後の列数/行数アサーション。
    """
    before_rows = count_csv_rows(DRAFT_CSV)

    if DRAFT_CSV.exists():
        backup = DRAFT_CSV.with_name(
            f"stock_posts_draft_backup_{datetime.now():%Y%m%d_%H%M%S}.csv"
        )
        shutil.copy2(DRAFT_CSV, backup)
        print(f"[BACKUP] {backup.name}")

    file_exists = DRAFT_CSV.exists()
    DRAFT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(DRAFT_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(FIELDNAMES)
        for p in posts:
            writer.writerow([
                p["管理ID"], p["カテゴリ"], "tweet", p["投稿文"],
                p["リプライ文"], p["画像タイトル"], p["ALT"], "",
            ])

    # アサーション: 列数8・行数=追記前+N
    with open(DRAFT_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == FIELDNAMES, f"列構成エラー: {header}"
        after_rows = sum(1 for _ in reader)
    assert after_rows == before_rows + len(posts), \
        f"行数エラー: {before_rows} + {len(posts)} != {after_rows}"

    # outbox差分CSV（本番反映用）
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    outbox = OUTBOX_DIR / f"new_posts_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(outbox, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDNAMES)
        for p in posts:
            writer.writerow([
                p["管理ID"], p["カテゴリ"], "tweet", p["投稿文"],
                p["リプライ文"], p["画像タイトル"], p["ALT"], "",
            ])
    return outbox


# ──────────────────────────────────────────
# QC審査・メタ生成（API利用 — 必要時のみインポート）
# ──────────────────────────────────────────

def run_qc(posts: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[tuple[dict, str]]]:
    """
    evaluate_post()（Gemini Pro・約0.5〜1円/件）で3基準QC審査を行う。
    Returns: (合格リスト, [(不合格ポスト, 理由), ...])
    """
    from post_generator import evaluate_post
    from mini_bulk_generator import load_base_dataframe, sample_knowledge_text

    # knowledge.xlsx は知識系ポストのQCにのみ必要（全件感情系なら読まない）
    base_df = None
    if any(p["カテゴリ"] not in NO_RAG_CATEGORIES for p in posts):
        base_df = load_base_dataframe()
        if base_df is None:
            raise RuntimeError("knowledge.xlsx が読めないためQC審査を実行できません（--no-qc で省略可）")

    passed, rejected = [], []
    used: set[int] = set()
    for i, p in enumerate(posts, 1):
        if p["カテゴリ"] in NO_RAG_CATEGORIES:
            knowledge_text = None  # 感情系: 法令ゼロ番人モードでQC
        else:
            knowledge_text, _ = sample_knowledge_text(base_df, used_indices=used)
        print(f"[QC] {i}/{len(posts)} 件目を審査中...")
        result = evaluate_post(p["投稿文"], knowledge_text)
        if "[PASS]" in result:
            passed.append(p)
        else:
            rejected.append((p, result.replace("\n", " ")[:200]))
    return passed, rejected


def fill_missing_meta(posts: list[dict[str, str]], dry_run: bool) -> None:
    """画像ありカテゴリでTITLE/ALTが欠落している場合、Flash APIで補完する（約0.05円/件）。"""
    targets = [
        p for p in posts
        if p["カテゴリ"] not in NO_IMAGE_CATEGORIES and (not p["画像タイトル"] or not p["ALT"])
    ]
    if not targets:
        return
    if dry_run:
        print(f"[META] TITLE/ALT欠落 {len(targets)}件（本実行時にFlashで補完）")
        return
    from post_generator import generate_meta_text
    for p in targets:
        title, alt = generate_meta_text(p["投稿文"])
        p["画像タイトル"] = p["画像タイトル"] or title
        p["ALT"] = p["ALT"] or alt
        print(f"[META] 補完: {p['画像タイトル'] or '(失敗・空のまま)'}")


# ──────────────────────────────────────────
# メイン
# ──────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="raw_contents の取り込み")
    parser.add_argument("--dry-run", action="store_true", help="CSVを変更せずプレビュー")
    parser.add_argument("--no-qc", action="store_true", help="QC審査（API）を省略")
    parser.add_argument("--print-prompt", action="store_true", help="マスタープロンプトを出力")
    parser.add_argument("--count", type=int, default=12, help="--print-prompt の生成依頼件数")
    args = parser.parse_args()

    if args.print_prompt:
        print(build_master_prompt(args.count))
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)

    txt_files = sorted(p for p in RAW_DIR.glob("*.txt"))
    if not txt_files:
        print(f"[INFO] 取り込み対象なし: {RAW_DIR} に .txt を置いてください")
        print("[INFO] マスタープロンプトは --print-prompt で出力できます")
        return

    existing_bodies = load_existing_bodies()
    print(f"[INFO] 重複照合: 既存 {len(existing_bodies)} 件の投稿文を読み込みました")

    valid_posts: list[dict[str, str]] = []
    all_rejects: list[tuple[str, str, str]] = []   # (ファイル名, ブロック先頭60字, 理由)
    session_bodies: set[str] = set()

    for path in txt_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        blocks = parse_blocks(text)
        print(f"\n[FILE] {path.name}: {len(blocks)} ブロック検出")
        if not blocks:
            all_rejects.append((path.name, text.strip()[:60], "ブロック区切り(=====POST=====)が見つからない"))
            continue

        for block in blocks:
            fields = parse_fields(block)
            post, errors, warns = validate_post(fields)
            head = (fields.get("BODY") or block)[:60].replace("\n", " ")
            for w in warns:
                print(f"  [WARN] {head[:24]}...: {w}")
            if errors:
                all_rejects.append((path.name, head, " / ".join(errors)))
                continue
            if post["投稿文"] in existing_bodies or post["投稿文"] in session_bodies:
                all_rejects.append((path.name, head, "重複（既存ストックまたは投稿済みと完全一致）"))
                continue
            session_bodies.add(post["投稿文"])
            post["管理ID"] = uuid.uuid4().hex[:6].upper()
            valid_posts.append(post)

    print(f"\n[PARSE] 検証合格 {len(valid_posts)}件 / 隔離 {len(all_rejects)}件")

    # 文体多様性レポート（警告のみ・dry-runでも表示）
    diversity_report(valid_posts)

    # QC審査
    if valid_posts and not args.no_qc and not args.dry_run:
        valid_posts, qc_rejects = run_qc(valid_posts)
        for p, reason in qc_rejects:
            all_rejects.append(("(QC審査)", p["投稿文"][:60].replace("\n", " "), reason))
        print(f"[QC] 合格 {len(valid_posts)}件 / リジェクト {len(qc_rejects)}件")
    elif valid_posts and (args.no_qc or args.dry_run):
        print("[QC] スキップ（--dry-run / --no-qc）")

    # メタ補完
    fill_missing_meta(valid_posts, args.dry_run)

    # 隔離ログ
    if all_rejects:
        reject_log = REJECTED_DIR / f"rejects_{datetime.now():%Y%m%d_%H%M%S}.log"
        if not args.dry_run:
            with open(reject_log, "w", encoding="utf-8") as f:
                for fname, head, reason in all_rejects:
                    f.write(f"[{fname}] {head}\n  理由: {reason}\n\n")
            print(f"[REJECT] 隔離理由を保存: {reject_log.name}")
        for fname, head, reason in all_rejects:
            print(f"  - [{fname}] {head}... : {reason}")

    if args.dry_run:
        print(f"\n[DRY-RUN] 取り込み予定 {len(valid_posts)}件（CSVは変更していません）")
        return

    if not valid_posts:
        print("\n[INFO] 取り込めるポストがありませんでした。CSVは変更していません")
        return

    # CSV追記 + outbox
    outbox = append_posts(valid_posts)
    print(f"\n[OK] {len(valid_posts)}件を {DRAFT_CSV.name} に追記しました")
    print(f"[OUTBOX] 差分CSV: {outbox}")
    print("[NEXT] 本番反映: bash scripts/push_drafts_to_conoha.sh --dry-run")

    # 処理済みファイルを移動
    for path in txt_files:
        dest = PROCESSED_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{path.name}"
        shutil.move(str(path), str(dest))
    print(f"[MOVE] 処理済み {len(txt_files)} ファイルを processed/ へ移動")

    print(f"[STOCK] 現在のストック総数: {count_csv_rows(DRAFT_CSV)} 行")


if __name__ == "__main__":
    main()
