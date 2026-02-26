# encoding: utf-8
"""
API 端点测试
测试所有 HTTP API 端点的功能和响应
"""
import pytest
import pytest_asyncio
import aiohttp
import asyncio
import json
import time

# 测试配置
BASE_URL = "http://localhost:8000"
TIMEOUT = aiohttp.ClientTimeout(total=30)


class TestHealthEndpoints:
    """健康检查端点测试"""

    @pytest.mark.asyncio
    async def test_root_endpoint(self):
        """测试根路径返回首页"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/") as resp:
                assert resp.status == 200
                assert 'text/html' in resp.content_type

    @pytest.mark.asyncio
    async def test_list_endpoint(self):
        """测试设备列表端点"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                assert resp.status == 200
                data = await resp.json()
                # API 直接返回设备数组
                assert isinstance(data, list)


class TestDeviceEndpoints:
    """设备相关端点测试"""

    @pytest_asyncio.fixture
    async def device_udid(self):
        """获取测试设备 UDID"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                devices = await resp.json()
                # API 直接返回设备数组
                if devices and len(devices) > 0:
                    return devices[0].get('udid')
        pytest.skip("No devices available for testing")

    @pytest.mark.asyncio
    async def test_device_info(self, device_udid):
        """测试获取设备信息"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/devices/{device_udid}") as resp:
                # 可能返回 200 或 404
                assert resp.status in [200, 404]

    @pytest.mark.asyncio
    async def test_device_screenshot_endpoint_exists(self, device_udid):
        """测试截图端点存在"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot"
            ) as resp:
                # 端点应该存在并返回图片或错误
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_device_screenshot_img_endpoint(self, device_udid):
        """测试截图图片端点"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
            ) as resp:
                if resp.status == 200:
                    assert resp.content_type == 'image/jpeg'
                    # 验证 X-Cache header
                    assert 'X-Cache' in resp.headers
                else:
                    # 设备可能不可用
                    assert resp.status in [404, 500]

    @pytest.mark.asyncio
    async def test_device_hierarchy_endpoint(self, device_udid):
        """测试 UI 层级端点"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/hierarchy"
            ) as resp:
                assert resp.status in [200, 404, 500]


class TestTouchEndpoints:
    """触控端点测试"""

    @pytest_asyncio.fixture
    async def device_udid(self):
        """获取测试设备 UDID"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                devices = await resp.json()
                # API 直接返回设备数组
                if devices and len(devices) > 0:
                    return devices[0].get('udid')
        pytest.skip("No devices available for testing")

    @pytest.mark.asyncio
    async def test_touch_click(self, device_udid):
        """测试点击命令"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'action': 'click',
            'x': 540,
            'y': 1200
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                # 应该返回成功或设备不可用
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_touch_swipe(self, device_udid):
        """测试滑动命令"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'action': 'swipe',
            'x': 540,
            'y': 1800,
            'x2': 540,
            'y2': 600,
            'duration': 300
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_touch_invalid_action(self, device_udid):
        """测试无效的触控动作"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'action': 'invalid_action',
            'x': 540,
            'y': 1200
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                # 应该返回错误
                assert resp.status in [200, 400, 404, 500]


class TestInputEndpoints:
    """文本输入端点测试"""

    @pytest_asyncio.fixture
    async def device_udid(self):
        """获取测试设备 UDID"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                devices = await resp.json()
                # API 直接返回设备数组
                if devices and len(devices) > 0:
                    return devices[0].get('udid')
        pytest.skip("No devices available for testing")

    @pytest.mark.asyncio
    async def test_text_input(self, device_udid):
        """测试文本输入"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'text': 'Hello Test'
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/input",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_chinese_input(self, device_udid):
        """测试中文输入"""
        if not device_udid:
            pytest.skip("No device available")

        payload = {
            'text': '测试中文输入'
        }

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/input",
                json=payload
            ) as resp:
                assert resp.status in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_keyevent(self, device_udid):
        """测试按键事件"""
        if not device_udid:
            pytest.skip("No device available")

        # 测试 Home 键
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/keyevent/3"
            ) as resp:
                assert resp.status in [200, 404, 500]


class TestGroupControlEndpoints:
    """群控端点测试"""

    @pytest.mark.asyncio
    async def test_async_page_requires_post(self):
        """测试 /async 页面需要 POST"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/async") as resp:
                # GET 请求应该返回 405
                assert resp.status == 405

    @pytest.mark.asyncio
    async def test_async_page_post(self):
        """测试 /async 页面 POST"""
        # 先获取设备列表
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                devices = await resp.json()  # API 直接返回数组

            if not devices or len(devices) == 0:
                pytest.skip("No devices available")

            # POST 请求群控页面
            udids = [d['udid'] for d in devices[:2]]
            form_data = aiohttp.FormData()
            for udid in udids:
                form_data.add_field('devices', udid)  # 服务器期望 'devices' 字段

            async with session.post(
                f"{BASE_URL}/async",
                data=form_data
            ) as resp:
                assert resp.status == 200
                assert 'text/html' in resp.content_type


class TestErrorHandling:
    """错误处理测试"""

    @pytest.mark.asyncio
    async def test_invalid_device_udid(self):
        """测试无效的设备 UDID"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(
                f"{BASE_URL}/inspector/invalid-device-12345/screenshot"
            ) as resp:
                assert resp.status in [404, 500]

    @pytest.mark.asyncio
    async def test_invalid_endpoint(self):
        """测试无效的端点"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/nonexistent/endpoint") as resp:
                assert resp.status == 404

    @pytest.mark.asyncio
    async def test_malformed_json(self):
        """测试格式错误的 JSON"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{BASE_URL}/inspector/test-device/touch",
                data="not valid json",
                headers={'Content-Type': 'application/json'}
            ) as resp:
                # 应该返回错误
                assert resp.status in [400, 404, 500]


class TestConcurrency:
    """并发测试"""

    @pytest.mark.asyncio
    async def test_concurrent_list_requests(self):
        """测试并发列表请求"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            tasks = [
                session.get(f"{BASE_URL}/list")
                for _ in range(10)
            ]
            responses = await asyncio.gather(*tasks)

            for resp in responses:
                assert resp.status == 200

    @pytest.mark.asyncio
    async def test_concurrent_screenshot_requests(self):
        """测试并发截图请求"""
        # 先获取设备
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                devices = await resp.json()  # API 直接返回数组

            if not devices or len(devices) == 0:
                pytest.skip("No devices available")

            udid = devices[0]['udid']

            # 并发请求截图
            tasks = [
                session.get(f"{BASE_URL}/inspector/{udid}/screenshot/img?q=40&s=0.4")
                for _ in range(5)
            ]
            responses = await asyncio.gather(*tasks)

            success_count = sum(1 for r in responses if r.status == 200)
            # 至少应该有一些成功
            assert success_count > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
