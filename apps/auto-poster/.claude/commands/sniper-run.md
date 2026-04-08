# /project:sniper-run — VIPアカウント監視・リプライ起案コマンド

`sniper_radar.py` を実行し、TARGET_ACCOUNTSの最新ツイートをスクリーニングしてリプライ案をCSV出力する。

## 事前確認

実行前に監視対象アカウントと現在のスカウト済み件数を確認する:

```bash
cd C:/Users/yotak/Documents/x-auto
venv/Scripts/python -c "
import sys
# TARGET_ACCOUNTSを表示（APIキーは読まない）
exec(open('sniper_radar.py', encoding='utf-8').read().split('def ')[0])
sys.stdout.buffer.write(f'監視対象: {TARGET_ACCOUNTS}\n件数: {len(TARGET_ACCOUNTS)}\n'.encode('utf-8'))
"
```

```bash
venv/Scripts/python -c "
import pandas as pd, sys, os
if os.path.exists('data/logs/scouted_targets.csv'):
    df = pd.read_csv('data/logs/scouted_targets.csv', encoding='utf-8-sig')
    sys.stdout.buffer.write(f'既存スカウト: {len(df)}件\n'.encode('utf-8'))
else:
    sys.stdout.buffer.write(b'scouted_targets.csv: 未作成\n')
"
```

アカウント一覧を表示してユーザーに実行確認を取ること。

## 実行

```bash
cd C:/Users/yotak/Documents/x-auto
venv/Scripts/python sniper_radar.py
```

## 実行後の確認

```bash
venv/Scripts/python -c "
import pandas as pd, sys
df = pd.read_csv('data/logs/scouted_targets.csv', encoding='utf-8-sig')
latest = df.tail(5)
sys.stdout.buffer.write(f'スカウト総数: {len(df)}件\n直近5件:\n'.encode('utf-8'))
sys.stdout.buffer.write(latest[['取得日時','ユーザー名','対象ツイート']].to_string().encode('utf-8'))
"
```

## 報告フォーマット

```
[sniper-run 完了]
- 監視アカウント数: XX件
- ツイート取得数: XX件
- スクリーニング通過: XX件
- 新規CSV書き込み: XX件
- スカウト総数: XX件（累計）
```

## エラー時の対処

| エラー | 対処 |
|---|---|
| `401 Unauthorized` | X Bearer Tokenの期限切れ。config.pyのX_BEARER_TOKENを確認（直接読まずユーザーに確認を依頼） |
| `429 Too Many Requests` | X APIレート制限。15分待ってから再実行 |
| `404 NOT_FOUND` (Geminiモデル) | `.claude/rules/model-routing.md` の廃止対応手順を参照 |
| ユーザー名が見つからない | TARGET_ACCOUNTSのアカウントが削除・非公開化された可能性。sniper_radar.pyを確認 |

## 注意事項
- X APIのレート制限（15分/15リクエスト）に注意
- 直近1時間以内に実行済みの場合は再実行を避けること
- セラピスト系アカウント（先頭4件）からの高コンバージョンリプライを優先確認すること
