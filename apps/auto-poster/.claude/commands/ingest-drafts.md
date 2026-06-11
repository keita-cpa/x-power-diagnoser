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
1. マスタープロンプトを出力して見せる: `venv/Scripts/python ingest_raw_contents.py --print-prompt --count 12`
2. 「このプロンプトを NotebookLM / Gemini ULTRA に貼り、出力を data/raw_contents/ に .txt 保存してください」

## Step 1: dry-run でプレビュー

```bash
venv/Scripts/python ingest_raw_contents.py --dry-run --no-qc
```

取り込み予定件数と隔離予定（理由付き）を報告する。

## Step 2: 隔離予定の推敲（Claude Codeの役割 = 推敲）

隔離理由が**軽微**なもの（TITLE文字数の微超過・カテゴリ名の表記揺れ・`**`の混入等）は、
raw_contents の該当 .txt を直接修正して救済する:
- カテゴリ名は `prompts.py` の `POST_CATEGORIES` キーと一字一句合わせる
- `**強調**` → `【強調】` に置換、URL・絵文字は削除
- **本文の内容（法令・数字）は書き換えない** — 内容に疑義がある場合は救済せずユーザーに報告

修正後、Step 1 を再実行して隔離が解消されたことを確認する。

## Step 3: 本実行（QC審査つき）

```bash
venv/Scripts/python ingest_raw_contents.py
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
| `ModuleNotFoundError` | `venv/Scripts/pip install google-genai openpyxl pandas` |
| QCで全件リジェクト | knowledge.xlsx と無関係な資料で生成された可能性。NotebookLMのソース設定を確認 |
| CSV列が8列でない | `.claude/rules/csv-safety.md` の復旧手順を参照 |
