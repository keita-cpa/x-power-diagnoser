# /project:stock-check — ストック残数確認

ローカルと ConoHa 本番の stock_posts_draft.csv を即時確認する。
ファイルサーバーを開かずにストック残数と内訳を把握できる。

## Step 1: ローカルのストック確認

```bash
cd C:/Projects/x-integrated-platform/apps/auto-poster
python -c "
import pandas as pd, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

df = pd.read_csv('data/drafts/stock_posts_draft.csv', encoding='utf-8-sig')
pending = df[(df['フォーマット'] == 'tweet') & (df['ステータス'].isna() | (df['ステータス'] == ''))]
posted  = df[df['ステータス'] == 'posted']

print('[LOCAL] stock_posts_draft.csv')
print(f'  未投稿: {len(pending)}件 / 投稿済み: {len(posted)}件 / 合計: {len(df)}件')
print()
print('  カテゴリ内訳:')
for cat, cnt in pending.groupby('カテゴリ')['管理ID'].count().sort_values(ascending=False).items():
    bar = '#' * cnt
    print(f'    {cat:<22} {cnt:>2}件 {bar}')
"
```

## Step 2: ConoHa 本番のストック確認

```bash
ssh -i /c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem \
    -o StrictHostKeyChecking=accept-new \
    -o ConnectTimeout=10 \
    -p 8022 \
    c9994802@www1156.conoha.ne.jp \
    "/usr/local/bin/python -c \"
import csv, sys

path = '/home/c9994802/x-auto/data/drafts/stock_posts_draft.csv'
pending = []
posted_count = 0
try:
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('フォーマット') == 'tweet' and not row.get('ステータス', '').strip():
                pending.append(row.get('カテゴリ', '未分類'))
            elif row.get('ステータス', '').strip() == 'posted':
                posted_count += 1
    print('[CONOHA] stock_posts_draft.csv')
    print('  未投稿: {}件 / 投稿済み: {}件'.format(len(pending), posted_count))
    print()
    from collections import Counter
    for cat, cnt in Counter(pending).most_common():
        print('    {:<22} {}件'.format(cat, cnt))
except Exception as e:
    print('[ERROR] ' + str(e))
\""
```

## 成功の判定基準

- Step 1: `[LOCAL]` 行と件数・カテゴリ内訳が表示される
- Step 2: `[CONOHA]` 行と件数・カテゴリ内訳が表示される
- 両者の件数が一致していれば同期済み。ローカルが多ければ `push_drafts_to_conoha.sh` で反映が必要

## エラー対処

| エラー | 対処 |
|---|---|
| `Connection timed out` | ConoHa の SSH ポートが 8022 であることを確認。VPN 不要 |
| `Permission denied (publickey)` | SSH キーのパスを確認: `/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem` |
| `No such file` (ローカル) | ローカルストックが空。`bulk-generate` でストックを補充する |
| ローカル＞ConoHa | 未反映のストックあり。`bash scripts/push_drafts_to_conoha.sh` で反映 |
| ローカル＜ConoHa | ConoHa 側で投稿が進んでいる状態（正常）。ローカルの在庫管理は参考値として扱う |
