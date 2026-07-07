#!/usr/bin/env bash
# scripts/deploy_to_conoha.sh
#
# apps/auto-poster/ を ConoHa WING へ rsync でデプロイする。
#
# 使用法:
#   bash scripts/deploy_to_conoha.sh --dry-run   # プレビュー（推奨: 最初に実行）
#   bash scripts/deploy_to_conoha.sh             # 実際にデプロイ
#
# 既定値は ConoHa WING 本番環境（環境変数で上書き可能）:
#   CONOHA_USER="c9994802"
#   CONOHA_HOST="www1156.conoha.ne.jp"
#   CONOHA_PORT="8022"                          # WINGのSSHポート（22ではない）
#   CONOHA_DEPLOY_PATH="/home/c9994802/x-auto"
#   SSH_KEY="/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem"
#
# 警告: WINGの実行環境は /usr/local/bin/python = Python 3.6.15（仮想環境なし）。
#       サーバー上でCron実行されるファイル（conoha_worker.py / auto_poster.py /
#       x_poster.py / prune_dead_posts.py / utils/merge_new_posts.py）に
#       Python 3.7以降の構文（list[dict]注釈・walrus演算子等）を入れないこと。

set -euo pipefail

# ── 設定変数（環境変数で上書き可能）────────────────────────────
CONOHA_USER="${CONOHA_USER:-c9994802}"
CONOHA_HOST="${CONOHA_HOST:-www1156.conoha.ne.jp}"
CONOHA_PORT="${CONOHA_PORT:-8022}"
CONOHA_DEPLOY_PATH="${CONOHA_DEPLOY_PATH:-/home/c9994802/x-auto}"
SSH_KEY="${SSH_KEY:-/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem}"

MONOREPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${MONOREPO_ROOT}/apps/auto-poster/"

# ── 引数解析 ───────────────────────────────────────────────────
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    *) echo "[ERROR] 不明な引数: $arg"; exit 1 ;;
  esac
done

# ── 必須変数チェック ───────────────────────────────────────────
if [[ -z "$CONOHA_USER" || -z "$CONOHA_HOST" || -z "$CONOHA_DEPLOY_PATH" ]]; then
  echo "======================================================"
  echo "[ERROR] 以下の環境変数を設定してください:"
  echo "======================================================"
  echo "  export CONOHA_USER=\"c9994802\""
  echo "  export CONOHA_HOST=\"www1156.conoha.ne.jp\""
  echo "  export CONOHA_PORT=\"8022\""
  echo "  export CONOHA_DEPLOY_PATH=\"/home/c9994802/x-auto\""
  echo "  export SSH_KEY=\"/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem\""
  exit 1
fi

# ── ソースディレクトリの存在確認 ──────────────────────────────
if [[ ! -d "$SRC" ]]; then
  echo "[ERROR] ソースディレクトリが存在しません: ${SRC}"
  echo "先に python scripts/migrate_local.py を実行してください"
  exit 1
fi

# ── rsync 除外リスト ───────────────────────────────────────────
# 重要: これらのファイルは絶対にConoHaへ送信しない
EXCLUDES=(
  "--exclude=.claude/"              # AIコンテキスト（機密）
  "--exclude=.git/"                 # Gitメタデータ
  "--exclude=.gitignore"
  "--exclude=.env"                  # シークレット（絶対除外）
  "--exclude=.env.*"                # .env.local 等も除外
  "--exclude=venv/"                 # 仮想環境（ConoHa側で別管理）
  "--exclude=__pycache__/"
  "--exclude=*.pyc"
  "--exclude=*.pyo"
  "--exclude=node_modules/"
  "--exclude=data/drafts/*.csv"     # 本番投稿データ（ConoHa側が正）
  "--exclude=data/logs/*.csv"       # 本番ログ（ConoHa側が正）
  "--exclude=data/analytics/"        # 分析データ全体（ConoHa不要・pruned_log.txtはConoHa側が正）
  "--exclude=data/raw/"
  "--exclude=data/raw_contents/"    # ローカル取り込み用（Web LLM出力置き場）
  "--exclude=data/outbox/"          # ローカル差分push待機場所
  "--exclude=data/inbox/"           # ConoHa側のマージ受信箱（--delete から保護）
  "--exclude=schedule.json"         # ランタイム状態（ConoHa側が正）
  "--exclude=*.pem"                 # SSH秘密鍵（絶対除外）
  "--exclude=tone_sample_*.txt"     # 個人情報
  "--exclude=自動生成用ナレッジ/"   # ローカルナレッジ
  "--exclude=drafts/"               # ローカル下書き
  "--exclude=docs/"                 # ドキュメント（不要）
  "--exclude=*.log"
  "--exclude=temp_post_image.jpg"
)

# ── SSH オプション ─────────────────────────────────────────────
# WINGのSSHはポート8022（ssh は -p / scp は -P で指定）
SSH_OPTS="-p ${CONOHA_PORT} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTS="${SSH_OPTS} -i ${SSH_KEY}"
fi

# ── rsync コマンド構築 ─────────────────────────────────────────
RSYNC_CMD=(
  rsync
  -avz
  --delete          # ConoHa上の不要ファイルを同期削除（exclude対象は保護）
  --checksum        # タイムスタンプではなくチェックサムで差分検出
  "${EXCLUDES[@]}"
  -e "ssh ${SSH_OPTS}"
  "$SRC"
  "${CONOHA_USER}@${CONOHA_HOST}:${CONOHA_DEPLOY_PATH}/"
)

# ── dry-run モード ─────────────────────────────────────────────
if $DRY_RUN; then
  echo "======================================================"
  echo "[DRY-RUN] 以下の内容でデプロイが実行されます"
  echo "======================================================"
  echo "  送信元 : ${SRC}"
  echo "  送信先 : ${CONOHA_USER}@${CONOHA_HOST}:${CONOHA_DEPLOY_PATH}/"
  echo "  SSH鍵  : ${SSH_KEY:-なし（デフォルト鍵を使用）}"
  echo "======================================================"
  echo ""
  echo "[確認] .env や *.pem が以下のリストに含まれていないことを確認してください:"
  echo ""
  "${RSYNC_CMD[@]}" --dry-run
  echo ""
  echo "======================================================"
  echo "[DRY-RUN 完了]"
  echo "上記のファイルリストに .env / *.pem / *.csv が含まれていないことを確認後、"
  echo "  bash scripts/deploy_to_conoha.sh"
  echo "を実行してください"
  echo "======================================================"
  exit 0
fi

# ── 本番デプロイ確認プロンプト ────────────────────────────────
echo "======================================================"
echo "[WARNING] 本番デプロイを実行します"
echo "======================================================"
echo "  送信元 : ${SRC}"
echo "  送信先 : ${CONOHA_USER}@${CONOHA_HOST}:${CONOHA_DEPLOY_PATH}/"
echo ""
echo "デプロイ前チェックリスト:"
echo "  [ ] --dry-run で内容を確認済みか?"
echo "  [ ] ConoHa上の cron が一時停止不要か（上書きデプロイのため通常不要）"
echo "  [ ] data/*.csv と schedule.json が除外リストにあることを確認済みか?"
echo "  [ ] サーバーでCron実行されるファイルが Python 3.6 互換か?（WINGは3.6.15）"
echo "======================================================"
echo -n "本当に実行しますか？ (yes/no): "
read -r CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
  echo "[ABORT] デプロイをキャンセルしました"
  exit 0
fi

# ── デプロイ実行 ───────────────────────────────────────────────
echo ""
echo "[DEPLOY] rsync 開始..."
"${RSYNC_CMD[@]}"

echo ""
echo "======================================================"
echo "[DEPLOY 完了]"
echo "======================================================"
echo ""
echo "次のステップ:"
echo "1. ConoHaに接続して構文チェック（投稿は走らせない）:"
echo "   ssh -p ${CONOHA_PORT} ${SSH_KEY:+-i ${SSH_KEY}} ${CONOHA_USER}@${CONOHA_HOST}"
echo "   cd ${CONOHA_DEPLOY_PATH}"
echo "   /usr/local/bin/python -m py_compile conoha_worker.py auto_poster.py x_poster.py"
echo ""
echo "2. Cronが正しいパスを指しているか確認:"
echo "   crontab -l"
echo "   期待される行: cd ~/x-auto && /usr/local/bin/python conoha_worker.py > cron_run.log 2>&1"
echo ""
echo "3. ログで直近の実行を確認（cron_run.log は毎回上書き＝最新実行分のみ）:"
echo "   cat ${CONOHA_DEPLOY_PATH}/cron_run.log"
