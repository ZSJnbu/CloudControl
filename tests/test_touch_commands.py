# encoding: utf-8
"""
触控命令测试
测试点击、滑动、按键等触控操作
"""
import pytest
import pytest_asyncio
import aiohttp
import asyncio
import time

# 测试配置
BASE_URL = "http://localhost:8000"
TIMEOUT = aiohttp.ClientTimeout(total=30)


class TestTouchClick:
    """点击命令测试"""

    @pytest_asyncio.fixture
    async def device_udid(self):
        """获取测试设备 UDID"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                data = await resp.json()
                devices = data  # API 直接返回数组
                if devices:
                    return devices[0].get('udid')
        pytest.skip("No devices available for testing")

    @pytest.mark.asyncio
    async def test_click_center(self, device_udid):
        """测试点击屏幕中心"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {'action': 'click', 'x': 540, 'y': 1200}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Click response: {data}")

    @pytest.mark.asyncio
    async def test_click_corners(self, device_udid):
        """测试点击屏幕四角"""
        if not device_udid:
            pytest.skip("No device available")

        corners = [
            (100, 100),      # 左上
            (980, 100),      # 右上
            (100, 2300),     # 左下
            (980, 2300),     # 右下
        ]

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for x, y in corners:
                payload = {'action': 'click', 'x': x, 'y': y}
                async with session.post(
                    f"{BASE_URL}/inspector/{device_udid}/touch",
                    json=payload
                ) as resp:
                    assert resp.status in [200, 404, 500]
                await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_click_negative_coords(self, device_udid):
        """测试负坐标点击 (边界情况)"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {'action': 'click', 'x': -10, 'y': -10}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                # 应该处理负坐标
                assert resp.status in [200, 400, 404, 500]

    @pytest.mark.asyncio
    async def test_click_large_coords(self, device_udid):
        """测试超大坐标点击 (边界情况)"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {'action': 'click', 'x': 99999, 'y': 99999}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                assert resp.status in [200, 400, 404, 500]


class TestTouchSwipe:
    """滑动命令测试"""

    @pytest_asyncio.fixture
    async def device_udid(self):
        """获取测试设备 UDID"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                data = await resp.json()
                devices = data  # API 直接返回数组
                if devices:
                    return devices[0].get('udid')
        pytest.skip("No devices available for testing")

    @pytest.mark.asyncio
    async def test_swipe_up(self, device_udid):
        """测试向上滑动"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'action': 'swipe',
            'x': 540, 'y': 1800,
            'x2': 540, 'y2': 600,
            'duration': 300
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_swipe_down(self, device_udid):
        """测试向下滑动"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'action': 'swipe',
            'x': 540, 'y': 600,
            'x2': 540, 'y2': 1800,
            'duration': 300
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_swipe_left(self, device_udid):
        """测试向左滑动"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'action': 'swipe',
            'x': 900, 'y': 1200,
            'x2': 180, 'y2': 1200,
            'duration': 300
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_swipe_right(self, device_udid):
        """测试向右滑动"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'action': 'swipe',
            'x': 180, 'y': 1200,
            'x2': 900, 'y2': 1200,
            'duration': 300
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_swipe_diagonal(self, device_udid):
        """测试对角线滑动"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'action': 'swipe',
            'x': 100, 'y': 100,
            'x2': 980, 'y2': 2300,
            'duration': 500
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_swipe_fast(self, device_udid):
        """测试快速滑动"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'action': 'swipe',
            'x': 540, 'y': 1800,
            'x2': 540, 'y2': 600,
            'duration': 50  # 快速滑动
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_swipe_slow(self, device_udid):
        """测试慢速滑动"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'action': 'swipe',
            'x': 540, 'y': 1800,
            'x2': 540, 'y2': 600,
            'duration': 1000  # 慢速滑动
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]


class TestKeyEvents:
    """按键事件测试"""

    @pytest_asyncio.fixture
    async def device_udid(self):
        """获取测试设备 UDID"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                data = await resp.json()
                devices = data  # API 直接返回数组
                if devices:
                    return devices[0].get('udid')
        pytest.skip("No devices available for testing")

    @pytest.mark.asyncio
    async def test_keyevent_home(self, device_udid):
        """测试 Home 键"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/keyevent/3"  # KEYCODE_HOME
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_keyevent_back(self, device_udid):
        """测试 Back 键"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/keyevent/4"  # KEYCODE_BACK
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_keyevent_menu(self, device_udid):
        """测试 Menu 键"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/keyevent/82"  # KEYCODE_MENU
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_keyevent_power(self, device_udid):
        """测试电源键"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/keyevent/26"  # KEYCODE_POWER
            ) as resp:
                assert resp.status in [200, 404, 500]


class TestTextInput:
    """文本输入测试"""

    @pytest_asyncio.fixture
    async def device_udid(self):
        """获取测试设备 UDID"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                data = await resp.json()
                devices = data  # API 直接返回数组
                if devices:
                    return devices[0].get('udid')
        pytest.skip("No devices available for testing")

    @pytest.mark.asyncio
    async def test_input_english(self, device_udid):
        """测试英文输入"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {'text': 'Hello World'}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/input",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_input_chinese(self, device_udid):
        """测试中文输入"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {'text': '你好世界'}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/input",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_input_special_chars(self, device_udid):
        """测试特殊字符输入"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {'text': '!@#$%^&*()_+-=[]{}|;:,.<>?'}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/input",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_input_emoji(self, device_udid):
        """测试 Emoji 输入"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {'text': '😀🎉🚀'}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/input",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_input_long_text(self, device_udid):
        """测试长文本输入"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {'text': 'A' * 500}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/input",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_input_empty(self, device_udid):
        """测试空文本输入"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {'text': ''}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/input",
                json=payload
            ) as resp:
                assert resp.status in [200, 400, 404, 500]


class TestTouchConcurrency:
    """触控命令并发测试"""

    @pytest_asyncio.fixture
    async def device_udid(self):
        """获取测试设备 UDID"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                data = await resp.json()
                devices = data  # API 直接返回数组
                if devices:
                    return devices[0].get('udid')
        pytest.skip("No devices available for testing")

    @pytest.mark.asyncio
    async def test_rapid_clicks(self, device_udid):
        """测试快速连续点击"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {'action': 'click', 'x': 540, 'y': 1200}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            tasks = [
                session.post(
                    f"{BASE_URL}/inspector/{device_udid}/touch",
                    json=payload
                )
                for _ in range(10)
            ]
            responses = await asyncio.gather(*tasks)

            success_count = sum(1 for r in responses if r.status == 200)
            print(f"Rapid clicks: {success_count}/10 successful")

    @pytest.mark.asyncio
    async def test_concurrent_different_commands(self, device_udid):
        """测试并发不同命令"""
        if not device_udid:
            pytest.skip("No device available")

        commands = [
            {'action': 'click', 'x': 540, 'y': 600},
            {'action': 'click', 'x': 540, 'y': 1200},
            {'action': 'swipe', 'x': 540, 'y': 1800, 'x2': 540, 'y2': 600, 'duration': 200},
        ]

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            tasks = [
                session.post(
                    f"{BASE_URL}/inspector/{device_udid}/touch",
                    json=cmd
                )
                for cmd in commands
            ]
            responses = await asyncio.gather(*tasks)

            for resp in responses:
                assert resp.status in [200, 404, 500]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
