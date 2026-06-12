# x-integrated-platform 運用マニュアル (SOP)

**対象読者**: エンジニア以外のオペレーター  
**最終更新**: 2026-06-12（ConoHa WING実環境への記載統一・ペルソナv2・ドロップ＆パース補充・リプライ運用を反映）  
**環境**: Windows 11 + Git Bash / ConoHa WING（共用レンタルサーバー） / Render (PaaS)

### ConoHa WING 本番環境（実測値・2026-06-12確認）

| 項目 | 値 |
|---|---|
| サーバー種別 | ConoHa **WING**（VPSではない・root権限なし） |
| SSHユーザー名 | `c9994802` |
| SSHホスト | `www1156.conoha.ne.jp` |
| SSHポート | **8022**（標準の22ではない。`ssh -p 8022` / `scp -P 8022`） |
| デプロイ先パス | `/home/c9994802/x-auto`（`~/x-auto`） |
| Python実行パス | `/usr/local/bin/python`（**Python 3.6.15**・仮想環境なし） |
| SSH秘密鍵 | `C:\Users\yotak\Documents\x-auto\key-2026-03-24-22-28.pem`（Git Bash表記: `/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem`） |
| Cronログ | `~/x-auto/cron_run.log`（**毎回上書き＝最新実行分のみ**） |

> **重要（Python 3.6制約）**: サーバー上でCron実行されるファイル
> （`conoha_worker.py` / `auto_poster.py` / `x_poster.py` / `prune_dead_posts.py` /
> `utils/merge_new_posts.py`）には Python 3.7以降の構文（`list[dict]` 注釈等）を
> 入れないこと。違反すると import 時に `TypeError` で自動投稿が止まる。

---

## 目次

1. [フォルダの役割説明](#1-フォルダの役割説明)
2. [運用カレンダーと日常確認](#2-運用カレンダーと日常確認)
3. [ConoHaへのデプロイ手順](#3-conohaへのデプロイ手順)
4. [ConoHaのCronパス変更手順](#4-conohaのcronパス変更手順)
5. [VercelのRoot Directory変更手順](#5-vercelのroot-directory変更手順)
6. [トラブルシューティング](#6-トラブルシューティング)
7. [死にポスト自動クレンジング手順](#7-死にポスト自動クレンジング手順)
8. [原稿補充の新フロー（ドロップ＆パース方式）](#8-原稿補充の新フロードロップパース方式2026-06-11導入)
9. [ペルソナv2「3つの顔」切替](#9-ペルソナv23つの顔切替2026-06-12promptspy-v6)
10. [sniper_radar リプライ運用手順](#10-sniper_radar-リプライ運用手順アクティブコミュニケーション)
11. [月次Analyticsとweightチューニング手順](#11-月次analyticsとweightチューニング手順)

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
│                              （ConoHa WINGサーバーで動作）
│
├── docs/
│   ├── knowledge/
│   │   ├── X_Algorithm/    ← Xの公式アルゴリズム解析（技術層・変更不可）
│   │   ├── X_Operations/   ← X運用ルール・機能ナレッジ（運用層・変更不可）
│   │   ├── Psychology/     ← 人蕩し術・話術の戦術原則（心理層・変更不可）
│   │   └── Claude_Mastery/ ← Claude Code設定集（参照資料・変更不可）
│   ├── MASTER_ARCHITECTURE.md ← システム設計書（戦略・ロードマップ）
│   └── SOP_Manual.md       ← このファイル（運用マニュアル）
│
├── scripts/
│   ├── migrate_local.py          ← データ移行スクリプト（初回のみ）
│   ├── deploy_to_conoha.sh       ← ConoHaへのデプロイスクリプト
│   └── push_drafts_to_conoha.sh  ← 補充原稿の差分を本番へ反映（§8）
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

ConoHa WINGサーバー上で動作しています。
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

## 2. 運用カレンダーと日常確認

### 2-0. 運用カレンダー（このシステムの全定期タスク）

| 頻度 | 所要 | タスク | 手順 |
|---|---|---|---|
| **日次** | 2分 | X投稿が正常に出ているか確認（§2-1） | §2-1 |
| **日次** | 5分 | 自分の投稿に届いたリプライへ**全返信**（著者返信=ReplyEngagedByAuthorシグナルで投稿スコアが二重加算） | — |
| **週次** | 15分 | `/project:sniper-run` → リプライ案レビュー → 手動送信 | §10 |
| **週次** | 1分 | ストック残数確認（cron_run.logに `[WARN] 原稿ストック残り` が出ていないか） | §2-1 |
| **月次** | 60分 | ① `/project:monthly-analytics` → ② weightチューニング → ③ 死にポスト処理 → ④ 原稿補充 → ⑤ 本番反映 | §11 → §7 → §8 |

> 月次タスクは毎月初旬にまとめて実施するのが効率的です（分析→改善→補充が1セット）。

### 2-1. X自動投稿システムの確認

**方法A: ブラウザから確認（簡単）**

Xのアカウントページを開き、直近の投稿が正常に行われているか確認します。

**方法B: サーバーログの確認（詳しく確認したい場合）**

1. Git Bashを開く（Windowsのスタートメニューで「Git Bash」を検索）
2. 以下のコマンドを入力してサーバーに接続（ポート8022に注意）:
   ```bash
   ssh -p 8022 -i "/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem" c9994802@www1156.conoha.ne.jp
   ```
3. 接続後、直近のログを確認（cron_run.log は毎回上書きされるため最新実行分のみ表示されます）:
   ```bash
   cat ~/x-auto/cron_run.log
   ```
4. 投稿ストックの残数を確認（**8件未満になると cron_run.log に `[WARN]` が自動出力されます**。補充は §8 の手順）:
   ```bash
   PYTHONIOENCODING=utf-8 /usr/local/bin/python -c "
   import csv
   with open('/home/c9994802/x-auto/data/drafts/stock_posts_draft.csv', encoding='utf-8-sig') as f:
       rows = list(csv.DictReader(f))
       empty = [r for r in rows if not r.get('ステータス')]
       print('未投稿ストック数: {}件'.format(len(empty)))
   "
   ```
   > `PYTHONIOENCODING=utf-8` はWINGのPython 3.6が日本語出力で
   > `UnicodeEncodeError` になるのを防ぐおまじないです（付け忘れてもデータは壊れません）。

### 2-2. X診断ツールの確認

1. ブラウザで以下にアクセス: `https://[あなたのRenderアプリURL]/api/health`
2. `{"status": "ok"}` が返れば正常
3. 返らない場合 → §6 トラブルシューティング を参照

---

## 3. ConoHaへのデプロイ手順

**デプロイが必要な場面:** `apps/auto-poster/` のPythonファイルを修正した後

### 前提条件

- Git Bashがインストールされていること
- SSH秘密鍵 `C:\Users\yotak\Documents\x-auto\key-2026-03-24-22-28.pem` が存在すること
- デプロイするPythonファイルが **Python 3.6互換**であること（冒頭の「ConoHa WING 本番環境」の重要注意を参照）

### 手順

**ステップ1: Git Bashを開く**

Windowsのスタートメニューで「Git Bash」を検索して起動します。

**ステップ2: 環境変数の設定は不要（既定値がWING本番に設定済み）**

`deploy_to_conoha.sh` には ConoHa WING の接続情報
（`c9994802@www1156.conoha.ne.jp`・ポート8022・`/home/c9994802/x-auto`・鍵パス）が
既定値として入っているため、そのまま実行できます。
別サーバーへ送りたい場合のみ環境変数で上書きします:

```bash
export CONOHA_USER="c9994802"
export CONOHA_HOST="www1156.conoha.ne.jp"
export CONOHA_PORT="8022"
export CONOHA_DEPLOY_PATH="/home/c9994802/x-auto"
export SSH_KEY="/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem"
```

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

構文チェック（import確認）のみを行います。`conoha_worker.py` を手動で直接実行すると
Cronと二重で投稿が走る可能性があるため、手動実行はしません。

```bash
ssh -p 8022 -i "/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem" c9994802@www1156.conoha.ne.jp \
  "cd ~/x-auto && /usr/local/bin/python -m py_compile conoha_worker.py auto_poster.py x_poster.py utils/merge_new_posts.py && echo OK"
```

`OK` が表示されれば成功です。その後、次のCron実行（最大5分後）の `cron_run.log` と
Xの投稿を確認してください。

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
ssh -p 8022 -i "/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem" c9994802@www1156.conoha.ne.jp
```

**ステップ2: 現在のCron設定を確認する**

```bash
crontab -l
```

以下のような行が表示されます（2026-06-12時点の本番設定）:

```
*/5 * * * * cd ~/x-auto && /usr/local/bin/python conoha_worker.py > cron_run.log 2>&1
```

> **メモ**: WINGでは仮想環境（venv）を使わず、標準の `/usr/local/bin/python` で実行します。
> Cronは ConoHa WING のコントロールパネル（サーバー管理 → Cron）からも編集できます。

**ステップ3: Cron設定を編集する**

```bash
crontab -e
```

`nano`というテキストエディタが開きます。

**ステップ4: パスを変更する**

矢印キーでカーソルを移動して、変更が必要な部分を書き換えます。

変更例:
- **変更前**: `cd ~/x-auto && /usr/local/bin/python conoha_worker.py`
- **変更後**: `cd ~/新しいフォルダ名 && /usr/local/bin/python conoha_worker.py`

**ステップ5: 保存して終了する**

1. `Ctrl + O` キーを押す（保存）
2. `Enter` キーを押す（ファイル名を確認）
3. `Ctrl + X` キーを押す（終了）

**ステップ6: 変更を確認する**

```bash
crontab -l
```

変更後のパスが表示されれば成功です。

**ステップ7: 動作確認（構文チェック）**

```bash
cd ~/x-auto && /usr/local/bin/python -m py_compile conoha_worker.py && echo OK
```

`OK` が出れば成功です。次のCron実行（最大5分後）の `cron_run.log` とXの投稿を確認してください。

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
# サーバーに接続（ポート8022）
ssh -p 8022 -i "/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem" c9994802@www1156.conoha.ne.jp

# ログを確認（cron_run.log は毎回上書き＝最新実行分のみ）
cat ~/x-auto/cron_run.log

# 構文・importエラーがないか確認
cd ~/x-auto
/usr/local/bin/python -m py_compile conoha_worker.py auto_poster.py x_poster.py && echo OK
```

**よくある原因と解決策:**

| エラーメッセージ | 原因 | 解決策 |
|---|---|---|
| `ModuleNotFoundError` | Pythonライブラリが不足 | `/usr/local/bin/python -m pip install --user ライブラリ名` |
| `TypeError: 'type' object is not subscriptable` | Python 3.7+の構文（`list[dict]`等）をデプロイした | 該当ファイルを3.6互換に修正して再デプロイ（冒頭の重要注意を参照） |
| `UnicodeEncodeError: 'ascii' codec ...` | 日本語printがASCII端末で失敗 | コマンドの先頭に `PYTHONIOENCODING=utf-8 ` を付ける |
| `FileNotFoundError: stock_posts_draft.csv` | 投稿ストックファイルが存在しない | §8 のドロップ＆パース補充で再生成 |
| `tweepy.errors.Unauthorized` | X APIキーが無効 | `config.py` のAPIキーを確認・更新 |
| `JSONDecodeError` | `schedule.json` が破損 | `schedule.json` を削除して再実行 |

**Cronが動いていない様子の場合:**

WINGは共用サーバーのためroot権限がなく、`systemctl` は使えません。
`crontab -l` で登録行が残っているか確認し、消えている場合は
ConoHa WING コントロールパネル（サーバー管理 → Cron）から再登録してください。

---

### Q: 投稿ストックが0件になった

§8 のドロップ＆パース方式でローカルで原稿を作成し、
`bash scripts/push_drafts_to_conoha.sh` で本番へマージします（推奨・コスト最安）。

> **注意**: サーバー上での `mini_bulk_generator.py` 実行は行いません。
> ローカル最新版はPython 3.9構文を含み、WINGのPython 3.6では動かないためです。
> 生成系スクリプトはすべてローカルで実行し、CSV差分だけをpushする運用です。

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
chmod 600 "/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem"

# SSH接続テスト（ポート8022）
ssh -p 8022 -i "/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem" -v c9994802@www1156.conoha.ne.jp exit
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
ssh -p 8022 -i "/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem" -o ConnectTimeout=5 c9994802@www1156.conoha.ne.jp echo "接続成功"
```

接続できない場合:
1. ポートが **8022** になっているか確認（標準の22では接続できません）
2. ホスト名 `www1156.conoha.ne.jp`・ユーザー名 `c9994802` が正しいか確認
3. ConoHa WING コントロールパネルで「SSH」が有効になっているか確認
   （WINGのSSHは接続元IP制限がかかる場合があります。回線変更後に繋がらなくなったら
   コントロールパネルのSSH設定を確認）

---

---

## 7. 死にポスト自動クレンジング手順

**目的**: 投稿から48時間以上経過し、AlgoScore下位10%かつプロフクリック0の
「完全に死んでいるポスト」を月1回特定し、ConoHa上のCronで自動削除する。

**頻度**: 月1回（月次分析と同じタイミングで実施）

---

### ステップ1: 月次分析スキルを実行する（VS Code ターミナル）

VS Codeのターミナル（`` Ctrl+` ``）を開き、以下を実行します。

```bash
cd C:/Projects/x-integrated-platform/apps/auto-poster
```

その後、コマンドパレット（`Ctrl+Shift+P`）から **「Claude: Run Command」** を選択するか、
ターミナルで `/project:monthly-analytics` を実行します。

分析が完了すると、**Step 5** が自動的に以下のファイルを生成します:

```
apps/auto-poster/data/analytics/dead_posts_queue.csv
```

ターミナルに `[OK] 死にポスト X件 を data/analytics/dead_posts_queue.csv に出力しました` と
表示されれば成功です。

> **「死にポストは検出されませんでした」と表示された場合**  
> 削除対象がない状態です。以降のステップは不要です。

---

### ステップ2: 削除対象を目視確認する（VS Code エディタ）

1. VS Code のエクスプローラーで
   `apps/auto-poster/data/analytics/dead_posts_queue.csv` をクリックして開きます。

2. 表示された一覧（ポストID・投稿日・本文先頭20文字）を確認します。

3. **削除したくないポストがある場合**: その行全体を選択して削除（`Delete` キー）し、
   `Ctrl+S` で保存します。

4. ファイルを閉じます。

5. `dead_posts_queue.csv` を ConoHa WING に転送します（scpのポート指定は大文字 `-P`）:

   ```bash
   # Git Bash で実行
   scp -P 8022 -i "/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem" \
     apps/auto-poster/data/analytics/dead_posts_queue.csv \
     c9994802@www1156.conoha.ne.jp:/home/c9994802/x-auto/data/analytics/dead_posts_queue.csv
   ```

> **注意**: `dead_posts_queue.csv` は `.gitignore` 対象のため Git ではなく
> `scp` コマンドで直接転送します。

---

### ステップ3: ConoHa Cron 設定（初回のみ）

ConoHa サーバーに SSH で接続し、Cron に削除ワーカーを登録します。

**接続:**

```bash
ssh -p 8022 -i "/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem" c9994802@www1156.conoha.ne.jp
```

**dry-run で事前確認（推奨）:**

```bash
cd ~/x-auto
PYTHONIOENCODING=utf-8 /usr/local/bin/python prune_dead_posts.py --dry-run
```

`[DRY-RUN] 削除予定: ID=...` が表示されれば正常です。
`dead_posts_queue.csv` は変更されません。

**Cron への登録:**

```bash
crontab -e
```

以下の1行を追加します（毎時0分に最大2件ずつ削除）:

```
0 * * * * cd ~/x-auto && PYTHONIOENCODING=utf-8 /usr/local/bin/python prune_dead_posts.py >> prune.log 2>&1
```

保存して終了（`Ctrl+O` → `Enter` → `Ctrl+X`）。

**登録確認:**

```bash
crontab -l
```

追加した行が表示されれば成功です。

---

### 削除履歴の確認方法

削除済みポストの履歴は以下のファイルに記録されています:

```bash
# ConoHa サーバー上で確認
tail -20 ~/x-auto/data/analytics/pruned_log.txt
```

出力例:
```
2026-04-18 10:00:01 [DELETED] ID=1234567890 | 投稿日=2026-04-10 | 本文=メンズエステが税務調...
2026-04-18 11:00:05 [DELETED] ID=9876543210 | 投稿日=2026-04-09 | 本文=確定申告の時期に気を...
```

---

### キューが空になった場合の Cron 挙動

`dead_posts_queue.csv` が空（または存在しない）場合、ワーカーは
`[INFO] dead_posts_queue.csv が空またはファイルが存在しません。` を出力して
正常終了します。エラーにはなりません。

---

## 8. 原稿補充の新フロー（ドロップ＆パース方式・2026-06-11導入）

従量APIでの生成（1投稿4〜7円）に代わり、定額プラン（NotebookLM / Gemini ULTRA Web）の出力を
取り込む方式。コストはQC審査のみ（約1円/投稿）。

### 手順（月1回・約5分の手作業＋自動処理）

1. **マスタープロンプトを出力**（カテゴリ・ペルソナは prompts.py と自動同期）:
   ```bash
   cd apps/auto-poster
   python ingest_raw_contents.py --print-prompt --count 12
   ```
2. 出力されたプロンプトを **NotebookLM**（法令ナレッジをソース登録済みのノート推奨）または
   **Gemini ULTRA Web** に貼り付けて生成させる
3. 生成結果を **`apps/auto-poster/data/raw_contents/` に .txt で保存**
4. **取り込み実行**（または Claude Code で `/project:ingest-drafts`）:
   ```bash
   python ingest_raw_contents.py --dry-run   # プレビュー（CSV変更なし）
   python ingest_raw_contents.py             # 本実行（QC審査つき・CSV追記・outbox差分生成）
   ```
   - 不合格は `raw_contents/rejected/` に理由ログ付きで隔離される
5. **本番（ConoHa）反映**:
   ```bash
   bash scripts/push_drafts_to_conoha.sh --dry-run   # 送信対象の確認
   bash scripts/push_drafts_to_conoha.sh             # scp → ConoHa側で管理ID照合マージ（冪等・再実行安全）
   ```

### 注意
- `push_drafts_to_conoha.sh` には WING の接続情報（ポート8022・`/usr/local/bin/python` での
  マージ実行）が既定値として組み込まれているため、環境変数の設定は不要
- Web版のRPA自動操作（Chrome MCP等）は**規約違反で定額アカウントBANリスクがあるため禁止**
  （この方式を採用した経緯: docs/MASTER_ARCHITECTURE.md §7）
- ConoHa側の `stock_posts_draft.csv` が常に正。マージは追記のみで `posted` ステータスに触れない
- ストックが8件未満になると conoha_worker.py がcronログに `[WARN]` を出す

---

## 9. ペルソナv2「3つの顔」切替（2026-06-12・prompts.py v6）

カテゴリ体系を全面刷新（経緯と設計: `docs/MASTER_ARCHITECTURE.md` §6、ルール: `.claude/rules/persona.md`）。

### 新旧カテゴリ対応表（月次Analytics比較時に必須）

| 旧カテゴリ（v5以前） | 新カテゴリ（v6） | 備考 |
|---|---|---|
| 日常・利用者としての共感 | 良客の目線・メンエス愛 | 実測TOP型（AlgoScore=124）の直系 |
| マインド・喝 | 痛みの代弁・がんばりの承認 | 説教廃止・代弁技術のみ継承 |
| 税務ノウハウ / Q&A / リスク警告 | お金と法律のお守り | 3カテゴリを統合 |
| 防衛実績・事例 | 施術中のワンシーン・そっと解決 | 手柄話→相手の安堵の一場面へ転換 |
| （新設） | 趣味・人間味・日常 | 肩書きゼロの「話すと楽しい人」 |

- 切替直後は旧カテゴリの既存ストックと新規生成が数日混在する（許容済み・投稿動作に影響なし）
- **次回 monthly-analytics では新旧カテゴリを別集計**し、新カテゴリの初回実測で weight を v7 チューニングすること

---

## 10. sniper_radar リプライ運用手順（アクティブコミュニケーション）

**目的**: 狙ったセラピストのポストへ「法的・税務的ファクトで擁護するリプライ」を送り、
1対1の信頼関係を作る。**リプライの実測AlgoScoreはメイン投稿の8.3倍**（全AlgoScoreの89%が
リプライ由来）であり、本システムで最も費用対効果の高い運用タスク。

### 手順（週1回・約15分）

1. **起案を実行**（Claude Code で）:
   ```
   /project:sniper-run
   ```
   VIPアカウントの最新ポストを取得 → AIがリプライ案を起案 → `data/logs/scouted_targets.csv` に出力されます。

2. **レビュー**: VS Code で `scouted_targets.csv` を開き、各リプライ案を確認します。
   - ペルソナv2準拠か（媚びていないか・具体的な事実への言及があるか・「彼女」が混入していないか）
   - 必要なら文面を直接修正

3. **送信は必ず手動で行う**（Xアプリ/Webからコピペ投稿）。
   > **なぜ自動送信しないのか**: Xの自動化ルールでは、リプライ・メンションの自動送信は
   > 「相手がメッセージを求めている／過去に交流がある」ことが条件です。違反は凍結リスクが
   > あるため、本システムは設計として「起案まで」に留めています
   > （詳細: `docs/knowledge/X_Operations/rules/20260408_X自動化開発ルール.md`）。

4. **送信後**: 相手から返信が来たら必ず返す（1対1の交流実績は将来の自動化条件の面でも資産になる）。

### VIPリストの管理

- 編集場所: `apps/auto-poster/sniper_radar.py` の `TARGET_ACCOUNTS`
- 選定基準（ペルソナv2）: **哲学・人間味・仕事への姿勢を発信しているセラピスト**を優先。
  発信に固有のディテールがある人ほど「具体的な事実への言及」で自己重要感を満たすリプライが書ける
- セラピスト/業界系はプロフィールクリック率1.4〜2.4%（一般アカウントの約20倍）

---

## 11. 月次Analyticsとweightチューニング手順

**目的**: 実測データ（AlgoScore）に基づいて投稿カテゴリの配信比率（weight）を進化させる
「自己進化ループ」を月1回まわす。

### 手順（月1回・約30分）

1. **X Analytics から CSV をダウンロード**し、`apps/auto-poster/data/analytics/raw/` に置く
   （ファイル名は `account_analytics_content_*.csv` のまま）

2. **分析を実行**（Claude Code で）:
   ```
   /project:monthly-analytics
   ```
   AlgoScore算出 → カテゴリ別集計 → 月次レポート（`data/analytics/monthly_report_YYYY-MM-DD.md`）
   → 死にポストキュー生成（→ §7 へ続く）まで自動で行われます。

3. **新旧カテゴリの別集計を確認**（v6切替後の初回は特に重要）:
   - 旧カテゴリ（切替前のストック分）と新カテゴリ（v6生成分）を混ぜて評価しないこと
   - 対応表は §9 を参照

4. **weight改定の判断ルール（厳守）**:
   - 実測 AlgoScore/件 の高低に基づき **±2〜5 の小幅調整**に留める
   - **実測のない投機的変更は禁止**
   - 外れ値1件でカテゴリ平均が急変動することがある（過去に34.0→3.3の乱高下の実例あり）。
     大幅変更は**2期連続で同じ傾向**が出てから行うこと

5. **prompts.py を更新**:
   - `POST_CATEGORIES` の weight を改定
   - ファイル冒頭のバージョンコメントに「変更根拠（実測値つき）」を必ず追記（v7, v8…と採番）
   - カテゴリプロンプト内の実績根拠も必要に応じて更新

6. **反映**: commit → `bash scripts/deploy_to_conoha.sh --dry-run` で確認 → 本番デプロイ

---

*このマニュアルは運用上の疑問が生じるたびに更新してください。*  
*不明点はエンジニアに相談し、解決策をこのファイルに追記してください。*
