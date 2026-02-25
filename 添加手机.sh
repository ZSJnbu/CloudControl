#!/bin/bash
# 一键添加手机到 CloudControl
# 支持 USB 连接或 WiFi 无线调试
# 使用 SQLite 数据库

cd "$(dirname "$0")"

echo "========================================"
echo "      CloudControl 添加手机工具"
echo "========================================"
echo ""
echo "请选择连接方式："
echo "  1. USB 连接（推荐，自动检测）"
echo "  2. WiFi 无线调试（需输入IP）"
echo ""
read -p "请输入 (1/2): " conn_type

if [[ "$conn_type" == "2" ]]; then
    # WiFi 连接
    echo ""
    echo "请在手机上打开: 设置 → 开发者选项 → 无线调试"
    echo "点击「使用配对码配对设备」或查看 IP 地址和端口"
    echo ""
    read -p "请输入 IP:端口 (如 192.168.31.186:40045): " wifi_addr

    if [ -z "$wifi_addr" ]; then
        echo "错误: 未输入地址"
        read -p "按回车退出..."
        exit 1
    fi

    echo "正在连接 $wifi_addr ..."
    adb connect "$wifi_addr"
    sleep 2

    # 检查是否连接成功
    if ! adb devices | grep -q "$wifi_addr"; then
        echo "错误: 连接失败！请检查："
        echo "   1. IP和端口是否正确"
        echo "   2. 手机和电脑是否在同一WiFi"
        echo "   3. 无线调试是否已开启"
        read -p "按回车退出..."
        exit 1
    fi

    serial="$wifi_addr"
    device_ip=$(echo "$wifi_addr" | cut -d: -f1)
else
    # USB 连接
    echo ""
    echo "正在检测手机..."
    serial=$(adb devices | grep -v "List" | grep "device$" | head -1 | awk '{print $1}')

    if [ -z "$serial" ]; then
        echo "错误: 没检测到手机！请确保："
        echo "   1. USB 已连接"
        echo "   2. 手机已开启 USB 调试"
        echo "   3. 手机上已允许此电脑调试"
        read -p "按回车退出..."
        exit 1
    fi

    # 获取IP
    device_ip=$(adb -s "$serial" shell "ip route | grep wlan0 | awk '{print \$9}'" 2>/dev/null | tr -d '\r')
fi

# 获取手机信息
model=$(adb -s "$serial" shell getprop ro.product.model 2>/dev/null | tr -d '\r')
brand=$(adb -s "$serial" shell getprop ro.product.brand 2>/dev/null | tr -d '\r')
version=$(adb -s "$serial" shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')

echo ""
echo "已连接手机："
echo "   品牌: $brand"
echo "   型号: $model"
echo "   系统: Android $version"
echo "   IP: $device_ip"
echo "   Serial: $serial"
echo ""

# 安装并启动 atx-agent，添加到数据库 (SQLite)
echo "正在初始化设备控制服务..."
python3 << PYEOF
import uiautomator2 as u2
import sqlite3
import json
import os
from datetime import datetime

serial = "$serial"
device_ip = "$device_ip"
model = "$model"
brand = "$brand"
version = "$version"

print("  连接设备并初始化 atx-agent...")
try:
    # 连接设备（会自动安装atx-agent）
    if ":" in serial:
        # WiFi 连接
        d = u2.connect(serial)
    else:
        # USB 连接
        d = u2.connect_usb(serial)

    info = d.device_info
    print("  atx-agent 已启动")

    # 获取屏幕尺寸
    width, height = d.window_size()

    # 生成udid
    udid = f"{serial.replace(':', '-')}-{model.replace(' ', '_')}"

    # SQLite 数据库路径
    db_path = os.path.join(os.getcwd(), 'database', 'cloudcontrol.db')

    # 连接 SQLite
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 确保表存在
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            udid TEXT UNIQUE NOT NULL,
            serial TEXT,
            ip TEXT,
            port INTEGER,
            present INTEGER DEFAULT 0,
            ready INTEGER DEFAULT 0,
            using_device INTEGER DEFAULT 0,
            is_server INTEGER DEFAULT 0,
            is_mock INTEGER DEFAULT 0,
            update_time TEXT,
            model TEXT,
            brand TEXT,
            version TEXT,
            sdk INTEGER,
            memory TEXT,
            cpu TEXT,
            battery TEXT,
            display TEXT,
            owner TEXT,
            provider TEXT,
            agent_version TEXT,
            hwaddr TEXT,
            created_at TEXT,
            updated_at TEXT,
            extra_data TEXT
        )
    ''')

    now = datetime.now().isoformat()

    # 插入或更新记录
    cursor.execute('''
        INSERT OR REPLACE INTO devices
        (udid, serial, ip, port, present, ready, using_device, is_server,
         model, brand, version, sdk, memory, cpu, battery, display,
         created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        udid, serial, device_ip if device_ip else '127.0.0.1', 7912,
        1, 1, 0, 0,
        model, brand, version, info.get('sdk', 30),
        json.dumps({'total': 8000000000}),
        json.dumps({'hardware': info.get('arch', 'unknown'), 'cores': 8}),
        json.dumps({'level': 100}),
        json.dumps({'width': width, 'height': height}),
        now, now
    ))

    conn.commit()
    conn.close()

    print("  已添加到 CloudControl 数据库 (SQLite)")
    print(f"  设备UDID: {udid}")

except Exception as e:
    print(f"  初始化失败: {e}")
    print("     请确保手机屏幕解锁并允许安装应用")
    import traceback
    traceback.print_exc()
    exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo ""
    echo "设备初始化失败，请重试"
    read -p "按回车退出..."
    exit 1
fi

echo ""
echo "========================================"
echo "            设置完成！"
echo "========================================"
echo ""
echo "打开浏览器访问: http://localhost:8000"
echo "刷新页面即可看到新添加的设备"
echo ""

# 询问是否打开 scrcpy
read -p "是否同时打开 scrcpy 窗口控制？(y/n): " use_scrcpy
if [[ "$use_scrcpy" == "y" || "$use_scrcpy" == "Y" ]]; then
    echo "启动 scrcpy..."
    scrcpy -s "$serial" --window-title "$brand $model" &
fi

echo ""
read -p "按回车退出..."
