#!/usr/bin/env bash
# 健康探测 + 两次连续失败告警（spec/09 §5）。
#
# 退出码：0 正常；1 本次失败；2 连续两次失败（应触发告警）。
#
# crontab: */5 * * * * /path/to/parallel-campus/ops/healthcheck.sh
set -uo pipefail

BASE="${PC_BASE_URL:-https://campus.example.com}"
STATE="${PC_HEALTH_STATE:-/tmp/pc-health.fail}"
WEBHOOK="${PC_ALERT_WEBHOOK:-}"

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/api/health" || echo 000)"

if [ "$code" = "200" ]; then
  rm -f "$STATE"
  exit 0
fi

# 记录失败次数
fails=0
[ -f "$STATE" ] && fails="$(cat "$STATE" 2>/dev/null || echo 0)"
fails=$((fails + 1))
echo "$fails" > "$STATE"

echo "[$(date -Is)] /api/health 返回 $code（连续 $fails 次）" >&2

if [ "$fails" -ge 2 ]; then
  msg="平行校园健康检查连续 ${fails} 次失败（HTTP ${code}）· ${BASE}"
  if [ -n "$WEBHOOK" ]; then
    curl -s --max-time 10 -X POST "$WEBHOOK" \
      -H 'Content-Type: application/json' \
      -d "{\"text\":\"${msg}\"}" >/dev/null 2>&1 || true
  fi
  exit 2
fi

exit 1
