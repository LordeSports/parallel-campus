#!/bin/sh
set -eu

# Compose 的 bind mount 可能由宿主机以 root 创建；确保运行用户能写 SQLite
# 数据卷及 WAL/SHM 文件，然后降权执行应用进程。
mkdir -p /data
chown -R app:app /data

exec gosu app "$@"
