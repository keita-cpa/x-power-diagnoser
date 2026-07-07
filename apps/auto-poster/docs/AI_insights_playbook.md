# AI参考記事インサイト → auto-poster 改善プレイブック

> 参照元ファイル: `G:\マイドライブ\08_AI_Tools_Reference（AIツール参考記事）\` 配下の21ファイル
> 分析日: 2026-06-20

このドキュメントは、収集したAI活用記事から抽出した実践知を、
auto-posterプロジェクトの具体的な改善策にマッピングしたものです。

---

## 1. ループ設計（DISCOVER→PLAN→EXECUTE→VERIFY→ITERATE）

**ソース**: 『loop設計』とは—プロンプト時代の終わり.md

### 核心インサイト

> 「プロンプトを書くな。ループを書け。」
> — Boris Cherny（Claude Code責任者）、Peter Steinberger（OpenClaw創設者）

「一回生成して終わり」→「生成→検証→改善→再生成が自動で回る仕組み」へ。

### auto-poster への適用

| フェーズ | 現在の実装 | 未実装/改善余地 |
|----------|------------|-----------------|
| DISCOVER | `sniper_radar.py` VIP監視 | — |
| PLAN     | `mini_bulk_generator.py` カテゴリ選択 | — |
| EXECUTE  | `conoha_worker.py` Cron投稿 | — |
| VERIFY   | `analyze_my_account.py` 月次分析 | **日次軽量チェック未実装** |
| ITERATE  | 手動でprompts.py weight調整 | **`--recommend-weights` フラグで自動化済（2026-06-20実装）** |

### 実装済み改善

- `analyze_my_account.py --recommend-weights`
  実測AlgoScore/件 vs 現weight を比較し、prompts.py への反映案を自動出力する。
  月次Analyticsの後に実行することで、weight調整の手間を90%削減。

### 残課題

- **日次軽量ヘルスチェック**: `conoha_worker.py` に「ストック残数＋直近3件のAlgoScore」を
  毎朝Slack/ログに通知する仕組み（現在は月次のみ）

---

## 2. バズ番頭パターン（高実績投稿の変形生成）

**ソース**: CodexでXを完全自動化.md

### 核心インサイト

「バズ番頭」: 過去30日でAlgoScore上位の投稿を分析→同じ構造で別内容のバリアントを5本ストック。

> 「今日書くことない...」が概念ごと消滅した。

### auto-poster への適用

従来の生成フロー（カテゴリ選択→knowledge.xlsx RAG→新規生成）とは別に、
**実証済みの勝ちパターンを再利用**する第二の生成経路を追加。

### 実装済み

- **`buzz_variant_generator.py`** (2026-06-20実装)
  ```
  analytics_posts.csv → Top-N抽出 → 手本として Gemini に渡す → バリアント生成 → QC → CSV追記
  ```
- **`/project:buzz-variants`** スラッシュコマンド

**推薦実行タイミング**:
- `/project:monthly-analytics` 直後
- ストック30件割れ時
- 特定カテゴリのAlgoScoreが全体平均の1.5倍超のとき（そのパターンを量産）

---

## 3. AIエージェントチーム設計（AGENTS.md パターン）

**ソース**: CodexでXを完全自動化.md（「AGENTS.mdがチームの憲法」）

### 核心インサイト

エージェントの暴走を防ぐのは憲法（AGENTS.md）。  
ルールがないと「絵文字爆撃する投稿侍」や「全員に媚びるリプ職人」が爆誕する。

**5層アーキテクチャ**:
1. Automations（Cronスケジューラ）
2. Plugins（外部API連携）
3. Memory（永続記憶）
4. Skills（再利用ノウハウ）
5. AGENTS.md（チームの憲法）

### auto-poster との対応

| Codexの概念 | auto-posterの実装 | 評価 |
|-------------|-------------------|------|
| Automations | `conoha_worker.py` | ✓ 完実装 |
| Plugins | tweepy X API | ✓ 実装済み |
| Memory | `knowledge.xlsx` + `posted_history.csv` | ✓ 実装済み |
| Skills | `.claude/skills/` | ✓ 実装済み |
| AGENTS.md | `.claude/rules/persona.md` 等に分散 | △ 分散している |

### 残課題（低優先）

`.claude/rules/persona.md`, `model-routing.md`, `security.md` 等を
単一の `AGENTS.md` または `CLAUDE.md` にまとめるとエージェントの一貫性が向上する。
ただし現在の分散構造も機能しているため、変更は次回リストラクチャ時に検討。

---

## 4. X記事のバズ構造設計

**ソース**: Claude Code記事制作.md

### 核心インサイト

> 「10分ちょいで書かせた2本のX記事が、累計800万インプ。自社商品が1億以上売れた。」

現在のXでは**記事機能が最もバズりやすい**メディア。  
バズ構造: hook-first（続きが読みたい設計）→ Show More ブースト（×20倍）→ リスト獲得→ DM相談。

### auto-poster との対応

`/project:write-article` コマンドで実装済み。  
`prompts.py` の `SYSTEM_PROMPT` に「Show Moreブースト（×20）」「フック設計」が既に組み込まれている。

**追加推奨アクション**:
月1〜2本のX記事を `write-article` で生成し、DM流入を計測する。
記事のAlgoScoreを通常ツイートと比較してROIを検証すること。

---

## 5. ペルソナ設計の深化

**ソース**: Codex完全自動化で高単価アフィリ月100万を組み立てる手順.md

### 核心インサイト（Pain-Stack Mapping）

「人は表面の悩みでは動かない。本当の動機は3層下にある」

5階層: 表層の悩み → 中層の不満 → 深層の根本原因 → 恐怖（最悪シナリオ）→ 理想

### auto-poster への適用

現在の `prompts.py` の「セラピストが抱える悩み」の設計を深化できる:

| 階層 | 現在の対応 | 強化余地 |
|------|-----------|---------|
| 表層 | 税務・確定申告の不安 | 実装済み |
| 中層 | 感情労働の消耗・孤独 | 実装済み（痛みの代弁カテゴリ） |
| 深層 | 収入の不安定さ・将来設計 | 弱い |
| 恐怖 | 税務調査・業務委託の罠 | 実装済み（お金と法律カテゴリ） |
| 理想 | 安心して施術に専念できる状態 | 弱い |

「深層」と「理想」に対応するプロンプト強化が次のチューニング候補。

---

## 6. 半自動フロー原則

**ソース**: OpenClawでSNS運用自動化.md

### 核心インサイト

> 「下書きまで自動、公開は人間が承認。これが失敗しにくい設計。」

### auto-poster との対応

| 機能 | フロー |
|------|--------|
| メイン投稿 | **完全自動**（Cronが自動投稿） ← 手動承認なし |
| quote_reposter | **半自動**（CSV出力→手動承認） ✓ 推奨設計 |
| sniper_radar | **半自動**（リプライ案→手動承認） ✓ 推奨設計 |

メイン投稿の完全自動化はQCが機能している前提なので問題なし。  
スパム判定リスクが高い時期（フォロワー急増・ペナルティ検知時）は一時的に  
`conoha_worker.py` の `CANDIDATE_HOURS` を減らすか停止を検討する。

---

## 実装サマリー（2026-06-20）

| 改善内容 | ファイル | ステータス |
|----------|----------|------------|
| バズ番頭スクリプト | `buzz_variant_generator.py` | ✅ 実装完了 |
| バズ番頭コマンド | `.claude/commands/buzz-variants.md` | ✅ 実装完了 |
| weight自動推薦フラグ | `analyze_my_account.py --recommend-weights` | ✅ 実装完了 |
| インサイトプレイブック | `docs/AI_insights_playbook.md` | ✅ このファイル |

## 次のアクション（推奨優先順）

1. `/project:monthly-analytics` 実行 → `--recommend-weights` で weight 見直し
2. `/project:buzz-variants` で Top3投稿のバリアントを9件ストック
3. 月1〜2本のX記事生成（`/project:write-article`）でDM流入を計測
4. 「深層の悩み・理想」に対応する新プロンプトカテゴリの検討（Pain-Stack Mapping適用）
