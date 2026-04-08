# x-integrated-platform 運用マニュアル (SOP)

**対象読者**: エンジニア以外のオペレーター  
**最終更新**: 2026-04-07  
**環境**: Windows 11 + Git Bash / ConoHa VPS / Render (PaaS)

---

## 目次

1. [フォルダの役割説明](#1-フォルダの役割説明)
2. [毎日の確認手順（デイリーチェック）](#2-毎日の確認手順)
3. [ConoHaへのデプロイ手順](#3-conohaへのデプロイ手順)
4. [ConoHaのCronパス変更手順](#4-conohaのcronパス変更手順)
5. [VercelのRoot Directory変更手順](#5-vercelのroot-directory変更手順)
6. [トラブルシューティング](#6-トラブルシューティング)

---

## 1. フォルダの役割説明

### 全体像

このシステムは「モノレポ」と呼ばれる1つのフォルダ（`x-integrated-platform`）に
複数のアプリをまとめて管理しています。

```
C:\Projects\x-integrated-platform\
│
├── apps/
│   ├── power-diagnoser/    ← Xアカウント戦闘力診断ツール
│   │                          （Renderというクラウドサービスで動作）
│   └── auto-poster/        ← X自動投稿システム・永久機関
│                              （ConoHa VPSサーバーで動作）
│
├── docs/
│   ├── knowledge/
│   │   ├── X_Algorithm/    ← Xの公式アルゴリズム（参照資料・変更不可）
│   │   └── Claude_Mastery/ ← Claude Code設定集（参照資料・変更不可）
│   └── SOP_Manual.md       ← このファイル（運用マニュアル）
│
├── scripts/
│   ├── migrate_local.py    ← データ移行スクリプト（初回のみ）
│   └── deploy_to_conoha.sh ← ConoHaへのデプロイスクリプト
│
└── CLAUDE.md               ← AIアシスタントへの指示書（触らない）
```

### 各フォルダの詳細説明

#### `apps/power-diagnoser/` — X戦闘力診断ツール

インターネット上で公開されているウェブサービスです。
GitHubにコードをアップロード（push）すると、Renderが自動的に更新します。

- **稼働確認**: ブラウザで `/api/health` にアクセスして `{"status": "ok"}` が返るか確認
- **注意**: このフォルダをConoHaにデプロイすることはありません

#### `apps/auto-poster/` — X自動投稿システム

ConoHa VPSサーバー上で動作しています。
5分おきにサーバーが自動的に `conoha_worker.py` を実行し、Xに投稿します。

**重要ファイル（絶対に削除禁止）:**

| ファイル | 内容 | 削除した場合の影響 |
|---|---|---|
| `data/drafts/stock_posts_draft.csv` | 投稿予定リスト | 全投稿ストックが消える |
| `data/logs/posted_history.csv` | 投稿済み履歴 | 重複投稿が発生する可能性 |
| `schedule.json` | 投稿タイミング管理 | スケジュールがリセットされる |

#### `docs/knowledge/` — 参照資料（変更禁止）

- `X_Algorithm/`: Xが公開しているアルゴリズムのコード。投稿最適化の参考資料。
- `Claude_Mastery/`: Claude AIの設定サンプル集。

---

## 2. 毎日の確認手順

### 2-1. X自動投稿システムの確認

**方法A: ブラウザから確認（簡単）**

Xのアカウントページを開き、直近の投稿が正常に行われているか確認します。

**方法B: サーバーログの確認（詳しく確認したい場合）**

1. Git Bashを開く（Windowsのスタートメニューで「Git Bash」を検索）
2. 以下のコマンドを入力してサーバーに接続:
   ```bash
   ssh -i "/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem" root@[ConoHaのIPアドレス]
   ```
3. 接続後、直近のログを確認:
   ```bash
   tail -20 /root/x-auto/logs/cron.log
   ```
4. 投稿ストックの残数を確認（残り10件を切ったら補充）:
   ```bash
   python3 -c "
   import csv
   with open('/root/x-auto/data/drafts/stock_posts_draft.csv', encoding='utf-8-sig') as f:
       rows = list(csv.DictReader(f))
       empty = [r for r in rows if not r.get('ステータス')]
       print(f'未投稿ストック数: {len(empty)}件')
   "
   ```

### 2-2. X診断ツールの確認

1. ブラウザで以下にアクセス: `https://[あなたのRenderアプリURL]/api/health`
2. `{"status": "ok"}` が返れば正常
3. 返らない場合 → §6 トラブルシューティング を参照

---

## 3. ConoHaへのデプロイ手順

**デプロイが必要な場面:** `apps/auto-poster/` のPythonファイルを修正した後

### 前提条件

- Git Bashがインストールされていること
- ConoHaのIPアドレスを知っていること
- SSH秘密鍵のパスを知っていること（例: `C:\Users\yotak\Documents\x-auto\key-*.pem`）

### 手順

**ステップ1: Git Bashを開く**

Windowsのスタートメニューで「Git Bash」を検索して起動します。

**ステップ2: 環境変数を設定する**

以下を1行ずつ入力してEnterキーを押します（毎回必要）:

```bash
export CONOHA_USER="root"
export CONOHA_HOST="133.xxx.xxx.xxx"
export CONOHA_DEPLOY_PATH="/root/x-auto"
export SSH_KEY="/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem"
```

> **注意**: `133.xxx.xxx.xxx` の部分は実際のConoHaのIPアドレスに変えてください。
> `key-2026-03-24-22-28.pem` の部分は実際の鍵ファイル名に変えてください。

**ステップ3: dry-run（テスト）で内容を確認する**

```bash
cd /c/Projects/x-integrated-platform
bash scripts/deploy_to_conoha.sh --dry-run
```

画面に送信されるファイルの一覧が表示されます。
**以下のファイルが一覧に含まれていないことを確認してください:**
- `.env`（シークレットファイル）
- `*.pem`（SSH秘密鍵）
- `*.csv`（本番データ）
- `tone_sample_*.txt`（個人情報）

**ステップ4: 実際にデプロイする**

```bash
bash scripts/deploy_to_conoha.sh
```

「本当に実行しますか？」と聞かれたら `yes` と入力してEnterを押します。

**ステップ5: デプロイ後の動作確認**

```bash
ssh -i "$SSH_KEY" ${CONOHA_USER}@${CONOHA_HOST} "cd ${CONOHA_DEPLOY_PATH} && ./venv/bin/python conoha_worker.py"
```

エラーが出なければ成功です。

---

## 4. ConoHaのCronパス変更手順

**この操作が必要な場面:**
- デプロイ先のフォルダパスを変更した時
- サーバー上のPython仮想環境のパスが変わった時
- 新しいサーバーに移行した時

> **注意**: Cronを誤って止めると自動投稿が停止します。
> 変更後は必ず動作確認を行ってください。

### 手順

**ステップ1: ConoHaのサーバーにSSHで接続する**

```bash
ssh -i "/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem" root@[ConoHaのIPアドレス]
```

**ステップ2: 現在のCron設定を確認する**

```bash
crontab -l
```

以下のような行が表示されます:

```
*/5 * * * * /root/x-auto/venv/bin/python /root/x-auto/conoha_worker.py >> /root/x-auto/logs/cron.log 2>&1
```

**ステップ3: Cron設定を編集する**

```bash
crontab -e
```

`nano`というテキストエディタが開きます。

**ステップ4: パスを変更する**

矢印キーでカーソルを移動して、変更が必要な部分を書き換えます。

変更例:
- **変更前**: `/root/x-auto/conoha_worker.py`
- **変更後**: `/home/新しいユーザー名/x-auto/conoha_worker.py`

**ステップ5: 保存して終了する**

1. `Ctrl + O` キーを押す（保存）
2. `Enter` キーを押す（ファイル名を確認）
3. `Ctrl + X` キーを押す（終了）

**ステップ6: 変更を確認する**

```bash
crontab -l
```

変更後のパスが表示されれば成功です。

**ステップ7: 動作確認（手動で1回実行）**

```bash
/root/x-auto/venv/bin/python /root/x-auto/conoha_worker.py
```

エラーが出なければ成功です。5分後にXの投稿を確認してください。

---

## 5. VercelのRoot Directory変更手順

> **現在の状況**: `power-diagnoser` は現在 **Render** を使用しており、Vercelは使用していません。
> 将来Vercelに移行した場合のみ、この手順を使用してください。

**この操作が必要な場面:**
- モノレポ移行後にVercelの設定を更新する時
- Vercel上でビルドエラーが発生した時（「ファイルが見つからない」エラー）

### 手順

**ステップ1: Vercelにログインする**

ブラウザで `https://vercel.com/dashboard` にアクセスしてログインします。

**ステップ2: プロジェクトを選択する**

ダッシュボードから対象のプロジェクト（例: `x-power-diagnoser`）をクリックします。

**ステップ3: Settings を開く**

上部メニューの「Settings」タブをクリックします。

**ステップ4: Root Directory を変更する**

1. 「General」セクションを探します
2. 「Root Directory」という項目を見つけます
3. 現在の値（例: `/` または空欄）を新しい値に変更します
   - モノレポ移行後の値: `apps/power-diagnoser`
4. 「Save」ボタンをクリックします

**ステップ5: 再デプロイする**

1. 「Deployments」タブをクリックします
2. 最新のデプロイメントの右側にある「...」メニューをクリックします
3. 「Redeploy」を選択します
4. 「Redeploy」ボタンをクリックして確認します

**ステップ6: 動作確認**

デプロイ完了後（通常2〜3分）にURLにアクセスして動作確認します。

---

## 6. トラブルシューティング

### Q: 自動投稿が止まっている

**確認手順:**

```bash
# サーバーに接続
ssh -i "/c/Users/yotak/Documents/x-auto/key-*.pem" root@[ConoHaのIP]

# ログを確認
tail -50 /root/x-auto/logs/cron.log

# 手動で実行してエラーを確認
cd /root/x-auto
./venv/bin/python conoha_worker.py
```

**よくある原因と解決策:**

| エラーメッセージ | 原因 | 解決策 |
|---|---|---|
| `ModuleNotFoundError` | Pythonライブラリが不足 | `./venv/bin/pip install -r requirements.txt` |
| `FileNotFoundError: stock_posts_draft.csv` | 投稿ストックファイルが存在しない | `mini_bulk_generator.py` で再生成 |
| `tweepy.errors.Unauthorized` | X APIキーが無効 | `config.py` のAPIキーを確認・更新 |
| `JSONDecodeError` | `schedule.json` が破損 | `schedule.json` を削除して再実行 |

**Cronサービスが停止している場合:**

```bash
systemctl status cron  # 状態確認
systemctl restart cron  # 再起動
```

---

### Q: 投稿ストックが0件になった

`mini_bulk_generator.py` を実行してストックを補充します:

```bash
# サーバー上で実行
cd /root/x-auto
./venv/bin/python mini_bulk_generator.py
```

または `knowledge.xlsx` を更新してからローカルで実行してConoHaにデプロイします。

---

### Q: Renderの診断ツールが「503」エラーになる

**原因1: Renderのスリープ（無料プランの場合）**

Renderの無料プランは、一定時間アクセスがないとスリープします。
30〜60秒待ってから再アクセスしてください。

**原因2: デプロイエラー**

1. `https://dashboard.render.com/` にログイン
2. 対象サービスを選択
3. 「Logs」タブでエラーメッセージを確認

---

### Q: デプロイスクリプトで「Permission denied (publickey)」エラー

SSH鍵のパスまたはパーミッションに問題があります:

```bash
# パーミッションを修正（Git Bashで実行）
chmod 600 "/c/Users/yotak/Documents/x-auto/key-*.pem"

# SSH接続テスト
ssh -i "/c/Users/yotak/Documents/x-auto/key-*.pem" -v root@[ConoHaのIP] exit
```

---

### Q: `.env` を誤ってGitにコミットしてしまった

**直ちに以下を実行:**

```bash
# GitのキャッシュからRemove（ファイル自体は残す）
git rm --cached .env
git rm --cached "**/.env"

# コミット
git commit -m "chore: remove accidentally committed .env files"
```

**さらに、影響を受けたAPIキーをすべて再発行してください:**

- Gemini API Key → Google AI Studio で再発行
- X (Twitter) API Key → developer.twitter.com で再発行

キーを再発行したら、ConoHaの `.env` ファイルとRenderの環境変数を更新してください。

---

### Q: `migrate_local.py` を再実行したら既存ファイルが消えた

消えていません。`shutil.copytree` の `dirs_exist_ok=True` オプションは
「上書きコピー」を行います。

- ソースに存在するファイル: ソース側の内容で上書き
- ソースに存在しないファイル: そのまま残る（削除されない）
- ソースと内容が同じファイル: 変更なし

---

### Q: ConoHaのサーバーに接続できない

```bash
# 接続テスト（タイムアウト5秒）
ssh -i "$SSH_KEY" -o ConnectTimeout=5 ${CONOHA_USER}@${CONOHA_HOST} echo "接続成功"
```

接続できない場合:
1. ConoHaの管理パネルでサーバーが起動していることを確認
2. IPアドレスが正しいことを確認（`CONOHA_HOST` の値）
3. ConoHaのファイアウォール設定でSSH（ポート22）が許可されているか確認

---

*このマニュアルは運用上の疑問が生じるたびに更新してください。*  
*不明点はエンジニアに相談し、解決策をこのファイルに追記してください。*
