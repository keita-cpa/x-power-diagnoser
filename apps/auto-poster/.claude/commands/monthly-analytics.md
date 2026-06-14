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
cd C:/Projects/x-integrated-platform/apps/auto-poster
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

# カテゴリ判定キーワード（prompts.py v6 のPOST_CATEGORIESと同期・2026-06-12ペルソナv2切替）
# 注意: 切替期は旧カテゴリ投稿が混在する。判定は新カテゴリ優先 → 旧カテゴリの順で行い、
#       レポートでは新旧を別集計すること（対応表: docs/SOP_Manual.md §9）
CATEGORY_KEYWORDS = {
    # ── 新カテゴリ（v6）──
    'お金と法律のお守り':           ['確定申告','経費','節税','控除','所得','消費税','源泉','帳簿','税務調査','リスク','勘違い','誤解','ガチレス'],
    '施術中のワンシーン・そっと解決': ['施術中','会話','聞かれ','ポロッ','相談され','答えた','そうなんですか'],
    '良客の目線・メンエス愛':       ['気遣い','救われ','癒や','入室','タオル','照明','通','お店','セラピストさん'],
    '痛みの代弁・がんばりの承認':   ['誰にも言えない','孤独','消耗','笑顔','演技','がんばり','承認','しんどい','疲れ'],
    '趣味・人間味・日常':           ['小説','本','映画','読んだ','コンビニ','帰り道','季節','失敗'],
    # ── 旧カテゴリ（v5以前の投稿の判定用・段階的に削除可）──
    'マインド・喝':         ['メンタル','マインド','覚悟','逃げる','稼げ'],
    '防衛実績・事例':       ['事例','実績','依頼','立ち会'],
    '日常・利用者としての共感': ['今日','ちょっと','なんか','気持ち'],
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

---

## Step 5: 死にポストの特定 → dead_posts_queue.csv 出力

「死にポスト」を精度重視の全条件ANDで判定し、キューファイルに出力する（削除は不可逆のため安全側に倒す）。
判定: ①投稿から48時間経過 ②6指標すべて0（Like/Reply/RT/BM/PClick/Detail）③IMP < 中央値の50%。
除外: 【保存版】等のホワイトリスト語を含む投稿・リプライ（@始まり）。メイン投稿（analytics_posts.csv）のみ処理する。
※ ホワイトリスト語は prune_dead_posts.py の WHITELIST と同期すること。

```bash
venv/Scripts/python -c "
import pandas as pd, sys, io, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

QUEUE_PATH = 'data/analytics/dead_posts_queue.csv'
fname      = 'data/analytics/analytics_posts.csv'

try:
    df = pd.read_csv(fname, encoding='utf-8-sig')
except FileNotFoundError:
    print(f'[ERROR] {fname} が見つかりません。先にStep 2を実行してください。')
    sys.exit(1)

# 列名正規化（Step 3と同じマッピング）
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
if not col_map:
    for col in df.columns:
        cl = col.lower().replace(' ', '').replace('_', '')
        if 'impression' in cl or 'impres' in cl:  col_map['IMP']    = col
        if 'like' in cl or 'favorite' in cl:      col_map['Like']   = col
        if 'retweet' in cl and 'quote' not in cl: col_map['RT']     = col
        if 'reply' in cl:                          col_map['Reply']  = col
        if 'bookmark' in cl:                       col_map['BM']     = col
        if 'detail' in cl or 'expand' in cl:       col_map['Detail'] = col
        if 'profile' in cl and 'click' in cl:      col_map['PClick'] = col

for k, v in col_map.items():
    df[k] = pd.to_numeric(df[v], errors='coerce').fillna(0).astype(int)

if not all(k in df.columns for k in ['Reply', 'BM', 'Like']):
    print('[ERROR] 必要な列が見つかりません。列名を確認してください。')
    sys.exit(1)

# AlgoScore再計算
df['AlgoScore'] = (
    df.get('Reply',  pd.Series(0, index=df.index)) * 5 +
    df.get('PClick', pd.Series(0, index=df.index)) * 4 +
    df.get('BM',     pd.Series(0, index=df.index)) * 3 +
    df.get('RT',     pd.Series(0, index=df.index)) * 3 +
    df.get('Detail', pd.Series(0, index=df.index)) * 2 +
    df.get('Like',   pd.Series(0, index=df.index)) * 1
)

# 日付列・ID列・本文列を特定
date_col = next((c for c in df.columns if '日付' in c or c.lower() == 'date'), df.columns[1])
id_col   = next((c for c in df.columns if 'ポストID' in c or c.lower() in ('tweet id', 'post id', 'id')), df.columns[0])
text_col = next((c for c in df.columns if 'ポスト本文' in c or 'tweet text' in c.lower()), df.columns[2])

# --- 死にポスト判定（精度重視・全条件AND / 削除は不可逆のため安全側に倒す）---
# 1) 48時間経過（初動IMPが落ち着く猶予）
df['_posted_at'] = pd.to_datetime(df[date_col], errors='coerce')
now = datetime.datetime.now()
elapsed_ok = (now - df['_posted_at']).dt.total_seconds() >= 48 * 3600

# 2) 完全無反応（6指標すべて0。1つでも反応があれば残す）
SIGNALS = ['Like', 'Reply', 'RT', 'BM', 'PClick', 'Detail']
zero_engagement = pd.Series(True, index=df.index)
for k in SIGNALS:
    zero_engagement &= (df.get(k, pd.Series(0, index=df.index)) == 0)

# 3) リーチ下限割れ（IMP < 中央値の50%。高IMPで今後伸び得る投稿は残す保険）
imp = df.get('IMP', pd.Series(0, index=df.index))
imp_floor = imp.median() * 0.5
imp_low = imp < imp_floor

# 除外) エバーグリーン・ホワイトリスト（本文ラベル・全文判定）。prune_dead_posts.py の WHITELIST と同期
WHITELIST = ['【保存版】', '緊急レポート', '保存推奨', '完全版', '報告書']
not_whitelisted = df[text_col].astype(str).apply(lambda t: not any(w in t for w in WHITELIST))

# 全条件ANDを満たす行を抽出
dead_mask = elapsed_ok & zero_engagement & imp_low & not_whitelisted
dead = df[dead_mask].copy()

if dead.empty:
    print('[INFO] 死にポストは検出されませんでした。(基準: 48h経過 & 全6指標0 & IMP<{:.0f} & 非WL)'.format(imp_floor))
else:
    queue = pd.DataFrame({
        'ポストID':      dead[id_col].astype(str),
        '日付':          dead[date_col].astype(str),
        '本文先頭20文字': dead[text_col].astype(str).str[:20],
    })
    queue.to_csv(QUEUE_PATH, encoding='utf-8-sig', index=False)
    print('[OK] 死にポスト {}件 を {} に出力 (基準: 48h経過 & 全6指標0 & IMP<{:.0f} & WL{}語除外)'.format(
        len(queue), QUEUE_PATH, imp_floor, len(WHITELIST)))
    print()
    print(queue.to_string(index=False))
"
```

**Step 5 成功の判定基準**
- `data/analytics/dead_posts_queue.csv` が生成されている（または「検出されませんでした」が表示される）
- 出力列が `ポストID`, `日付`, `本文先頭20文字` の3列になっている
- encoding `utf-8-sig` で VS Code・Excel どちらでも文字化けせず開ける
