#!/usr/bin/env bash
# 递归转译热榜为校园事件，并把虚拟世界快进 N 个 tick（spec/09 §3 / §6）。
#
#   ./ops/warmup.sh                       # 默认 144 tick（3 虚拟日）
#   ./ops/warmup.sh 48                    # 1 虚拟日
#
# 144 tick ≈ 3 虚拟日，预计 40 分钟内跑完（取决于 LLM 速率）。
set -euo pipefail

BASE="${PC_BASE_URL:-http://localhost:8000}"
TOKEN="${PC_ADMIN_TOKEN:-dev-admin-token}"
TICKS="${1:-144}"

api() {
  curl -fsS -X "$1" "$BASE$2" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    "${@:3}"
}

echo "==> 拉取热榜并转译为事件"
api POST /api/admin/hot-pull | tee /dev/stderr

echo "==> 快进 $TICKS tick（约 $((TICKS / 48)) 虚拟日）"
api POST "/api/admin/fast-forward?ticks=${TICKS}" | tee /dev/stderr

echo "==> 检查预算与状态"
api GET /api/admin/status | tee /dev/stderr

echo
echo "提示：确认 llm_today.fail_streak == 0，且校园墙已累积 ≥10 帖。"
