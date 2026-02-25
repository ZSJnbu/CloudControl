#!/bin/bash

# 切换到脚本所在目录
cd "$(dirname "$0")"

echo "================================"
echo "   CloudControl 服务启动中..."
echo "================================"
echo ""

# 检查 Python3 是否安装
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 Python3，请先安装 Python3"
    echo "按任意键退出..."
    read -n 1
    exit 1
fi

# 检查依赖是否安装
if ! python3 -c "import aiohttp" 2>/dev/null; then
    echo "检测到依赖未安装，正在安装..."
    pip3 install -r requirements.txt
    echo ""
fi

echo "服务地址: http://localhost:8000"
echo "按 Ctrl+C 停止服务"
echo ""
echo "--------------------------------"
echo ""

# 启动服务
python3 main.py

# 如果服务异常退出，保持窗口打开
echo ""
echo "服务已停止，按任意键关闭窗口..."
read -n 1
