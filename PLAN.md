# 実装計画: リプライ起案の改修・紹介ポストのv3整合・重複ファイル統合

## 目的
1. 特定アカウントへのリプライ案生成（sniper_radar）を、ツイートの話題に応じた
   2モード起案＋v3トーンに改修し、単一アカウント指定でも実行できるようにする
2. 紹介長文ポスト（therapist_introducer）にv3のNGトーン・温度感を整合させる
3. 機能が重複・役目を終えたファイルを統合・削除する

## 影響範囲
| ファイル | 変更 |
|---|---|
| `apps/auto-poster/sniper_radar.py` | 改修（3点） |
| `apps/auto-poster/prompts.py` | `_TONE_REPLY` のみ改修（他セクションは触らない） |
| `apps/auto-poster/.claude/skills/therapist-introduction/SKILL.md` | NGトーン補遺の追加 |
| `apps/auto-poster/therapist_introducer.py` | print絵文字の除去（cp932規約違反の修正） |
| `apps/auto-poster/CLAUDE.md` ほかドキュメント4箇所 | 削除ファイルへの参照を更新 |
| `scripts/deploy_to_conoha.sh` | 削除ファイルのexclude行を整理 |

## タスク分解

### Step 1: sniper_radar.py の改修
- [x] 監視対象を `data/config/target_accounts.txt`（1行1アカウント・#コメント可）に外部化。
      ファイルが無ければ現行のハードコードにフォールバック（コード編集なしで対象を増減できる）
- [x] `--target ユーザー名` フラグを追加（指定時はそのアカウントだけを即時スキャン。
      「@nyakomiya に今すぐリプライ案がほしい」ユースケース対応）
- [x] `draft_reply()` を2モード化:
      A) お金・法律・労務の話題 → 現行のファクト擁護型（条文を平易な翻訳つきで）
      B) 感情・日常・体験談 → 受けの一拍→具体承認型（法律ファクトの強制をやめる）
      モード判定はプロンプト内でGeminiに行わせる（追加API呼び出しなし・コスト増ゼロ）

### Step 2: prompts.py `_TONE_REPLY` のv3同期
- [x] NGワード（魔法・奇跡・賜物・一体感・完璧・プロ呼称等）の禁止を追記
- [x] 「笑」の表記ルール（句点の代わり・「。笑」禁止）・括弧ツッコミ禁止を追記
- [x] 評論家調禁止・恐縮の即時解除・退路つきの誘いを追記
- [x] 既存の【ツッコミ技術】【自虐・逆マウント技術】【絶対制約】は維持

### Step 3: 紹介長文ポスト（therapist-introduction）のv3整合
- [x] SKILL.md に「NGトーン・表記補遺（v3同期）」セクションを追加:
      禁止語（魔法・奇跡・賜物・一体感・完璧・感動・プロ）/「。笑」表記禁止 /
      「〜の賜物である」等の評論調禁止 / 相手は自立した一人の人間（境界線）
- [x] therapist_introducer.py の print 絵文字（⚠️✨📝💡）を [WARN] 等のASCII表記へ修正
      （coding-style.md の cp932 規約違反の解消）

### Step 4: 重複・不要ファイルの統合と削除
- [x] 削除: `utils/text_to_csv.py` — ingest_raw_contents.py と機能重複
      （同じブロック形式を読むが、NG機械検証・QC審査・重複排除なしの劣化版。取り込みはingestに一本化）
- [x] 削除: `utils/migrate_csv.py` — 1回限り・再実行禁止（削除が最も確実な再実行防止）
- [x] 削除: `utils/clean_categories.py` — 1回限り・Windowsパス固定の整備スクリプト
- [x] 削除: `x_auto_master.md` — CLAUDE.md・contexts と重複し記述が古い（ConoHa VPS等）
- [x] 削除: `docs/PLAN_条文番号ルール_20260403.md` — 完了済みの旧計画
- [x] 削除: `drafts/intro_*.md` ×4 — 4月の生成済みドラフト
- [x] 削除: `drafts/gemini_gem_prompt_optimized_v1.md`・`v2.md` — v3が完全上位互換
      ※ drafts/ はGit管理外のため削除すると復元不可（要確認）
- [x] 参照更新: CLAUDE.md（migrate_csv行の削除・therapist関連の説明更新）/
      csv-safety.md・test-run.md・bulk-generate.md（migrate_csv による復旧手順を
      「バックアップからの復旧」に書き換え）/ deploy_to_conoha.sh（exclude 2行削除）

### Step 5: 動作確認・コミット
- [x] py_compile・import確認（sniper_radar / therapist_introducer / prompts）
- [x] sniper_radar はAPI課金を避け、プロンプト組み立てのみローカル検証
      （実スキャンは /project:sniper-run でユーザー実行）
- [x] コミット・プッシュ（シークレットチェック後）

## 懸念事項・リスク
- `drafts/` 配下の削除はGit履歴に残らない（v1/v2プロンプトは完全消失）
- migrate_csv.py 削除により「CSV列が8列でない」場合の復旧はバックアップ頼みになる
  （ただし ingest が毎回バックアップを取るため実用上は問題ない想定）
- SKILL.md 第4段の「独占欲・渇望」表現は、新設したNG境界線（擬似恋愛的距離の禁止）と
  思想的に緊張関係がある。今回の補遺は禁止語・表記の同期に留め、
  第4段の戦略自体を弱めるかは別途ユーザー判断とする

## 合意事項（ユーザー確認待ち）
1. この5ステップで進めてよいか
2. v1/v2プロンプト（Git管理外・復元不可）も削除してよいか
3. SKILL.md 第4段「独占欲・渇望」は現状維持でよいか（禁止語の同期のみ実施）
