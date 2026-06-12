#!/usr/bin/env bash
# scripts/push_drafts_to_conoha.sh
#
# ingest_raw_contents.py が生成した outbox 差分CSVを ConoHa WING へ転送し、
# 本番の stock_posts_draft.csv へ安全にマージする（管理ID/投稿文 照合・追記のみ）。
#
# 使用法:
#   bash scripts/push_drafts_to_conoha.sh --dry-run   # 送信対象のプレビュー（ネットワーク接続なし）
#   bash scripts/push_drafts_to_conoha.sh             # 実際に転送・マージ
#
# 既定値は ConoHa WING 本番環境（環境変数で上書き可能）:
#   CONOHA_USER="c9994802"
#   CONOHA_HOST="www1156.conoha.ne.jp"
#   CONOHA_PORT="8022"                          # WINGのSSHポート（22ではない）
#   CONOHA_DEPLOY_PATH="/home/c9994802/x-auto"
#   SSH_KEY="/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem"
#   CONOHA_PYTHON="/usr/local/bin/python"       # WING標準Python（3.6.15）
#
# 注意: WINGのPythonは 3.6.15。サーバーで実行するスクリプトは3.6互換構文のみ。

set -euo pipefail

CONOHA_USER="${CONOHA_USER:-c9994802}"
CONOHA_HOST="${CONOHA_HOST:-www1156.conoha.ne.jp}"
CONOHA_PORT="${CONOHA_PORT:-8022}"
CONOHA_DEPLOY_PATH="${CONOHA_DEPLOY_PATH:-/home/c9994802/x-auto}"
SSH_KEY="${SSH_KEY:-/c/Users/yotak/Documents/x-auto/key-2026-03-24-22-28.pem}"
CONOHA_PYTHON="${CONOHA_PYTHON:-/usr/local/bin/python}"

MONOREPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTBOX_DIR="${MONOREPO_ROOT}/apps/auto-poster/data/outbox"
SENT_DIR="${OUTBOX_DIR}/sent"

# ── 引数解析 ───────────────────────────────────────────────────
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    *) echo "[ERROR] 不明な引数: $arg"; exit 1 ;;
  esac
done

# ── 送信対象の確認 ─────────────────────────────────────────────
shopt -s nullglob
PENDING=("${OUTBOX_DIR}"/new_posts_*.csv)
shopt -u nullglob

if [[ ${#PENDING[@]} -eq 0 ]]; then
  echo "[INFO] 送信対象なし: ${OUTBOX_DIR} に未送信の差分CSVがありません"
  echo "[INFO] 先に python apps/auto-poster/ingest_raw_contents.py を実行してください"
  exit 0
fi

echo "======================================================"
echo "  outbox 差分push: ${#PENDING[@]} ファイル"
echo "======================================================"
for f in "${PENDING[@]}"; do
  rows=$(($(wc -l < "$f") - 1))
  echo "  - $(basename "$f") (${rows}行)"
done

if $DRY_RUN; then
  echo ""
  echo "[DRY-RUN] 実行される処理:"
  echo "  1. scp で \$CONOHA_DEPLOY_PATH/data/inbox/ へ転送"
  echo "  2. ssh で ${CONOHA_PYTHON} utils/merge_new_posts.py を実行（管理ID照合マージ）"
  echo "  3. 成功したファイルをローカルの outbox/sent/ へ移動"
  echo "[DRY-RUN 完了] 実行するには --dry-run を外してください"
  exit 0
fi

# ── 必須変数チェック（実転送時のみ）────────────────────────────
if [[ -z "$CONOHA_USER" || -z "$CONOHA_HOST" || -z "$CONOHA_DEPLOY_PATH" ]]; then
  echo "[ERROR] 環境変数を設定してください: CONOHA_USER / CONOHA_HOST / CONOHA_DEPLOY_PATH"
  exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTS="${SSH_OPTS} -i ${SSH_KEY}"
fi
# ssh は -p / scp は -P でポート指定（WINGは8022）
SSH_CMD_OPTS="${SSH_OPTS} -p ${CONOHA_PORT}"
SCP_CMD_OPTS="${SSH_OPTS} -P ${CONOHA_PORT}"

mkdir -p "$SENT_DIR"

# ── 転送・マージ ───────────────────────────────────────────────
# shellcheck disable=SC2086
ssh ${SSH_CMD_OPTS} "${CONOHA_USER}@${CONOHA_HOST}" "mkdir -p '${CONOHA_DEPLOY_PATH}/data/inbox'"

FAIL=0
for f in "${PENDING[@]}"; do
  fname="$(basename "$f")"
  echo ""
  echo "[PUSH] ${fname} を転送中..."
  # shellcheck disable=SC2086
  if scp ${SCP_CMD_OPTS} "$f" "${CONOHA_USER}@${CONOHA_HOST}:${CONOHA_DEPLOY_PATH}/data/inbox/${fname}" \
     && ssh ${SSH_CMD_OPTS} "${CONOHA_USER}@${CONOHA_HOST}" \
          "cd '${CONOHA_DEPLOY_PATH}' && ${CONOHA_PYTHON} utils/merge_new_posts.py 'data/inbox/${fname}'"; then
    mv "$f" "${SENT_DIR}/${fname}"
    echo "[OK] ${fname} をマージ完了 → outbox/sent/ へ移動"
  else
    echo "[ERROR] ${fname} の転送またはマージに失敗（outboxに残します）"
    FAIL=1
  fi
done

echo ""
echo "======================================================"
if [[ $FAIL -eq 0 ]]; then
  echo "[完了] すべての差分を本番へ反映しました"
else
  echo "[警告] 一部のファイルが失敗しました。再実行してください（マージは冪等で安全）"
  exit 1
fi
echo "======================================================"
