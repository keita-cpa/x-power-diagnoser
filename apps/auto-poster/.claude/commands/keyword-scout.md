# /project:keyword-scout — キーワード検索・新規セラピスト発掘コマンド

`keyword_scout.py` を実行し、`watch_keywords.txt` のキーワードで X を検索して
税・お金・将来の不安を投稿しているセラピスト系の新規アカウントを発掘する。

## 事前確認

```bash
# キーワード数・既存の発掘済み件数を確認する
cd C:/Projects/x-integrated-platform/apps/auto-poster
python -c "
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
kws = [l.split('#',1)[0].strip() for l in open('data/config/watch_keywords.txt', encoding='utf-8-sig') if l.split('#',1)[0].strip()]
print(f'watch_keywords.txt: {len(kws)}件')
if os.path.exists('data/logs/keyword_scout_results.csv'):
    import csv
    rows = list(csv.DictReader(open('data/logs/keyword_scout_results.csv', encoding='utf-8-sig')))
    print(f'過去の発掘済み候補: {len(rows)}件')
else:
    print('keyword_scout_results.csv: 未作成（初回実行）')
"
```

## 実行

```bash
cd C:/Projects/x-integrated-platform/apps/auto-poster

# 全キーワードをバッチ検索（推奨）
python keyword_scout.py

# 単一キーワードでテスト検索
python keyword_scout.py --keyword 確定申告

# 1バッチあたりの最大採用件数を変更する（デフォルト5）
python keyword_scout.py --max 3
```

## 実行後の確認

```bash
python -c "
import pandas as pd, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
df = pd.read_csv('data/logs/keyword_scout_results.csv', encoding='utf-8-sig')
latest = df.tail(10)
print(f'発掘済み総数: {len(df)}件')
print('直近10件:')
print(latest[['マッチキーワード','ユーザー名','フォロワー数','bio']].to_string())
"
```

## target_accounts.txt への追記フロー

1. `data/logs/keyword_scout_results.csv` を開いて目視確認する
2. **セラピスト個人と確認できたアカウント**のみ `data/config/target_accounts.txt` に追記する
3. フォロワー5000以上は `influencer_accounts.txt` へ
4. 追記後、`/project:sniper-run` でリプライ起案を実行する

## 報告フォーマット

```
[keyword-scout 完了]
- 検索バッチ数: XX件（キーワード計 XX件）
- 新規候補（既知除外）: XX件
- 発掘済み総数（累計）: XX件
[次のアクション]
- target_accounts.txt への追加推奨: XX件
  （アカウント名と推奨理由を列挙）
```

## エラー時の対処

| エラー | 対処 |
|---|---|
| `[FORBIDDEN] 検索APIへのアクセス権がありません` | X API Basic プラン（$100/月）が必要。Freeプランでは search_recent_tweets が使用不可 |
| `429 Too Many Requests` | レート制限（15req/15min）。`wait_on_rate_limit=True` で自動待機するため通常は発生しない |
| `keyword_scout_results.csv` が空 | `THERAPIST_SCREEN_KEYWORDS` に一致するバイオ・ツイートがなかった。`--keyword` で単一テストを実施 |

## 注意事項

- 発掘候補は **セラピスト個人かどうかを目視確認**してから target_accounts.txt に追加すること
- 同一ランで重複発掘しない（`seen_in_run` 制御）
- 過去の発掘済み候補（`keyword_scout_results.csv`）も自動除外されるため、同一アカウントが重複追記されることはない
