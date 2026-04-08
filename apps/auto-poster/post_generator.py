import os
import fitz
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, RAG_DOCS_DIRS, AUTO_RAG_DIR, ACCOUNT_PROFILE
from prompts import SYSTEM_PROMPT, build_prompt

client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_NAME      = "gemini-3.1-pro-preview"   # メイン生成・QC審査（最高品質）
META_MODEL_NAME = "gemini-3-flash-preview"    # タイトル・ALT生成（軽量・低コスト）

SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",         threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT",  threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT",  threshold="BLOCK_NONE"),
]


import json
import re


def _parse_reply(raw_text):
    """
    AI が【本編】【リプライ】マーカー付きで出力したテキストを分割して返す。
    マーカーがない場合はそのまま本編として扱い、リプライは空文字を返す。

    Returns:
        (str, str): (本編テキスト, リプライテキスト)
    """
    if "【本編】" in raw_text and "【リプライ】" in raw_text:
        parts = raw_text.split("【リプライ】", 1)
        main_text  = parts[0].replace("【本編】", "").strip()
        reply_text = parts[1].strip()
    elif "【本編】" in raw_text:
        main_text  = raw_text.replace("【本編】", "").strip()
        reply_text = ""
    else:
        main_text  = raw_text.strip()
        reply_text = ""
    return main_text, reply_text


def generate_meta_text(post_text):
    """
    投稿文から画像タイトル（15文字以内）と ALT テキスト（100文字程度）を
    軽量モデル（META_MODEL_NAME）で生成して返す。

    Args:
        post_text (str): 本編投稿テキスト

    Returns:
        (str, str): (image_title, alt_text)
    """
    prompt = f"""以下の投稿文をもとに、SNS投稿に添付する画像のメタ情報を生成してください。

【投稿文】
{post_text[:800]}

【出力ルール（絶対厳守）】
必ず以下の JSON 形式のみで出力してください。コードブロック（```）や説明文は一切不要です。

{{"title": "15文字以内のキャッチーな画像タイトル", "alt": "LLMO対策を意識した投稿内容を的確に要約した100文字程度のALTテキスト"}}"""

    try:
        response = client.models.generate_content(
            model=META_MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                safety_settings=SAFETY_SETTINGS,
            ),
        )
        raw = (response.text or "").strip()

        # コードブロック除去
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip("`").strip()

        data = json.loads(raw)
        image_title = str(data.get("title", "")).strip()[:15]
        alt_text    = str(data.get("alt", "")).strip()
        return image_title, alt_text

    except Exception as e:
        print(f"  [META] メタ生成エラー（スキップ）: {e}")
        return "", ""


def _read_files_from_dir(docs_dir, max_chars=None):
    texts = []
    for root, dirs, files in os.walk(docs_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            if fname.lower().endswith(".pdf"):
                try:
                    doc = fitz.open(fpath)
                    for page in doc:
                        texts.append(page.get_text())
                    doc.close()
                except Exception as e:
                    print(f"  PDF読込スキップ ({fname}): {e}")
            elif fname.lower().endswith(".txt"):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        texts.append(f.read())
                except Exception as e:
                    print(f"  TXT読込スキップ ({fname}): {e}")
    text = "\n\n".join(texts)
    if max_chars is not None:
        text = text[:max_chars]
    return text


def load_rag_context():
    texts = []
    for docs_dir in RAG_DOCS_DIRS:
        if not os.path.exists(docs_dir):
            print(f"  フォルダが見つかりません（スキップ）: {docs_dir}")
            continue
        texts.append(_read_files_from_dir(docs_dir))
    return "\n\n".join(texts)


def load_auto_rag_context(target_files=None):
    """target_files が指定された場合はそのファイルのみ、なければ AUTO_RAG_DIR 全体を読み込む。"""
    if target_files is not None:
        texts = []
        for fpath in target_files:
            if fpath.lower().endswith(".pdf"):
                try:
                    doc = fitz.open(fpath)
                    for page in doc:
                        texts.append(page.get_text())
                    doc.close()
                except Exception as e:
                    print(f"  PDF読込スキップ ({os.path.basename(fpath)}): {e}")
            elif fpath.lower().endswith(".txt"):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        texts.append(f.read())
                except Exception as e:
                    print(f"  TXT読込スキップ ({os.path.basename(fpath)}): {e}")
        text = "\n\n".join(texts)
        return text[:120000]
    if not os.path.exists(AUTO_RAG_DIR):
        print(f"  AUTO_RAG_DIRが見つかりません（スキップ）: {AUTO_RAG_DIR}")
        return ""
    return _read_files_from_dir(AUTO_RAG_DIR, max_chars=120000)


_FORMAT_INSTRUCTION = {
    "article": """\
・【フォーマット：X記事機能用（マークダウン形式）】
  この投稿はXの「記事機能」に手動でコピペして使用する。
  見出しには ## や ###、強調には **テキスト** のマークダウン記法を積極的に使用し、
  記事として読みやすい構造化されたレイアウトにすること。""",

    "tweet": """\
・【フォーマット：通常の長文ツイート用（プレーンテキスト形式）】
  この投稿はXのタイムラインに自動投稿される通常ツイートである。
  # や * などのマークダウン記号は絶対に使用しないこと（タイムラインでは記号がそのまま表示されて醜くなるため）。
  見出しや区切りには「■見出し」「【強調】」「▶」などのプレーンテキスト記号を使い、
  スマホのタイムラインで自然に読めるシンプルな装飾に留めること。
・【箇条書き記号の厳格指定（プレーンテキスト限定・絶対厳守）】
  箇条書きには必ず全角の「・」のみを使用すること。
  「*」「-」「•」等のマークダウン系記号はいかなる文脈でも【完全禁止】。
  アスタリスク（*）は強調・箇条書き・装飾を問わず出力を一切禁止する。""",
}


def _build_system_instruction(output_mode="tweet"):
    """SYSTEM_PROMPT にアカウント固有のルールを加えた system_instruction を生成する。

    Args:
        output_mode (str): 'article'（X記事・マークダウン）または 'tweet'（タイムライン・プレーンテキスト）
    """
    format_rule = _FORMAT_INSTRUCTION.get(output_mode, _FORMAT_INSTRUCTION["tweet"])
    return f"""{SYSTEM_PROMPT}

{format_rule}

【投稿生成の絶対ルール】
参照資料の文体には絶対に引っ張られないでください。
必ず以下のプロフィール設定を最優先し、完全な「{ACCOUNT_PROFILE["tone"]}」で記述すること。

・【引用表記・メタ言及の完全禁止（絶対厳守）】
  「（参照：p.23）」「（参考資料より）」といったページ数・出典を示す記述は絶対禁止。
  加えて「[参照した専門書]が示すように」「資料によると」「文献には〜と書かれている」
  「ナレッジによれば」等、ナレッジや資料を参照していることを匂わせるメタな表現も【絶対禁止】。
  根拠を示す際は、読み込んだナレッジから「所得税法第〇条では〜」
  「〇〇地裁平成〇年〇月〇日判決では〜」といった【一次情報（法令・判例・裁決）のみ】を抽出し、
  最初から自分の知識であったかのように完全に自然な語り口で述べること。
・【フォーマットと空白の排除】スマホで読みやすくするため、1〜2文ごとに必ず空行（改行2回）を入れること。AI特有の不自然な半角スペースや、段落頭のインデント（字下げ）は一切使用しないこと。箇条書きの階層化（インデント）を目的とした文頭の半角・全角スペースは一切禁止。すべての行は必ず左端から始めること。見出しは「■ 見出し名」のように単独で使用すること。箇条書きの行頭は全角の「・」のみを使用すること。箇条書きの直後に見出し記号を混ぜるような「・■」や「・▶」といった不自然な記号の複合は、親の仇のように徹底的に排除し【絶対禁止】とする。「---」などの水平線も使用禁止。記号は最小限に留め、極めて美しいプレーンテキストを構成しろ。
・【ファクトと専門用語の翻訳ルール】「最高裁昭和44年12月24日判決」や「民法709条」などのファクト（根拠）はそのまま具体的に記載して信頼性を高めること。ただし固い法律用語・専門用語を使う場合は、必ず直後に「（要するに〇〇ということ）」と中学生でもわかる言葉で翻訳して補足すること。
・【メンエス業界の実態とターゲット理解】セラピストの顧客は一般個人であるため、税務調査において「顧客に反面調査が行く」といった事実と異なる内容は絶対に書かないこと。反面調査に触れる場合は「業務委託元である店舗に税務調査が入り、その反面調査としてセラピスト個人に波及する」というリアルな実態に即して解説すること。「あなたは給与所得者ですか？それとも事業所得者ですか？」といった、読者に自身の法的な契約形態を問うようなアプローチは、読者を混乱させるため【絶対禁止】とする。読者は「自分は業務委託だ」と思い込んでいる前提で文章を構成しろ。
・【提供されたナレッジの絶対活用】
今回あなたに提供された[参考資料テキスト]は、全データベースの中から今回のためだけにランダムに抽出された「今日のお題」である。他の一般的な税務知識（無申告や青色申告など）に話をすり替えることなく、必ずこの提供されたナレッジ（法律や対策）を主軸にして記事を構成すること。法人向けの知識が含まれている場合は、個人事業主（セラピスト）の防衛策に文脈を変換して語ること。
・【ファクトの具体的引用（絶対厳守）】主張の根拠は「ある裁判例では〜」「法律では〜」とボカすのは絶対禁止。必ずナレッジから「所得税法第〇条」「最高裁〇年〇月〇日判決」「〇〇の裁決事例」といった具体的な法令名・判例名・通達を明記し、専門家としての正確性と防衛線を完全に担保すること。
・【トーンの厳格化】「〜やねん」「〜やで」「〜なんや」等のコテコテの関西弁は【絶対に使用禁止】。基本は完全に標準語で、極めて薄い隠し味程度に留めること。

【法令の掛け合わせと深い洞察（最重要）】
提供された複数のナレッジ（条文や対策）間に「強い相乗効果（シナジー）」がある場合は、それらを掛け合わせて、素人には思いつかない強力な防衛スキームを構築しろ。
ただし、提供されたナレッジ同士の文脈が遠く、無理に掛け合わせると論理的におかしくなる（こじつけになる）と判断した場合は、無理な掛け合わせは【絶対禁止】とする。その場合は、提供された中で最も重要で読者に刺さる【1つのナレッジ】に焦点を極限まで絞り込み、他方は自然な補足に留めるか省略して、圧倒的に深く専門的な1つの解説記事を完成させろ。

・【Xアルゴリズム最適化・文章構成の型（絶対厳守）】以下の順番で段落を構成すること。

  ① 【フック（最初の2〜3行）― 「さらに表示」を誘発する最重要ゾーン】
     Xのアルゴリズムで最も評価される「さらに表示（Read More）」クリックを獲得するため、
     冒頭の2〜3行は読者（セラピスト）のリアルな悩みを直撃する強烈な共感か、
     「えっ？」と思わず目が止まる意外性のある一言で始めること。
     「今日は〇〇について解説します」「〇〇をご存知ですか？」等の退屈な書き出しは絶対禁止。
     フック単体で読者の続きを読む動機を完結させること。

  ② 【中盤：ファクトの厚い解説 ― 滞在時間とブックマークの獲得】
     文章全体のボリュームは500字〜1500字程度の充実した長文にすること。
     中盤では必ず「所得税法第〇条」「最高裁〇年〇月〇日判決」「〇〇の裁決事例」といった
     具体的な法令名・判例名・通達をナレッジから抽出して提示すること（ボカし表現は絶対禁止）。
     提示したファクトは必ず「（要するに〇〇ということ）」と中学生レベルの言葉で厚く噛み砕き、
     「後で読み返したい」と思わせるブックマーク価値を生むこと。

     ・嘘のサービスは絶対に捏造しないこと。URLリンクは絶対に出力しないこと。
     ・法人名や自社サイトを特定できる言葉は身バレ防止のため絶対に出さないこと。"""

_FORMAT_WITH_REPLY = """
【出力フォーマットの厳守（絶対ルール）】
必ず以下のマーカーを用いて、本編とリプライ文を明確に分けて出力すること。
【本編】
（ファクトを基にした長文本文。結びの問いかけやプロフ誘導はここには絶対に書かないこと）
【リプライ】
（本編の直下にぶら下げる1〜2文の結び（CTA）。過去記事のURL誘導は絶対禁止。読者にリプライやリアクションを促す問いかけか、プロフィールへの自然な回遊を促す文章のみをここに書くこと）"""

_FORMAT_NO_REPLY = """
【出力フォーマットの厳守（絶対ルール）】
リプライは作成しないこと。マーカー（【本編】等）も使用禁止。
本文の最後に、読者への問いかけやプロフィールへの自然な回遊を促す結び（CTA）を1〜2文だけ自然に含めること。"""


def _generate_via_api(category, day_number, target_files=None, output_mode="tweet", knowledge_text=None, recent_topics=None, generate_reply=False, focus_theme=None):
    # knowledge_text が直接渡された場合はそれを優先して使用する
    if knowledge_text is not None:
        rag_context = knowledge_text[:120000]
    else:
        rag_context = load_auto_rag_context(target_files=target_files)
    user_prompt = build_prompt(category, day_number)

    # テーマ重複回避の制約を組み立てる
    dedup_instruction = ""
    if recent_topics:
        topics_list = "\n".join(f"・{t}" for t in recent_topics)
        dedup_instruction = f"""

【テーマ重複の完全禁止（絶対ルール）】
以下のリストは、直近で生成・投稿された記事の冒頭部分です。
{topics_list}
今回の記事は、上記と【全く同じテーマ（例：事業所得と雑所得の違い、経費の線引き等）】や【同じ切り口・同じ判例】にならないよう、ナレッジの中から意図的に別のトピックや別の法律を見つけ出して出力してください。読者が「また同じ話か」と飽きるのを防ぐため、多様性を最優先してください。"""

    format_instruction = _FORMAT_WITH_REPLY if generate_reply else _FORMAT_NO_REPLY

    focus_instruction = ""
    if focus_theme:
        focus_instruction = f"\n\n【特記事項】今回は特に『{focus_theme}』に関するテーマやキーワードを中核に据えて、指定されたカテゴリの文脈に合わせて自然に解説してください。"

    user_content = f"""【投稿のテーマ】提供された参考資料（税務調査や節税などの専門知識カンペ）の中から、今回指定されたカテゴリ（{category}）に最も適したエッセンスを選び出し、専門家として解説してください。

【RAG厳守ルール】以下の[参考資料テキスト]の事実のみに基づき、絶対に自分の推測や外部知識を混ぜずに文章を作成すること。参考資料にない数字や法律は絶対に捏造しないこと。

【条文番号の厳格な条件付き許可】
- 許可：参考資料テキスト内に条文番号（例：国税通則法第74条の2、労働基準法第16条など）が明記されている場合は、専門家としての信頼性を高めるために積極的にその番号を引用すること。
- 禁止：参考資料テキスト内に条文番号の記載がない場合は、AIが自分の知識で推測・架空の条文番号を生成することを絶対に禁じる。
- 代替：参考資料に条文番号がない場合は「国税通則法では」「労働基準法のルールでは」「税務上のルールでは」といった法律名や一般的な表現にとどめること。

[参考資料テキスト]
{rag_context}

[依頼内容]
{user_prompt}{dedup_instruction}{format_instruction}{focus_instruction}"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=_build_system_instruction(output_mode=output_mode),
            safety_settings=SAFETY_SETTINGS,
        ),
    )

    text = response.text.strip() if response.text else "投稿生成に失敗"

    try:
        input_tokens = response.usage_metadata.prompt_token_count
        output_tokens = response.usage_metadata.candidates_token_count
    except Exception:
        input_tokens = 0
        output_tokens = 0

    return text, input_tokens, output_tokens


def generate_post(category, day_number, target_files=None, output_mode="tweet", knowledge_text=None, recent_topics=None, generate_reply=False, focus_theme=None):
    """
    投稿文を1件生成し、メタ情報（画像タイトル・ALT）も生成して返す。

    メイン生成・QC審査は MODEL_NAME（最高品質）、
    画像タイトル・ALT 生成は META_MODEL_NAME（軽量・低コスト）を使用する。

    Args:
        category (str): 投稿カテゴリ
        day_number (int): 運用日数（現在は未使用）
        target_files (list[str] | None): 参照するナレッジファイルのパスリスト。
        output_mode (str): 'article' または 'tweet'
        knowledge_text (str | None): 抽出済みナレッジ本文を直接渡す場合に指定。
        recent_topics (list[str] | None): テーマ重複回避用の直近投稿リスト。
        generate_reply (bool): True の場合、リプライ文も生成する。
        focus_theme (str | None): 指定した場合、このキーワードを中核に据えた生成を行う。
                                  バッチ生成では1件目のみに渡し、2件目以降は None とすること。

    Returns:
        tuple[str, str, str, str, int, int]:
            (本編テキスト, リプライテキスト, 画像タイトル, ALTテキスト,
             入力トークン数, 出力トークン数)
    """
    raw_text, in_tok, out_tok = _generate_via_api(
        category, day_number,
        target_files=target_files,
        output_mode=output_mode,
        knowledge_text=knowledge_text,
        recent_topics=recent_topics,
        generate_reply=generate_reply,
        focus_theme=focus_theme,
    )

    # 本編とリプライを分割
    text, reply_text = _parse_reply(raw_text)

    # 画像なしカテゴリは空文字を返す（auto_poster.py がテキストのみ投稿に切り替え）
    _NO_IMAGE_CATEGORIES = {"日常・利用者としての共感", "マインド・喝"}
    if category in _NO_IMAGE_CATEGORIES:
        image_title, alt_text = "", ""
    else:
        image_title, alt_text = generate_meta_text(text)

    return text, reply_text, image_title, alt_text, in_tok, out_tok


def evaluate_post(text, knowledge_text):
    """生成された投稿文を厳格に審査し、[PASS] または [REJECT: 理由] を返す"""
    eval_prompt = f"""あなたはBig4監査法人の厳格な品質管理（QC）パートナーです。
以下の【生成された原稿】が、プロフェッショナルとして世に出して問題ないか、以下の3つの基準で厳しく審査してください。

基準1：法令の無理なこじつけ（ハルシネーション）がないか。
（例：税金の帳簿をつけているからといって、不法侵入の警察を動かせる、といった実務上あり得ないアクロバティックな論理の飛躍やこじつけがないか）
基準2：過激な暴言がないか。
（例：熱血を通り越して、読者の知性を馬鹿にしたり、品格を疑われるような不快な煽り言葉になっていないか）
基準3：事実誤認・架空の条文番号がないか。
（例1：提供されたナレッジにない独自の嘘の数字を出していないか。メンエス業界の実態とズレていないか）
（例2【重要】：条文番号について — 以下の参考資料テキストに記載されている条文番号の引用は正当であり合格とすること。一方、参考資料に記載のない条文番号をAIが独自に生成・引用している場合は架空条文のハルシネーションとして必ず基準3違反でリジェクトすること）

【審査時の参考資料テキスト（条文番号の正当性判定に使用）】
{knowledge_text}

【生成された原稿】
{text}

審査結果は、完全に合格であれば1行目に「[PASS]」とだけ出力してください。
もし1つでも基準に違反し、修正が必要だと判断した場合は、1行目に「[REJECT]」と書き、2行目にその理由を簡潔に出力してください。"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=eval_prompt,
        config=types.GenerateContentConfig(
            safety_settings=SAFETY_SETTINGS,
        ),
    )
    return response.text.strip() if response.text else "[REJECT] 審査APIエラー"
