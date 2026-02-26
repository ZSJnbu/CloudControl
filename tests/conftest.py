# encoding: utf-8
"""
CloudControl Test Configuration
共享的 pytest fixtures 和配置
"""
import pytest
import asyncio
import aiohttp
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============ 配置常量 ============
TEST_SERVER_URL = "http://localhost:8000"
TEST_TIMEOUT = 10  # 秒


# ============ Fixtures ============

@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def http_session():
    """创建 HTTP 会话"""
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture
def server_url():
    """服务器 URL"""
    return TEST_SERVER_URL


@pytest.fixture
def mock_device_info():
    """模拟设备信息"""
    return {
        'udid': 'test-device-001',
        'serial': 'emulator-5554',
        'ip': '10.0.2.16',
        'port': 7912,
        'model': 'sdk_gphone64_arm64',
        'brand': 'google',
        'version': '14',
        'sdk': 34,
        'display': {'width': 1080, 'height': 2400},
        'device_type': 'emulator',
        'present': True,
        'ready': True,
        'using': False,
    }


@pytest.fixture
def mock_touch_event():
    """模拟触控事件"""
    return {
        'action': 'click',
        'x': 540,
        'y': 1200
    }


@pytest.fixture
def mock_swipe_event():
    """模拟滑动事件"""
    return {
        'action': 'swipe',
        'x': 540,
        'y': 1800,
        'x2': 540,
        'y2': 600,
        'duration': 300
    }


# ============ 辅助函数 ============

async def check_server_running(session, url):
    """检查服务器是否运行"""
    try:
        async with session.get(f"{url}/list", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_test_devices():
    """获取测试设备列表"""
    import subprocess
    try:
        result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=5)
        devices = []
        for line in result.stdout.strip().split('\n')[1:]:
            parts = line.strip().split('\t')
            if len(parts) >= 2 and parts[1] == 'device':
                devices.append(parts[0])
        return devices
    except Exception:
        return []
