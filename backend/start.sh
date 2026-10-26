#!/bin/bash
# 启动后端服务

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 激活虚拟环境
if [ -d "venv/bin" ]; then
    source venv/bin/activate
elif [ -d "venv/Scripts" ]; then
    source venv/Scripts/activate
else
    echo "错误: 未找到虚拟环境 venv/"
    exit 1
fi

# 启动 uvicorn（--no-access-log 关闭每请求日志）
python -m uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8000 --no-access-log
