# CLAUDE.md — X自動投稿・永久機関システム

## Project
メンエスセラピスト向けX運用システム（Big4品質）。
アカウント: @Keita_CPA（Big4出身公認会計士・税理士）

### 最終目的（North Star — すべての判断の上位基準）
**セラピストと個人的な信頼関係を築き、お金・税・法律・将来のパーソナルな相談（DM）が
自然に生まれること。** 投稿・記事・自動化はすべてこの目的のための手段であり、目的ではない。

- **主要指標**: セラピストとの会話・DM相談の発生。フォロワー数・バズ・到達数（IMP）は副次指標
- **関係構築の本体はリプライ・引用（交流）**。投稿（ブロードキャスト）は「信頼の裏付け」に過ぎない
  （実測: リプライは投稿の8倍効率 → `.claude/skills/x-algorithm/SKILL.md`）
- 法令・判例の知識は「権威の宣言」ではなく「いざという時に頼れる証明」として置く
- 良客視点の発信・男性読者への共感/拡散は、セラピストからの信頼を補強する範囲で維持する副次目標
- 永久機関（自動投稿の継続）は「存在感の維持」のための土台であり、それ単体がゴールではない

## Quick Start（新セッション開始時）
1. このCLAUDE.mdは自動ロード済み
2. 作業内容に応じて `.claude/rules/` の該当ファイルを参照
3. 複雑な変更は必ず `PLAN.md` を先に作成（`.claude/rules/planning-with-files.md`）
4. エラー発生時は `.claude/rules/superpowers.md` の原則に従う
5. 投稿生成・prompts.py編集時は `.claude/skills/x-algorithm/SKILL.md` を参照
6. コンテキストが40万トークンに近づいたら `/compact` を実行して圧縮する（コスト最適化）

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
| `drafts/gemini_gem_prompt_optimized.md` | Gem/NotebookLM用マスタープロンプトの単一ソース（投稿生成用） | 改訂記録はファイル先頭ヘッダーに追記。`--print-prompt` で出力 |
| `drafts/gem_mobile_assistant_reply_quote.md` | スマホ運用Gem用プロンプト（リプライ＆引用リポストのスマホ起案） | 中距離(柔らかい敬語)・湿度排除・二人称「あなた」不使用(本Gem固有)。改訂記録はファイル先頭ヘッダーに追記 |
| `drafts/gem_influencer_reply_quote.md` | インフルエンサー向けリプライ＆引用リポスト起案Gem | 同業リスペクト型・安全チェック付き。influencer_accounts.txt 登録アカウント向け |
| `drafts/gem_analytics_scientist.md` | X Analytics分析・AlgoScoreスコアリング・改善パッチ設計Gem | /project:monthly-analytics内部使用。prompts.py weight変更案をPythonフォーマットで出力 |
| `drafts/gem_therapist_introducer.md` | セラピスト紹介長文ポスト生成Gem | /project:introduce-therapist 連動。5段構成・╰ᘏᗢ ☕︎締め |
| `drafts/gemini_gem_article_prompt.md` | X記事（長文記事）生成Gem | /project:write-article 連動。3,000〜4,500字生成→Claude推敲 |
| `utils/merge_new_posts.py` | outbox差分のConoHa側マージ（冪等） | push_drafts_to_conoha.sh から実行 |
| `prune_dead_posts.py` | 死にポストの安全削除（毎時最大2件） | ConoHa Cron |
| `config.py` | APIキー・パス設定 | **Read/Edit 絶対禁止** |
| `sniper_radar.py` | セラピスト個人監視・リプライ起案（共感・承認デフォルト／専門は質問時のみ・72h再接触インターバル） | 対象は `data/config/target_accounts.txt` で管理（全員セラピスト個人・25件）・`--target` で単一指定可 |
| `data/config/target_accounts.txt` | sniper_radar.py / quote_reposter.py の監視対象リスト（セラピスト個人25件） | 全員セラピスト個人に限定。フォロワー5000以上は influencer_accounts.txt へ |
| `data/config/influencer_accounts.txt` | コバンザメ戦略用・Xリスト参照ドキュメント（sniper --mode influencer が参照するXリストのメンバー） | 業者・大型アカウントのみ。個人セラピストは target_accounts.txt へ移動済み |
| `data/config/watch_keywords.txt` | Phase 1 keyword_scout.py 用キーワード単一ソース（税・お金・将来不安39件） | セラピストの不安投稿を検索するためのキーワード集。直接削除禁止 |
| `keyword_scout.py` | キーワード検索による新規セラピスト発掘（watch_keywords.txt参照・Gemini不使用） | 出力 `data/logs/keyword_scout_results.csv`・発掘後は手動で target_accounts.txt に追記 |
| `quote_reposter.py` | 引用リポスト起案（実測最高フォーマット・代弁型・全肯定のみ） | 出力 `data/logs/quote_drafts.csv`・sniperと履歴共有で72hインターバル・投稿は手動承認 |
| `therapist_introducer.py` | 指定アカウントの紹介長文ポスト生成（「気くばり手帖」シリーズ採番・ターミナル出力） | 台帳 `data/logs/introductions_log.csv`（8列）に自動記録。会った人・施術を受けた人は紹介禁止（制度v2） |
| `docs/introduction_system.md` | セラピスト紹介の制度設計書v2（会わない紹介・シリーズ・希少性・再紹介条件・ステマ規制・KPIの単一ソース） | 紹介運用の変更時は必ずここを更新 |
| `conoha_worker.py` | Cronスケジューラ | |
| `daily_menu.py` | 毎朝の交流メニュー生成（メンション返信案の起案＋sniper/quote/scout実行→HTML集約） | タスクスケジューラ `KeitaCPA_DailyMenu` が毎朝7:30に `run_daily_menu.cmd` 経由で自動実行。出力 `data/menus/latest.html` |
| `run_daily_menu.cmd` | daily_menu.py 実行→メニューをブラウザで開く起動バッチ | ダブルクリックで手動実行も可 |
| `docs/system_overview.html` | 永久機関の全体像・実測根拠・毎日の行動・撤退基準 | 意味を見失ったら開くページ |
| `docs/gem_knowledge_map.html` | Gem×ナレッジ設計書（7 Gemの添付ナレッジ構成・NotebookLM使い分け・著作権設計） | Gemのナレッジ変更時は必ずここを更新 |
| `docs/gdocs_archive_sync.md` | 投稿済みアーカイブ→Googleドキュメント自動転記の設定手順（Apps Script） | 重複防止ナレッジの基盤 |
| `recycler.py` | 死にポストリサイクラー（突合→アーカイブ→Gemini Flashリライト→CSV追記） | `--dry-run` / `--archive-only` / `--recycle-only` モード対応。ローカル実行専用 |
| `data/analytics/dead_posts_archive.csv` | 削除済み死にポストの全情報アーカイブ（ポストID・投稿日・削除日・カテゴリ・AlgoScore・本文全文・リサイクル済み） | prune_dead_posts.py 実行後・recycler.py 実行前に内容を確認すること |

## Slash Commands（`/project:xxx` で呼び出し）
| コマンド | 説明 |
|---|---|
| `/project:daily-menu` | daily_menu.py を実行・今日の交流メニュー（HTML）を生成・件数報告 |
| `/project:stock-check` | ローカルとConoHa本番のストック残数をSSHで即時確認 |
| `/project:test-run` | ヘルスチェック（import確認・API疎通・CSV検証） |
| `/project:bulk-generate` | mini_bulk_generator.py を安全実行・ストック数報告 |
| `/project:keyword-scout` | keyword_scout.py を実行・新規セラピスト候補を発掘・CSV出力 |
| `/project:sniper-run` | sniper_radar.py を実行・新規スカウト数報告 |
| `/project:quote-run` | quote_reposter.py を実行・引用リポスト案を起案・新規件数報告 |
| `/project:introduce-therapist @username` | 指定アカウントの紹介長文ポストを生成・ターミナル出力 |
| `/project:monthly-analytics` | 月次X Analytics CSV分析→AlgoScoreレポート出力 |
| `/project:ingest-drafts` | raw_contents の取り込み→検証→QC→CSV追記→本番反映案内 |
| `/project:write-article テーマ` | X記事（長文記事）の構成設計→Gemini ULTRAハンドオフ→レビュー→最終稿（入稿は手動） |
| `/project:buzz-variants` | 高AlgoScore投稿のバリアント生成→CSV追記（バズ番頭パターン・loop設計ITERATE実装） |
| `/project:recycle-posts` | recycler.py を実行→死にポストをGemini Flashでリライト→stock_posts_draft.csvに追記 |

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
| `x-article` | write-article コマンド実行時・X記事フォーマット/公開運用の調整時 |

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
- **対話型CLI（`mini_bulk_generator.py` 等）を `printf`/パイプで自律実行しない**・長文生成はGemini ULTRAへ委譲 → `.claude/rules/cost-and-delegation.md`
- `tone_sample_*.txt` はトーン学習用サンプル — Read可（条件は `.claude/rules/security.md` 参照）・Edit禁止・コミット禁止
