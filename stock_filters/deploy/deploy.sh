#!/bin/bash
# stock-filters 部署脚本
# 用法: bash deploy.sh [install|uninstall|status|logs]

set -e

APP_NAME="stock-filters"
APP_DIR="/opt/stock_filters"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"

install() {
    echo "=== 安装 ${APP_NAME} ==="

    # 1. 创建用户（如果不存在）
    if ! id -u stock &>/dev/null; then
        echo "创建服务用户 stock..."
        sudo useradd -r -s /sbin/nologin stock
    fi

    # 2. 同步代码（如果 APP_DIR 已存在则更新）
    if [ -d "${APP_DIR}" ]; then
        echo "更新代码到 ${APP_DIR}..."
        rsync -av --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' \
            --exclude='data/cache' --exclude='*.pyc' \
            "${DEPLOY_DIR}/../" "${APP_DIR}/"
    else
        echo "复制代码到 ${APP_DIR}..."
        sudo mkdir -p "${APP_DIR}"
        sudo rsync -av --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' \
            --exclude='data/cache' --exclude='*.pyc' \
            "${DEPLOY_DIR}/../" "${APP_DIR}/"
    fi

    # 3. 创建虚拟环境并安装依赖
    if [ ! -d "${APP_DIR}/venv" ]; then
        echo "创建 Python 虚拟环境..."
        python3 -m venv "${APP_DIR}/venv"
    fi
    echo "安装依赖..."
    "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

    # 4. 设置时区
    sudo timedatectl set-timezone Asia/Shanghai

    # 5. 安装 systemd 服务
    echo "安装 systemd 服务..."
    sudo cp "${DEPLOY_DIR}/${APP_NAME}.service" "${SERVICE_FILE}"
    sudo systemctl daemon-reload
    sudo systemctl enable "${APP_NAME}"

    # 6. 设置权限
    sudo chown -R stock:stock "${APP_DIR}"

    echo ""
    echo "=== 安装完成 ==="
    echo "请编辑 ${SERVICE_FILE} 配置钉钉环境变量，然后执行:"
    echo "  sudo systemctl start ${APP_NAME}"
    echo ""
    echo "常用命令:"
    echo "  sudo systemctl start ${APP_NAME}    # 启动"
    echo "  sudo systemctl stop ${APP_NAME}     # 停止"
    echo "  sudo systemctl restart ${APP_NAME}  # 重启"
    echo "  sudo systemctl status ${APP_NAME}   # 状态"
    echo "  journalctl -u ${APP_NAME} -f        # 实时日志"
}

uninstall() {
    echo "=== 卸载 ${APP_NAME} ==="
    sudo systemctl stop "${APP_NAME}" 2>/dev/null || true
    sudo systemctl disable "${APP_NAME}" 2>/dev/null || true
    sudo rm -f "${SERVICE_FILE}"
    sudo systemctl daemon-reload
    echo "已卸载服务（代码保留在 ${APP_DIR}）"
}

status() {
    sudo systemctl status "${APP_NAME}" --no-pager
}

logs() {
    sudo journalctl -u "${APP_NAME}" -f
}

case "${1}" in
    install)   install ;;
    uninstall) uninstall ;;
    status)    status ;;
    logs)      logs ;;
    *)
        echo "用法: bash $0 {install|uninstall|status|logs}"
        exit 1
        ;;
esac
