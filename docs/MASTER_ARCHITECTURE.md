# X-Integrated-Platform (X統合支援プラットフォーム) マスタードキュメント

## 1. プロジェクト概要と目的
本プロジェクトは、X（Twitter）の運用自動化、データ分析による自己進化、不要ポストの自動クレンジングを一元管理する「AI駆動型モノレポ（統合リポジトリ）」である。
最終的な目的は、強力なXアカウントを構築・維持し、集客した見込み客に対して価値あるコンテンツ（社宅規程パッケージ等）を自動生成・販売する「コンテンツ収益化エンジン」を完成させることにある。

## 2. システムアーキテクチャ（ハイブリッド・マルチAI構成）
安全性・コスト・確実性を最高レベルで担保するため、役割を厳格に分割したインフラとマルチAI構成を採用する。

* **GitHub (Private Repository):** ソースコード、プロンプト、AIのルール資産（`.claude/`）のバージョン管理とバックアップの拠点。
* **ConoHa VPS (Ubuntu/Linux):** 実行拠点。固定IPによるAPI通信、安定したCronジョブの実行、および本番データ（CSV/JSON）の永続的な保存先。
* **Render / Vercel:** X戦闘力診断ツールなど、フロントエンドWebアプリの公開環境。

### 【重要】マルチAIによるコスト最適化と役割分担
Claude Codeのトークン消費（APIコスト）を最小化するため、以下のタスク分割を絶対の掟とする。
1. **データ処理は「Python」に一任:** CSVの集計、AlgoScore計算、API通信、文字列の正規化などはLLMに推論させず、必ずPythonスクリプトを実行して処理する。
2. **重いコンテンツ生成は「Gemini ULTRA/Pro」へオフロード:** 大量の資料読み込み（RAG）や、セールスレター・LP・長文コンテンツのゼロからの生成は、Gemini APIを呼び出すスクリプトを介して行う。
3. **Claude Codeの役割は「オーケストレーションと推敲」:** システムの司令塔としてPythonやGeminiを呼び出し、上がってきた結果を最終的なブランドガイドラインに合わせてレビュー・微調整（リライト）することに専念する。

## 3. ディレクトリ構成（プログレッシブ・ディスクロージャー設計）
AIの思考（コンテキスト）汚染とトークン浪費を防ぐため、段階的開示設計（Progressive Disclosure）を徹底する。ルートの `CLAUDE.md` は200行以内の軽量なルーターにとどめ、詳細は各部門ファイルへ委譲する。

```text
C:/Projects/x-integrated-platform/
├── .claude/              # モノレポ共通のAIコンテキスト・司令塔
│   ├── contexts/         # 各アプリの前提知識
│   ├── skills/           # 自律起動するワークフロー（外部ナレッジから随時追加）
│   └── agents/           # 専門分業のサブエージェント（レビュー担当、監査担当など）
├── apps/
│   ├── auto-poster/      # X自動投稿・月次分析・クレンジングシステム
│   │   ├── data/         # 本番データ（Git管理外）
│   │   └── utils/        # Pythonユーティリティスクリプト
│   └── power-diagnoser/  # Xアカウントパワー診断ツール
├── docs/                 # ナレッジベース、運用マニュアル、本マスタードキュメント
├── scripts/              # デプロイ等の一括処理スクリプト（deploy_to_conoha.sh）
├── .gitignore            # 機密情報、ローカルログ、本番データを厳密に除外
└── CLAUDE.md             # プロジェクト全体のルーター（AIへの初期的指示）

```

## 4. 運用ワークフローと自己進化ループ

### 月次分析とプロンプト進化

月に一度、実績データ（CSV）から以下の数式で「AlgoScore」を算出し、プロンプト（`prompts.py`）の配信比率を自動で最適化する。

* **AlgoScore** = `(Reply × 5) + (PClick × 4) + (Bookmark × 3) + (RT × 3) + (Detail × 2) + (Like × 1)`

### 死にポスト全自動クレンジング

アカウント品質維持のため、月次分析時に「投稿から48時間以上経過」「AlgoScore下位10%未満」「PClick=0」のポストを `dead_posts_queue.csv` に抽出。VS Codeでの目視確認後、ConoHa上のCronが毎時最大2件ずつ安全に自動削除する。

### デプロイとGit運用ルール

開発はVS Codeで行い、GitHubへ `commit & push` してナレッジを保護する。本番（ConoHa）への適用は、必ず `bash scripts/deploy_to_conoha.sh` を使用し、本番データ（`data/`）や機密ファイル（`.env`, `*.pem`）を保護しながら差分同期を行う。

## 5. 【Fable 5対応】Skillsの自律的選定と最適化方針

本プロジェクトは、最新のClaude Code（Fable 5等）の自律機能を最大限に引き出すため、以下のフローで常に環境を最適化する。

1. **外部ナレッジの自律探索:** AIは、指示があった際 `C:\Users\yotak\Documents\everything-claude-code` ディレクトリを探索し、現在のプロジェクトフェーズ（X運用自動化、コスト最適化、Geminiコンテンツ生成）に最も合致する優れたSkillやAgent（例：多層レビューエージェント、自動セールスレター作成スキルなど）を自律的に評価・選別する。
2. **アーキテクチャへの統合:** 選別したSkillを `.claude/skills/` や `.claude/agents/` に最適な形で移植し、SKILL.md の `description` や `allowed-tools` を本プロジェクトの仕様に合わせて書き換える。
3. **継続的リファクタリング:** 定期的にプロジェクト全体を俯瞰し、肥大化した設定があればファイル分割（ルールの細分化）を行い、トークン効率とAIの指示遵守率を常に最高状態に保つこと。

### インポート実績（2026-06-11 / everything-claude-code より選定）

| コンポーネント | 配置先 | 選定理由 |
|---|---|---|
| context-budget | `.claude/skills/context-budget/` | §5.3の継続的リファクタリングを自動化（`.claude`全体のトークン監査） |
| llm-cost-optimizer | `.claude/skills/llm-cost-optimizer/` | cost-aware-llm-pipeline + data-scraper-agent のGemini部分を統合。バッチ呼び出し・絞り込みリトライ・予算ガードレール |
| content-engine | `.claude/skills/content-engine/` | コンテンツ収益化エンジン（セールスレター・LP・媒体展開）の設計スキル。長文生成はGeminiオフロード |
| security-reviewer | `.claude/agents/security-reviewer.md` | コミット前・デプロイ前監査をPython/本リポジトリ仕様に書き換えて移植 |

見送り: x-api（x_poster.pyで稼働済み）、code-reviewer/planner/verification-loop（Claude Code組み込み機能と重複）、blueprint/enterprise-agent-ops（現フェーズには過剰）。