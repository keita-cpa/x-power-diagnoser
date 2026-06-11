# Context: X_Operations / Psychology ナレッジ

## X_Operations（docs/knowledge/X_Operations/）

X運用ルール（凍結回避・自動化の許容範囲）と機能活用（X記事・note導線）のナレッジ。
`X_Algorithm/`（何がバズるか）と対になる「何をしてはいけないか・どの機能を使うか」の層。

### 参照タイミング
- auto-poster / sniper_radar の自動化仕様を変更する時（→ rules/X自動化開発ルール）
- IMPが急減した時・凍結リスクを評価する時（→ rules/X検索ルール・警告と凍結）
- X記事機能・note収益化フローを実装する時（→ features/）

### 鉄則
- まず `X_Operations/README.md`（ダイジェスト）だけ読む。詳細が必要な時のみ個別ファイルを開く
- リプライ自動化は「起案まで」。送信は人間判断（sniper_radarの現設計を崩さない）
- グレーな自動化は絶対にしない（凍結＝アカウント資産の全損）

## Psychology（docs/knowledge/Psychology/）

ペルソナv2の心理層。『人蕩し術』（自己重要感・群居衝動・愛と陽気さ）×『おもろい話し方』
（フリオチ・例え・感情言語化）の戦術原則集。

### 参照タイミング
- prompts.py のトーン・カテゴリプロンプトを改修する時
- 投稿の推敲で「媚びと承認の区別」「説教の混入」を判定する時
- content-engine で長文コンテンツを設計する時

### 関連実装
- 原実装（最精密）: `apps/auto-poster/.claude/skills/therapist-introduction/SKILL.md`
- 適用先: `apps/auto-poster/prompts.py` v6 / `.claude/rules/persona.md` v2
