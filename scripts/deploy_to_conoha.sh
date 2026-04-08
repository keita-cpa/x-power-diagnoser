#!/usr/bin/env bash
# scripts/deploy_to_conoha.sh
#
# apps/auto-poster/ を ConoHa VPS へ rsync でデプロイする。
#
# 使用法:
#   bash scripts/deploy_to_conoha.sh --dry-run   # プレビュー（推奨: 最初に実行）
#   bash scripts/deploy_to_conoha.sh             # 実際にデプロイ
#
# 必須環境変数（実行前に export してください）:
#   export CONOHA_USER="root"
#   export CONOHA_HOST="133.xxx.xxx.xxx"
#   export CONOHA_DEPLOY_PATH="/root/x-auto"
#   export SSH_KEY="/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem"

set -euo pipefail

# ── 設定変数（環境変数で上書き可能）────────────────────────────
CONOHA_USER="${CONOHA_USER:-}"
CONOHA_HOST="${CONOHA_HOST:-}"
CONOHA_DEPLOY_PATH="${CONOHA_DEPLOY_PATH:-}"
SSH_KEY="${SSH_KEY:-}"

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
  echo "  export CONOHA_USER=\"root\""
  echo "  export CONOHA_HOST=\"xxx.xxx.xxx.xxx\""
  echo "  export CONOHA_DEPLOY_PATH=\"/root/x-auto\""
  echo "  export SSH_KEY=\"/c/Users/yotak/.../key-*.pem\"  # SSH鍵がある場合"
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
  "--exclude=data/analytics/*.csv"  # 本番分析データ
  "--exclude=data/raw/"
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
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
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
echo "1. ConoHaに接続して動作確認:"
echo "   ssh ${SSH_KEY:+-i ${SSH_KEY}} ${CONOHA_USER}@${CONOHA_HOST}"
echo "   cd ${CONOHA_DEPLOY_PATH}"
echo "   ./venv/bin/python conoha_worker.py"
echo ""
echo "2. Cronが正しいパスを指しているか確認:"
echo "   crontab -l"
echo "   期待されるパス: ${CONOHA_DEPLOY_PATH}/conoha_worker.py"
echo ""
echo "3. ログで直近の投稿を確認:"
echo "   tail -20 ${CONOHA_DEPLOY_PATH}/logs/cron.log"
