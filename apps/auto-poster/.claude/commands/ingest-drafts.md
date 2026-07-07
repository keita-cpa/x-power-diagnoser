# /project:ingest-drafts — 定額Web LLM出力の取り込みコマンド

`data/raw_contents/` に置かれた NotebookLM / Gemini ULTRA Web の出力テキストを
パース・検証・QC審査して `stock_posts_draft.csv` に追記し、本番反映まで案内する。
（生成コスト0円・QC審査のみ約1円/件）

## Step 0: 取り込み対象の確認

```bash
cd C:/Projects/x-integrated-platform/apps/auto-poster
ls data/raw_contents/*.txt 2>/dev/null || echo "NO_FILES"
```

`NO_FILES` の場合はユーザーに案内して終了:
1. マスタープロンプトを出力して見せる: `python ingest_raw_contents.py --print-prompt`
2. 「このプロンプトを Gemini ULTRA に貼り、出力を data/raw_contents/ に .txt 保存してください」

## Step 1: dry-run でプレビュー

```bash
python ingest_raw_contents.py --dry-run --no-qc
```

取り込み予定件数と隔離予定（理由付き）を報告する。

## Step 2: 隔離予定の推敲（Claude Codeの役割 = 推敲）

隔離理由が**軽微**なもの（TITLE文字数の微超過・カテゴリ名の表記揺れ・`**`の混入等）は、
raw_contents の該当 .txt を直接修正して救済する:
- カテゴリ名は `prompts.py` の `POST_CATEGORIES` キーと一字一句合わせる
- `**強調**` → `【強調】` に置換、URL・絵文字は削除
- **本文の内容（法令・数字）は書き換えない** — 内容に疑義がある場合は救済せずユーザーに報告

修正後、Step 1 を再実行して隔離が解消されたことを確認する。

### Show More カットポイントチェック（知識系カテゴリ限定）

Xのタイムラインでは、長文投稿の冒頭**約130字**でテキストが切れ「もっと見る」が表示される。
このタップはアルゴリズムで20倍ブーストされる（全シグナル中最強）。

**対象**: `お金と法律のお守り` / `施術中のワンシーン・そっと解決` の2カテゴリのみ必須確認
（感情系・趣味系は冒頭の温度感を優先するためチェック不要）

```
# 冒頭130字を計測する簡易方法（raw_contents .txt に対して実施）
python -c "
t = open('data/raw_contents/XXX.txt', encoding='utf-8').read()
import re
posts = re.findall(r'\[BODY\](.*?)\[REPLY\]', t, re.DOTALL)
for i, p in enumerate(posts):
    body = p.strip()
    print(f'--- 投稿{i+1} 冒頭130字 ---')
    print(body[:130])
    print()
"
```

**OK パターン（未解決の緊張感で切れている）:**
- 【】フック + セリフ引用 → 「それが、どれほど危険な認識かをぼくは知っていました。」で止まる
- 予告型: 「調査官がぼくにだけ話してくれた、実際に起きた話があります。」（→ 何の話かは続きで）
- 数字型: 「追徴された金額が、ぼくが聞いた中でいちばん大きかった。」（→ いくらかは続きで）
- 反転型: 「『チップは申告しなくていい』──その認識が、大きな問題になりました。」（解決は後述）

**NG パターン（救済対象）:**
- 冒頭130字で問いと答えが完結する（「正解は〇〇です」まで書いてある）
- 感情的な結び（「ありがとーって思ってます笑」等）で130字が切れる
- 【】フックを使いながら直後の文で結論まで言い切る

**救済方法**: フックの順序を入れ替えて「著者固有情報の予告」や「未解決の疑問」が130字付近に来るよう調整する。
本文の内容・法令・数字は書き換えない（フック順序の組み換えのみ可）。

## Step 3: 本実行（QC審査つき）

```bash
python ingest_raw_contents.py
```

- QC審査（Gemini Pro・3基準）が実行される。[REJECT] は rejected/ に理由付きで隔離される
- QCリジェクトの本文修正はユーザー判断（法令精度に関わるため勝手に直さない）

## Step 4: 本番反映

ユーザーに確認を取ってから実行する:

```bash
cd C:/Projects/x-integrated-platform
bash scripts/push_drafts_to_conoha.sh --dry-run   # まずプレビュー
bash scripts/push_drafts_to_conoha.sh             # ユーザーOK後に実行（要環境変数）
```

環境変数（CONOHA_USER / CONOHA_HOST / CONOHA_DEPLOY_PATH / SSH_KEY）が未設定なら
ユーザーに `! export ...` での設定を依頼する。

## 報告フォーマット

```
[ingest-drafts 完了]
- パース: XX件（XXファイル）
- 検証隔離: XX件（理由の内訳）
- QC審査: 合格XX / リジェクトXX
- CSV追記: XX件（ストック総数 XX行）
- 本番反映: 完了 / 未実施（outboxに保留中）
```

## エラー時の対処

| エラー | 対処 |
|---|---|
| ブロック区切りが見つからない | Web LLMが形式を守っていない。`--print-prompt` の【出力フォーマット】を再度貼って再生成 |
| カテゴリ不正が多発 | マスタープロンプトのカテゴリ名と prompts.py の同期を確認 |
| `ModuleNotFoundError` | `pip install google-genai openpyxl pandas` |
| QCで全件リジェクト | knowledge.xlsx と無関係な資料で生成された可能性。NotebookLMのソース設定を確認 |
| CSV列が8列でない | `.claude/rules/csv-safety.md` の復旧手順を参照 |
