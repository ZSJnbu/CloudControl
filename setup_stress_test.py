#!/usr/bin/env python3
# encoding: utf-8
"""
压力测试环境准备脚本
创建模拟设备数据用于测试 (SQLite版本)
"""

import asyncio
import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def setup_mock_devices(count: int = 1000):
    """创建模拟设备数据"""
    try:
        import aiosqlite
        import json

        db_path = os.path.join(os.path.dirname(__file__), 'database', 'cloudcontrol.db')

        print(f"正在连接 SQLite: {db_path}")

        async with aiosqlite.connect(db_path) as db:
            # 确保表存在
            await db.execute('''
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
            await db.commit()

            print(f"正在创建 {count} 个模拟设备...")

            # 删除旧的模拟设备
            cursor = await db.execute("DELETE FROM devices WHERE udid LIKE 'stress-test-%'")
            deleted = cursor.rowcount
            await db.commit()
            print(f"  已删除 {deleted} 个旧模拟设备")

            # 批量创建模拟设备
            now = datetime.now().isoformat()

            for i in range(count):
                device = {
                    'udid': f'stress-test-device-{i}',
                    'serial': f'STRESS{i:06d}',
                    'ip': f'192.168.{(i // 256) % 256}.{i % 256}',
                    'port': 5555,
                    'present': 1,
                    'ready': 1,
                    'using_device': 0,
                    'is_mock': 1,
                    'model': f'StressTest-{i}',
                    'brand': 'TestDevice',
                    'version': '12',
                    'sdk': 31,
                    'memory': json.dumps({'total': 8000000000}),
                    'cpu': json.dumps({'hardware': 'test', 'cores': 8}),
                    'battery': json.dumps({'level': 100}),
                    'display': json.dumps({'width': 1080, 'height': 2400}),
                    'created_at': now,
                    'updated_at': now,
                }

                await db.execute('''
                    INSERT OR REPLACE INTO devices
                    (udid, serial, ip, port, present, ready, using_device, is_mock,
                     model, brand, version, sdk, memory, cpu, battery, display,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    device['udid'], device['serial'], device['ip'], device['port'],
                    device['present'], device['ready'], device['using_device'], device['is_mock'],
                    device['model'], device['brand'], device['version'], device['sdk'],
                    device['memory'], device['cpu'], device['battery'], device['display'],
                    device['created_at'], device['updated_at']
                ))

                if (i + 1) % 100 == 0:
                    await db.commit()
                    print(f"  已创建 {i + 1}/{count} 个设备")

            await db.commit()

            # 统计
            cursor = await db.execute("SELECT COUNT(*) FROM devices")
            total = (await cursor.fetchone())[0]

            cursor = await db.execute("SELECT COUNT(*) FROM devices WHERE is_mock = 1")
            mock_count = (await cursor.fetchone())[0]

            print(f"\n完成！")
            print(f"  - 模拟设备: {mock_count}")
            print(f"  - 总设备数: {total}")

        return True

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return False


async def cleanup_mock_devices():
    """清理模拟设备"""
    try:
        import aiosqlite

        db_path = os.path.join(os.path.dirname(__file__), 'database', 'cloudcontrol.db')

        print(f"正在清理模拟设备...")

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("DELETE FROM devices WHERE is_mock = 1")
            deleted = cursor.rowcount
            await db.commit()

            print(f"  已删除 {deleted} 个模拟设备")

        return True

    except Exception as e:
        print(f"错误: {e}")
        return False


def print_usage():
    print("""
压力测试环境准备脚本 (SQLite版本)

用法:
    python setup_stress_test.py setup [count]   - 创建模拟设备 (默认 1000)
    python setup_stress_test.py cleanup         - 清理模拟设备
    python setup_stress_test.py run             - 运行压力测试

示例:
    python setup_stress_test.py setup 1000
    python setup_stress_test.py run
    python setup_stress_test.py cleanup
""")


async def run_stress_test():
    """运行压力测试"""
    import subprocess

    print("运行压力测试...")
    print("=" * 60)

    # 阶段性测试
    stages = [
        (10, 10),    # 10 连接，10秒
        (50, 15),    # 50 连接，15秒
        (100, 20),   # 100 连接，20秒
        (200, 30),   # 200 连接，30秒
        (500, 45),   # 500 连接，45秒
        (1000, 60),  # 1000 连接，60秒
    ]

    for connections, duration in stages:
        print(f"\n{'#'*60}")
        print(f"# 阶段: {connections} 并发连接, {duration} 秒")
        print(f"{'#'*60}\n")

        result = subprocess.run([
            sys.executable, 'stress_test.py',
            '-c', str(connections),
            '-d', str(duration),
            '-m', 'mixed'
        ])

        if result.returncode != 0:
            print(f"阶段 {connections} 连接测试失败")
            break

        print(f"\n等待 5 秒后继续下一阶段...")
        await asyncio.sleep(5)


async def main():
    if len(sys.argv) < 2:
        print_usage()
        return

    command = sys.argv[1].lower()

    if command == 'setup':
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
        await setup_mock_devices(count)

    elif command == 'cleanup':
        await cleanup_mock_devices()

    elif command == 'run':
        await run_stress_test()

    else:
        print_usage()


if __name__ == "__main__":
    asyncio.run(main())
