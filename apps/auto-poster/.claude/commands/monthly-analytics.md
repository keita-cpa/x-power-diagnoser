# /project:monthly-analytics — 月次X Analytics 分析コマンド

X Analytics CSVを自動取得・分割し、AlgoScoreに基づくカテゴリ別パフォーマンスレポートを出力する。
実行後、`growth-hacker` エージェントへの改善依頼を提案する。

## AlgoScore計算式（重要）
```
AlgoScore = Reply×5 + ProfileClick×4 + Bookmark×3 + RT×3 + DetailClick×2 + Like×1
```
X Heavy Rankerの実際の重み付けに基づく（詳細: `.claude/skills/x-algorithm/SKILL.md`）

---

## Step 1: X Analytics CSVの自動取得

OneDriveのEdgeダウンロードフォルダから最新のX Analytics CSVを検出し、`data/analytics/raw/` へコピーする:

```bash
cd C:/Users/yotak/Documents/x-auto
venv/Scripts/python -c "
import pathlib, shutil, sys, io, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

RAW_DIR = pathlib.Path('data/analytics/raw')
RAW_DIR.mkdir(parents=True, exist_ok=True)

base = pathlib.Path.home() / 'OneDrive'
onedrive_dirs = [d for d in base.parent.iterdir() if 'OneDrive' in d.name] if base.parent.exists() else []
if not onedrive_dirs:
    onedrive_dirs = [base] if base.exists() else []

found = []
for od in onedrive_dirs:
    dl_edge = od / 'ダウンロード' / 'Edge'
    if dl_edge.exists():
        csvs = sorted(dl_edge.glob('tweet_activity_metrics_*.csv'), key=lambda p: p.stat().st_mtime, reverse=True)
        found.extend(csvs[:2])

if not found:
    print('ERROR: X Analytics CSV が見つかりません')
    print('手動で data/analytics/raw/ にCSVを配置してください')
    sys.exit(1)

ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
for src in found[:2]:
    dst = RAW_DIR / f'tweet_activity_{ts}_{src.name}'
    shutil.copy2(src, dst)
    print(f'コピー: {src.name} -> {dst}')
"
```

CSVが見つからない場合: X(Twitter)のアナリティクス画面から手動エクスポートし、ファイルをそのまま `data/analytics/raw/` に配置する（リネーム不要）。

---

## Step 2: 最新ファイルの自動検出 + posts / replies 分割

```bash
venv/Scripts/python -c "
import glob, os, sys, io
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

RAW_DIR = 'data/analytics/raw'
csv_files = glob.glob(f'{RAW_DIR}/*.csv')
if not csv_files:
    print(f'エラー: {RAW_DIR} にCSVファイルが見つかりません')
    sys.exit(1)

latest_file = max(csv_files, key=os.path.getmtime)
print(f'[INFO] 最新のデータを読み込みます: {latest_file}')

df = pd.read_csv(latest_file, encoding='utf-8-sig', header=0)
print(f'総行数: {len(df)}')
print(f'列: {df.columns.tolist()}')

# ポスト本文列を特定（日本語・英語どちらの列名にも対応）
text_candidates = [c for c in df.columns if 'ポスト本文' in c or 'tweet text' in c.lower()]
text_col = text_candidates[0] if text_candidates else df.columns[2]

# @で始まる行 = リプライ
is_reply = df[text_col].astype(str).str.startswith('@')
posts   = df[~is_reply].copy()
replies = df[is_reply].copy()

posts.to_csv('data/analytics/analytics_posts.csv',   encoding='utf-8-sig', index=False)
replies.to_csv('data/analytics/analytics_replies.csv', encoding='utf-8-sig', index=False)
print(f'メイン投稿: {len(posts)}件 -> data/analytics/analytics_posts.csv')
print(f'リプライ:   {len(replies)}件 -> data/analytics/analytics_replies.csv')
"
```

---

## Step 3: AlgoScoreスコアリングと分析レポート

```bash
venv/Scripts/python -c "
import pandas as pd, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# カテゴリ判定キーワード（prompts.pyのPOST_CATEGORIESと同期）
CATEGORY_KEYWORDS = {
    'マインド・喝':         ['メンタル','マインド','稼ぐ','自分','選択','覚悟','逃げる','変わ','稼げ'],
    'リスク警告':           ['税務調査','摘発','逮捕','違法','リスク','注意','危険','罰金','告発'],
    'Q&A・よくある勘違い':  ['Q&A','よくある','勘違い','間違い','実は','本当は','誤解'],
    '防衛実績・事例':       ['実際','事例','相談','解決','守','対応','実績','依頼'],
    '公認会計士・税理士の税務ノウハウ': ['確定申告','経費','節税','控除','所得','消費税','源泉','帳簿'],
    '日常・利用者としての共感': ['今日','ちょっと','なんか','気持ち','疲れ','嬉し','楽し'],
}

def classify(text):
    text = str(text)
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return cat
    return '未分類'

for fname, label in [('data/analytics/analytics_posts.csv','=== メイン投稿 ==='), ('data/analytics/analytics_replies.csv','=== リプライ ===')]:
    try:
        df = pd.read_csv(fname, encoding='utf-8-sig')
    except FileNotFoundError:
        print(f'{fname} が見つかりません')
        continue

    # 列名の正規化（日本語・英語どちらの列名にも対応）
    # 日本語優先マッピング（Xの日本語エクスポート形式）
    JP_COL_MAP = {
        'IMP':    'インプレッション数',
        'Like':   'いいね',
        'RT':     'リポスト',
        'Reply':  '返信',
        'BM':     'ブックマーク',
        'Detail': '詳細のクリック数',
        'PClick': 'プロフィールへのアクセス数',
    }
    col_map = {}
    for short, jp in JP_COL_MAP.items():
        if jp in df.columns:
            col_map[short] = jp
    # 日本語列が見つからない場合は英語キーワードでフォールバック
    if not col_map:
        for col in df.columns:
            cl = col.lower().replace(' ','').replace('_','')
            if 'impression' in cl or 'impres' in cl:  col_map['IMP']    = col
            if 'like' in cl or 'favorite' in cl:       col_map['Like']   = col
            if 'retweet' in cl and 'quote' not in cl:  col_map['RT']     = col
            if 'reply' in cl and 'count' in cl:        col_map['Reply']  = col
            if 'bookmark' in cl:                        col_map['BM']     = col
            if 'detail' in cl or 'expand' in cl:       col_map['Detail'] = col
            if 'profile' in cl and 'click' in cl:      col_map['PClick'] = col

    for k, v in col_map.items():
        df[k] = pd.to_numeric(df[v], errors='coerce').fillna(0).astype(int)

    if not all(k in df.columns for k in ['Like','RT','Reply','BM']):
        print(f'{fname}: 必要な列が見つかりません。列: {df.columns.tolist()}')
        continue

    df['AlgoScore'] = (
        df.get('Reply',  pd.Series(0, index=df.index)) * 5 +
        df.get('PClick', pd.Series(0, index=df.index)) * 4 +
        df.get('BM',     pd.Series(0, index=df.index)) * 3 +
        df.get('RT',     pd.Series(0, index=df.index)) * 3 +
        df.get('Detail', pd.Series(0, index=df.index)) * 2 +
        df.get('Like',   pd.Series(0, index=df.index)) * 1
    )

    text_col = df.columns[0]
    df['カテゴリ'] = df[text_col].apply(classify)

    print(label)
    print(f'投稿数: {len(df)} | 総IMP: {df[\"IMP\"].sum() if \"IMP\" in df else \"N/A\"} | 総AlgoScore: {df[\"AlgoScore\"].sum()}')
    print()

    # カテゴリ別集計
    cat_summary = df.groupby('カテゴリ').agg(
        件数=('AlgoScore','count'),
        AlgoScore合計=('AlgoScore','sum'),
        AlgoScore平均=('AlgoScore','mean'),
        IMP合計=('IMP','sum') if 'IMP' in df else ('AlgoScore','count'),
    ).sort_values('AlgoScore合計', ascending=False)
    print('【カテゴリ別パフォーマンス】')
    print(cat_summary.to_string())
    print()

    # Top5
    print('【AlgoScore Top5】')
    top5 = df.nlargest(5, 'AlgoScore')[[text_col, 'AlgoScore', 'IMP' if 'IMP' in df.columns else 'Like', 'カテゴリ']]
    for _, row in top5.iterrows():
        print(f'  [{row[\"AlgoScore\"]:3d}] {str(row[text_col])[:60]}... ({row[\"カテゴリ\"]})')
    print()
"
```

---

## Step 4: 改善提案の生成

分析レポート出力後、以下を実行:

1. **ボトムカテゴリ**（AlgoScore平均が全体平均の50%以下）を特定
2. **growth-hacker** エージェントへの依頼文を生成:
   ```
   「[カテゴリ名]のAlgoScore平均が[X]で低迷しています。
   x-algorithm/SKILL.md のシグナル重みを参照し、
   prompts.py の該当カテゴリプロンプトを改善してください。」
   ```
3. POST_CATEGORIESの重みを実データと照合し、乖離が大きい場合は修正を提案

## 成功の判定基準
- analytics_posts.csv と analytics_replies.csv が正常に分割されている
- AlgoScoreが全投稿に計算されている
- カテゴリ別集計表が出力されている
- Top5投稿が特定されている
