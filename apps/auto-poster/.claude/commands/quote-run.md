# /project:quote-run — 引用リポスト起案コマンド

`quote_reposter.py` を実行し、監視対象アカウント（`data/config/target_accounts.txt` で管理）の
最新ツイートをスクリーニングして「相手がリポストで返したくなる代弁コメント案」をCSV出力する。
実測で最もスコアが高いフォーマット（Quote Tweet形式 / AlgoScore=44）の起案専用。

**起案は自動・投稿は手動承認。** 出力CSVを目視確認し、指摘・説教・未要求のアドバイスに
なっていないことを必ずチェックしてから手で引用リポストすること。

## 事前確認

監視対象アカウントと現在の引用起案済み件数を確認する:

```bash
cd C:/Projects/x-integrated-platform/apps/auto-poster
cat data/config/target_accounts.txt
```
（ファイルが無い場合は `sniper_radar.py` 内の `DEFAULT_TARGET_ACCOUNTS` にフォールバックされる）

```bash
python -c "
import pandas as pd, sys, os
if os.path.exists('data/logs/quote_drafts.csv'):
    df = pd.read_csv('data/logs/quote_drafts.csv', encoding='utf-8-sig')
    sys.stdout.buffer.write(f'既存引用起案: {len(df)}件\n'.encode('utf-8'))
else:
    sys.stdout.buffer.write(b'quote_drafts.csv: 未作成\n')
"
```

アカウント一覧を表示してユーザーに実行確認を取ること。

## 実行

```bash
cd C:/Projects/x-integrated-platform/apps/auto-poster
python quote_reposter.py
```

特定の1アカウントだけ即時スキャンする場合（72時間インターバルを無視）:

```bash
python quote_reposter.py --target ユーザー名
```

## 実行後の確認

```bash
python -c "
import pandas as pd, sys
df = pd.read_csv('data/logs/quote_drafts.csv', encoding='utf-8-sig')
latest = df.tail(5)
sys.stdout.buffer.write(f'引用起案総数: {len(df)}件\n直近5件:\n'.encode('utf-8'))
sys.stdout.buffer.write(latest[['取得日時','ユーザー名','AI引用コメント案']].to_string().encode('utf-8'))
"
```

## 報告フォーマット

```
[quote-run 完了]
- 監視アカウント数: XX件
- 間隔スキップ(72h): XX件
- スクリーニング通過: XX件
- 新規CSV書き込み: XX件
- 引用起案総数: XX件（累計）
```

## スパム・炎上回避の組み込み制御（コード側で自動適用）
- **72時間インターバル**: リプライ(`scouted_targets.csv`)＋引用(`quote_drafts.csv`)の両履歴をマージ参照し、
  同一アカウントへ3日以内に接触済みならスキップ（横断スパム防止）
- **上限**: 1ラン1アカウント1件／1ラン4件（リプライ sniper=6 と合わせ1日5〜10件目安）
- **温度ランダム化**: 0.85〜1.05 でジッターし、AI定型文の固定化を防止

## エラー時の対処

| エラー | 対処 |
|---|---|
| `401 Unauthorized` | X Bearer Tokenの期限切れ。config.pyのX認証情報を確認（直接読まずユーザーに確認を依頼） |
| `429 Too Many Requests` | X APIレート制限。15分待ってから再実行 |
| `404 NOT_FOUND` (Geminiモデル) | `.claude/rules/model-routing.md` の廃止対応手順を参照 |
| ユーザー名が見つからない | 監視対象アカウントが削除・非公開化された可能性。data/config/target_accounts.txt を確認 |

## 注意事項
- X APIのレート制限（15分/15リクエスト）に注意
- 引用リポストは「相手への贈り物」。全肯定・共感・事実承認のみ。指摘・説教は厳禁
- 投稿前に必ず目視確認すること（手動承認フロー）
