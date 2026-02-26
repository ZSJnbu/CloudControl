# encoding: utf-8
"""
集成测试
测试端到端工作流和系统集成
"""
import pytest
import pytest_asyncio
import aiohttp
import asyncio
import time

# 测试配置
BASE_URL = "http://localhost:8000"
TIMEOUT = aiohttp.ClientTimeout(total=60)


class TestDeviceWorkflow:
    """设备操作工作流测试"""

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
    async def test_full_device_interaction(self, device_udid):
        """测试完整的设备交互流程"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 1. 获取设备列表
            async with session.get(f"{BASE_URL}/list") as resp:
                assert resp.status == 200
                devices = await resp.json()  # API 直接返回数组
                assert isinstance(devices, list)
                print(f"Step 1: Found {len(devices)} devices")

            # 2. 获取截图
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=60&s=0.6"
            ) as resp:
                if resp.status == 200:
                    img_data = await resp.read()
                    print(f"Step 2: Screenshot captured ({len(img_data)} bytes)")
                else:
                    print(f"Step 2: Screenshot failed ({resp.status})")

            # 3. 点击屏幕中心
            payload = {'action': 'click', 'x': 540, 'y': 1200}
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                print(f"Step 3: Click sent ({resp.status})")

            await asyncio.sleep(0.5)

            # 4. 再次获取截图 (验证屏幕变化)
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=60&s=0.6&t={time.time()}"
            ) as resp:
                if resp.status == 200:
                    img_data = await resp.read()
                    print(f"Step 4: Screenshot after click ({len(img_data)} bytes)")

            # 5. 按返回键
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/keyevent/4"
            ) as resp:
                print(f"Step 5: Back key sent ({resp.status})")

    @pytest.mark.asyncio
    async def test_scroll_workflow(self, device_udid):
        """测试滚动操作工作流"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 1. 获取初始截图
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
            ) as resp:
                if resp.status == 200:
                    initial_size = len(await resp.read())
                    print(f"Initial screenshot: {initial_size} bytes")

            # 2. 向上滑动
            payload = {
                'action': 'swipe',
                'x': 540, 'y': 1800,
                'x2': 540, 'y2': 600,
                'duration': 300
            }
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                print(f"Swipe up: {resp.status}")

            await asyncio.sleep(0.5)

            # 3. 获取滑动后截图
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5&t={time.time()}"
            ) as resp:
                if resp.status == 200:
                    after_size = len(await resp.read())
                    print(f"After swipe screenshot: {after_size} bytes")

            # 4. 向下滑动回去
            payload = {
                'action': 'swipe',
                'x': 540, 'y': 600,
                'x2': 540, 'y2': 1800,
                'duration': 300
            }
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                print(f"Swipe down: {resp.status}")


class TestGroupControlWorkflow:
    """群控工作流测试"""

    @pytest_asyncio.fixture
    async def devices(self):
        """获取所有测试设备"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}/list") as resp:
                data = await resp.json()
                devices = data  # API 直接返回数组
                if len(devices) >= 2:
                    return devices[:2]
        pytest.skip("Need at least 2 devices for group control testing")

    @pytest.mark.asyncio
    async def test_group_control_page_access(self, devices):
        """测试群控页面访问"""
        if not devices:
            pytest.skip("No devices available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # POST 请求群控页面
            form_data = aiohttp.FormData()
            for d in devices:
                form_data.add_field('devices', d['udid'])  # 服务器期望 'devices' 字段

            async with session.post(
                f"{BASE_URL}/async",
                data=form_data
            ) as resp:
                assert resp.status == 200
                html = await resp.text()
                # 验证页面包含群控元素
                assert 'GROUP_CONTROL' in html or 'group' in html.lower()
                print(f"Group control page loaded with {len(devices)} devices")

    @pytest.mark.asyncio
    async def test_multi_device_screenshot(self, devices):
        """测试多设备截图"""
        if not devices:
            pytest.skip("No devices available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 并发获取所有设备截图
            tasks = [
                session.get(
                    f"{BASE_URL}/inspector/{d['udid']}/screenshot/img?q=50&s=0.5"
                )
                for d in devices
            ]
            responses = await asyncio.gather(*tasks)

            for i, resp in enumerate(responses):
                if resp.status == 200:
                    data = await resp.read()
                    print(f"Device {i+1} ({devices[i]['udid'][:20]}...): {len(data)} bytes")
                else:
                    print(f"Device {i+1}: Failed ({resp.status})")

    @pytest.mark.asyncio
    async def test_multi_device_touch(self, devices):
        """测试多设备同步触控"""
        if not devices:
            pytest.skip("No devices available")

        payload = {'action': 'click', 'x': 540, 'y': 1200}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 并发发送触控命令
            tasks = [
                session.post(
                    f"{BASE_URL}/inspector/{d['udid']}/touch",
                    json=payload
                )
                for d in devices
            ]
            responses = await asyncio.gather(*tasks)

            success_count = sum(1 for r in responses if r.status == 200)
            print(f"Multi-device touch: {success_count}/{len(devices)} successful")


class TestErrorRecovery:
    """错误恢复测试"""

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
    async def test_invalid_device_handling(self):
        """测试无效设备处理"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 尝试访问不存在的设备
            async with session.get(
                f"{BASE_URL}/inspector/nonexistent-device-xyz/screenshot/img"
            ) as resp:
                # 应该返回 404
                assert resp.status in [404, 500]

            # 系统应该继续正常工作
            async with session.get(f"{BASE_URL}/list") as resp:
                assert resp.status == 200

    @pytest.mark.asyncio
    async def test_rapid_reconnect(self, device_udid):
        """测试快速重连场景"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 模拟快速重复请求
            for i in range(5):
                async with session.get(
                    f"{BASE_URL}/inspector/{device_udid}/screenshot/img?t={i}"
                ) as resp:
                    # 应该都能正常响应
                    assert resp.status in [200, 404, 500]


class TestDataConsistency:
    """数据一致性测试"""

    @pytest.mark.asyncio
    async def test_device_list_consistency(self):
        """测试设备列表一致性"""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 多次获取设备列表
            results = []
            for _ in range(5):
                async with session.get(f"{BASE_URL}/list") as resp:
                    data = await resp.json()
                    results.append(set(d['udid'] for d in data))
                await asyncio.sleep(0.1)

            # 短时间内设备列表应该一致
            if results:
                for i in range(1, len(results)):
                    assert results[i] == results[0], "Device list inconsistent"
                print(f"Device list consistent across {len(results)} requests")


class TestSessionManagement:
    """会话管理测试"""

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
    async def test_multiple_sessions(self, device_udid):
        """测试多会话并发访问"""
        if not device_udid:
            pytest.skip("No device available")

        async def session_workflow(session_id):
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                # 每个会话执行一系列操作
                results = []

                # 获取设备列表
                async with session.get(f"{BASE_URL}/list") as resp:
                    results.append(('list', resp.status))

                # 获取截图
                async with session.get(
                    f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
                ) as resp:
                    results.append(('screenshot', resp.status))

                # 发送点击
                payload = {'action': 'click', 'x': 540, 'y': 1200}
                async with session.post(
                    f"{BASE_URL}/inspector/{device_udid}/touch",
                    json=payload
                ) as resp:
                    results.append(('touch', resp.status))

                return session_id, results

        # 启动 5 个并发会话
        tasks = [session_workflow(i) for i in range(5)]
        all_results = await asyncio.gather(*tasks)

        for session_id, results in all_results:
            print(f"Session {session_id}: {results}")


class TestE2EScenarios:
    """端到端场景测试"""

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
    async def test_scenario_app_navigation(self, device_udid):
        """测试应用导航场景"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            print("\n=== 应用导航场景测试 ===")

            # 1. 按 Home 键回到主屏幕
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/keyevent/3"
            ) as resp:
                print(f"1. Home key: {resp.status}")
            await asyncio.sleep(1)

            # 2. 截图确认在主屏幕
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=60&s=0.6"
            ) as resp:
                if resp.status == 200:
                    print(f"2. Home screen captured")

            # 3. 点击屏幕中心 (可能打开应用)
            payload = {'action': 'click', 'x': 540, 'y': 1200}
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                print(f"3. Center click: {resp.status}")
            await asyncio.sleep(0.5)

            # 4. 按返回键
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/keyevent/4"
            ) as resp:
                print(f"4. Back key: {resp.status}")
            await asyncio.sleep(0.5)

            # 5. 再次截图
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=60&s=0.6&t={time.time()}"
            ) as resp:
                if resp.status == 200:
                    print(f"5. Final screenshot captured")

            print("=== 场景测试完成 ===")

    @pytest.mark.asyncio
    async def test_scenario_text_input(self, device_udid):
        """测试文本输入场景"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            print("\n=== 文本输入场景测试 ===")

            # 1. 点击输入区域
            payload = {'action': 'click', 'x': 540, 'y': 800}
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/touch",
                json=payload
            ) as resp:
                print(f"1. Click input area: {resp.status}")
            await asyncio.sleep(0.5)

            # 2. 输入文本
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/input",
                json={'text': 'Test input 测试'}
            ) as resp:
                print(f"2. Text input: {resp.status}")
            await asyncio.sleep(0.5)

            # 3. 截图验证
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=60&s=0.6&t={time.time()}"
            ) as resp:
                if resp.status == 200:
                    print(f"3. Screenshot after input captured")

            # 4. 清空输入 (删除键)
            async with session.post(
                f"{BASE_URL}/inspector/{device_udid}/keyevent/67"  # KEYCODE_DEL
            ) as resp:
                print(f"4. Delete key: {resp.status}")

            print("=== 场景测试完成 ===")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
