# CLAUDE.md — X自動投稿・永久機関システム

## Project
メンエスセラピスト向けX自動投稿システム（Big4品質）。
法令・判例を武器に、搾取から守る知識を自動生成・投稿し続ける「永久機関」。
アカウント: @Keita_CPA（Big4出身公認会計士・税理士）

## Quick Start（新セッション開始時）
1. このCLAUDE.mdは自動ロード済み
2. 作業内容に応じて `.claude/rules/` の該当ファイルを参照
3. 複雑な変更は必ず `PLAN.md` を先に作成（`.claude/rules/planning-with-files.md`）
4. エラー発生時は `.claude/rules/superpowers.md` の原則に従う
5. 投稿生成・prompts.py編集時は `.claude/skills/x-algorithm/SKILL.md` を参照

## Architecture Pipeline
```
knowledge.xlsx → mini_bulk_generator.py → [Gemini API] → stock_posts_draft.csv
                                                                    ↓
                                                           auto_poster.py → X（画像付き）
```
サブシステム:
- `sniper_radar.py`: VIPアカウント監視 → リプライ起案 → scouted_targets.csv
- `conoha_worker.py`: Cronベーススケジューラ（schedule.jsonで状態管理）

## File Reference
| ファイル | 役割 | 注意 |
|---|---|---|
| `post_generator.py` | Gemini API呼び出し中枢・RAG・QC審査 | |
| `mini_bulk_generator.py` | Excel→一括生成→CSV追記（対話型CLI） | |
| `auto_poster.py` | CSV取得→OGP画像生成→X投稿→履歴移動 | |
| `x_poster.py` | tweepy v2/v1ラッパー | |
| `prompts.py` | システムプロンプト・カテゴリ・トーン定義 | ペルソナv2「3つの顔」対応 v6 |
| `ingest_raw_contents.py` | 定額Web LLM出力のドロップ＆パース取り込み | 生成コスト0円・QCのみ約1円/件 |
| `drafts/gemini_gem_prompt_optimized_v3.md` | Gem/NotebookLM用マスタープロンプトの単一ソース | `--print-prompt` が最新版を自動出力 |
| `utils/merge_new_posts.py` | outbox差分のConoHa側マージ（冪等） | push_drafts_to_conoha.sh から実行 |
| `prune_dead_posts.py` | 死にポストの安全削除（毎時最大2件） | ConoHa Cron |
| `config.py` | APIキー・パス設定 | **Read/Edit 絶対禁止** |
| `sniper_radar.py` | VIPアカウント監視・リプライ起案（2モード: 法律ファクト擁護型／共感承認型） | 対象は `data/config/target_accounts.txt` で管理・`--target` で単一指定可 |
| `therapist_introducer.py` | 指定アカウントの紹介長文ポスト生成（ターミナル出力） | CSV書き込みなし |
| `conoha_worker.py` | Cronスケジューラ | |

## Slash Commands（`/project:xxx` で呼び出し）
| コマンド | 説明 |
|---|---|
| `/project:test-run` | ヘルスチェック（import確認・API疎通・CSV検証） |
| `/project:bulk-generate` | mini_bulk_generator.py を安全実行・ストック数報告 |
| `/project:sniper-run` | sniper_radar.py を実行・新規スカウト数報告 |
| `/project:introduce-therapist @username` | 指定アカウントの紹介長文ポストを生成・ターミナル出力 |
| `/project:monthly-analytics` | 月次X Analytics CSV分析→AlgoScoreレポート出力 |
| `/project:ingest-drafts` | raw_contents の取り込み→検証→QC→CSV追記→本番反映案内 |

## Specialized Agents
| エージェント | 役割 | 起動タイミング |
|---|---|---|
| `data-scientist` | CSV分析・AlgoScoreスコアリング・KPI記録 | `/project:monthly-analytics` 内部・手動分析時 |
| `growth-hacker` | prompts.py最適化・アルゴリズムハック提案 | X algorithm変更検知・分析レポート後 |

## Skills（自動参照）
| スキル | 参照タイミング |
|---|---|
| `x-algorithm` | 投稿生成・prompts.py編集・フック設計時 |
| `gemini-api` | API呼び出しコード追加・モデル変更・エラー対応時 |
| `therapist-introduction` | introduce-therapist コマンド実行時・紹介文プロンプト調整時 |

## Model Routing（詳細: `.claude/rules/model-routing.md`）
- **メイン長文生成・QC審査**: `gemini-3.1-pro-preview`
- **タイトル(15字)・ALT(100字)・リプライ生成**: `gemini-3-flash-preview`
- **監視・大量処理（将来）**: `gemini-2.5-flash-lite`

## CSV Schema（8列 — 絶対に破壊しないこと）
```
管理ID | カテゴリ | フォーマット | 投稿文 | リプライ文 | 画像タイトル | ALT | ステータス
```
- 投稿対象: `フォーマット=tweet` かつ `ステータス=空欄` の最初の1行
- エンコーディング: `utf-8-sig`（BOM付きUTF-8）
- 列変更時は `mini_bulk_generator.py` と `auto_poster.py` の `FIELDNAMES` を必ず同期

## Persona v2「3つの顔」（詳細: `.claude/rules/persona.md`）
| 顔 | トーン | カテゴリ |
|---|---|---|
| 良客（主役） | 静かな出だし・擬音・引き算の美学。具体的事実による承認 | 良客の目線・メンエス愛 / 痛みの代弁・がんばりの承認 |
| 頼れる専門家（ギャップ） | 普段は良客、知識が必要な時だけ「格が違う」精度がスッと出る | お金と法律のお守り / 施術中のワンシーン・そっと解決 |
| 話すと楽しい人（奥行き） | 肩書きゼロ。フリオチ・例えで軽く笑わせる | 趣味・人間味・日常 |

絶対ルール: 一人称「ぼく」・二人称「あなた」（「お前」禁止）・URL禁止・Markdown太字（`**`）禁止・
説教/媚び禁止・守秘フィクション化（施術中エピソードは特定不可能に再構成）・性的ニュアンス禁止

## QC審査（3基準）
1. 法令のこじつけ・ハルシネーションがないか
2. 過激な暴言（熱血と混同しない）がないか
3. 事実誤認・ナレッジ外数字の捏造がないか

## Coding Conventions
```python
# API呼び出しは必ずtry/exceptで囲む（max_retries=3 / retry_wait=2秒）
# CSV読み書きは encoding="utf-8-sig" を徹底する
# print()の絵文字はWindows cp932で文字化けするため使用禁止
# セーフティ設定 BLOCK_NONE は意図的 — 変更禁止
```
- `generate_post()` 戻り値: `(text, reply_text, image_title, alt_text, in_tok, out_tok)`
- RAGの「ナレッジ外ファクト捏造禁止」制約は国家資格者の信用に直結 — 緩めない

## Critical Warnings
- `config.py` を Read/Edit すると APIキーが漏洩する → **絶対禁止**
- CSVの8列構造を変更するとすべての読み書きが壊れる
- `stock_posts_draft.csv` を削除するとストックが全滅する
- モデル名変更前に必ず `client.models.list()` で利用可能か確認する
- `BLOCK_NONE` セーフティ設定は意図的 — 変更禁止
- `tone_sample_*.txt` はトーン学習用サンプル — Read可（条件は `.claude/rules/security.md` 参照）・Edit禁止・コミット禁止
