# encoding: utf-8
"""
高并发配置 - 支持 1000 台设备同时连接

使用方法：
1. 在启动服务前执行系统优化命令
2. 使用优化后的参数启动服务
"""

import os
import sys

# ============== 服务器配置 ==============
SERVER_CONFIG = {
    # 服务器端口
    "port": 8000,

    # 最大并发连接数
    "max_connections": 2000,

    # 工作进程数（多核支持）
    "workers": os.cpu_count() or 4,

    # 请求超时（秒）
    "request_timeout": 30,

    # WebSocket 心跳间隔（秒）
    "ws_heartbeat": 30,

    # 最大 WebSocket 消息大小（MB）
    "ws_max_msg_size": 16,
}

# ============== 连接池配置 ==============
CONNECTION_POOL_CONFIG = {
    # 最大连接数
    "max_size": 1200,

    # 最小空闲连接
    "min_idle": 50,

    # 空闲超时（秒）
    "max_idle_time": 600,

    # 健康检查间隔（秒）
    "health_check_interval": 120,

    # 连接获取超时（秒）
    "acquire_timeout": 10,
}

# ============== 线程池配置 ==============
THREAD_POOL_CONFIG = {
    # 核心线程数
    "core_threads": os.cpu_count() * 4,

    # 最大线程数
    "max_threads": min(os.cpu_count() * 20, 200),

    # 线程空闲超时（秒）
    "thread_idle_timeout": 60,

    # 任务队列大小
    "queue_size": 10000,
}

# ============== 截图缓存配置 ==============
SCREENSHOT_CACHE_CONFIG = {
    # 缓存大小
    "max_size": 500,

    # 缓存有效期（毫秒）
    "ttl_ms": 100,
}

# ============== 系统优化建议 ==============
SYSTEM_TUNING = """
==========================================================
  系统优化命令 (需要 root/sudo 权限)
==========================================================

【macOS】
# 增加文件描述符限制
sudo launchctl limit maxfiles 65535 200000
ulimit -n 65535

# 增加最大进程数
sudo sysctl -w kern.maxproc=2048
sudo sysctl -w kern.maxprocperuid=1024

# 网络优化
sudo sysctl -w net.inet.tcp.msl=15000
sudo sysctl -w net.inet.tcp.delayed_ack=0


【Linux】
# 增加文件描述符限制
echo "* soft nofile 65535" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 65535" | sudo tee -a /etc/security/limits.conf
ulimit -n 65535

# 内核参数优化
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.core.netdev_max_backlog=65535
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=65535
sudo sysctl -w net.ipv4.tcp_fin_timeout=10
sudo sysctl -w net.ipv4.tcp_tw_reuse=1
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"

# 持久化配置
sudo tee -a /etc/sysctl.conf << EOF
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 10
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535
EOF
sudo sysctl -p

==========================================================
"""


def print_config():
    """打印当前配置"""
    print("=" * 60)
    print("  CloudControl 高并发配置")
    print("=" * 60)

    print("\n服务器配置:")
    for key, value in SERVER_CONFIG.items():
        print(f"  - {key}: {value}")

    print("\n连接池配置:")
    for key, value in CONNECTION_POOL_CONFIG.items():
        print(f"  - {key}: {value}")

    print("\n线程池配置:")
    for key, value in THREAD_POOL_CONFIG.items():
        print(f"  - {key}: {value}")

    print("\n截图缓存配置:")
    for key, value in SCREENSHOT_CACHE_CONFIG.items():
        print(f"  - {key}: {value}")

    print(SYSTEM_TUNING)


def check_system_limits():
    """检查系统限制"""
    import resource

    print("\n当前系统限制:")

    # 文件描述符限制
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    print(f"  - 文件描述符限制: soft={soft}, hard={hard}")
    if soft < 10000:
        print(f"    ⚠️ 建议增加到至少 65535")

    # 最大进程数
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
        print(f"  - 最大进程数: soft={soft}, hard={hard}")
    except:
        pass

    # CPU 核心数
    import os
    print(f"  - CPU 核心数: {os.cpu_count()}")

    # 内存
    try:
        import psutil
        mem = psutil.virtual_memory()
        print(f"  - 总内存: {mem.total / (1024**3):.1f} GB")
        print(f"  - 可用内存: {mem.available / (1024**3):.1f} GB")
    except ImportError:
        pass

    print("\n预估容量:")
    # 每个设备连接约需要 5MB 内存
    estimated_devices = (os.cpu_count() or 4) * 250
    print(f"  - 预估最大设备数: {estimated_devices}")
    print(f"  - 目标: 1000 台设备")

    if estimated_devices >= 1000:
        print(f"  ✅ 系统配置满足 1000 设备需求")
    else:
        print(f"  ⚠️ 需要更多资源才能支持 1000 设备")


if __name__ == "__main__":
    print_config()
    check_system_limits()
