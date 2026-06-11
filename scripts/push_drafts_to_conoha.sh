#!/usr/bin/env bash
# scripts/push_drafts_to_conoha.sh
#
# ingest_raw_contents.py が生成した outbox 差分CSVを ConoHa VPS へ転送し、
# 本番の stock_posts_draft.csv へ安全にマージする（管理ID/投稿文 照合・追記のみ）。
#
# 使用法:
#   bash scripts/push_drafts_to_conoha.sh --dry-run   # 送信対象のプレビュー（ネットワーク接続なし）
#   bash scripts/push_drafts_to_conoha.sh             # 実際に転送・マージ
#
# 必須環境変数（deploy_to_conoha.sh と共通）:
#   export CONOHA_USER="root"
#   export CONOHA_HOST="133.xxx.xxx.xxx"
#   export CONOHA_DEPLOY_PATH="/root/x-auto"
#   export SSH_KEY="/c/Projects/x-integrated-platform/apps/auto-poster/key-*.pem"
#
# 任意:
#   export CONOHA_PYTHON="./venv/bin/python"   # 既定: python3

set -euo pipefail

CONOHA_USER="${CONOHA_USER:-}"
CONOHA_HOST="${CONOHA_HOST:-}"
CONOHA_DEPLOY_PATH="${CONOHA_DEPLOY_PATH:-}"
SSH_KEY="${SSH_KEY:-}"
CONOHA_PYTHON="${CONOHA_PYTHON:-python3}"

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

mkdir -p "$SENT_DIR"

# ── 転送・マージ ───────────────────────────────────────────────
# shellcheck disable=SC2086
ssh ${SSH_OPTS} "${CONOHA_USER}@${CONOHA_HOST}" "mkdir -p '${CONOHA_DEPLOY_PATH}/data/inbox'"

FAIL=0
for f in "${PENDING[@]}"; do
  fname="$(basename "$f")"
  echo ""
  echo "[PUSH] ${fname} を転送中..."
  # shellcheck disable=SC2086
  if scp ${SSH_OPTS} "$f" "${CONOHA_USER}@${CONOHA_HOST}:${CONOHA_DEPLOY_PATH}/data/inbox/${fname}" \
     && ssh ${SSH_OPTS} "${CONOHA_USER}@${CONOHA_HOST}" \
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
