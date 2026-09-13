#!/usr/bin/env bash
# SQLite 滚动备份（spec/09 §4）：每小时一份，保留 24 份。
#
# 用 `.backup` 而不是 `cp`——WAL 模式下直接复制主文件可能拿到撕裂的快照。
#
# crontab: 0 * * * * /path/to/parallel-campus/ops/backup.sh >> /var/log/pc-backup.log 2>&1
set -euo pipefail

DB="${PC_DB:-/data/pc.db}"
DIR="${PC_BACKUP_DIR:-/data/backup}"
KEEP="${PC_BACKUP_KEEP:-24}"

mkdir -p "$DIR"
STAMP="$(date +%H)"
OUT="$DIR/pc-${STAMP}.db"

if [ ! -f "$DB" ]; then
  echo "[$(date -Is)] 找不到数据库 $DB，跳过" >&2
  exit 1
fi

sqlite3 "$DB" ".backup '$OUT'"
echo "[$(date -Is)] 已备份 → $OUT"

# 保留最近 $KEEP 份（按修改时间）
ls -1t "$DIR"/pc-*.db 2>/dev/null | tail -n "+$((KEEP + 1))" | while read -r old; do
  rm -f "$old"
  echo "[$(date -Is)] 清理旧备份 $old"
done
