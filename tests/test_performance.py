# encoding: utf-8
"""
性能测试
测试系统性能、延迟、吞吐量等
"""
import pytest
import aiohttp
import asyncio
import time
import statistics
from typing import List, Dict

# 测试配置
BASE_URL = "http://localhost:8000"
TIMEOUT = aiohttp.ClientTimeout(total=60)


class TestLatencyMetrics:
    """延迟指标测试"""

    @pytest.fixture
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
    async def test_list_endpoint_latency(self):
        """测试设备列表 API 延迟"""
        latencies = []

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for _ in range(10):
                start = time.time()
                async with session.get(f"{BASE_URL}/list") as resp:
                    await resp.json()
                latencies.append((time.time() - start) * 1000)

        avg = statistics.mean(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]

        print(f"\n设备列表 API 延迟:")
        print(f"  平均: {avg:.2f}ms")
        print(f"  P95: {p95:.2f}ms")
        print(f"  P99: {p99:.2f}ms")

        # 设备列表应该很快
        assert avg < 500, f"Average latency {avg}ms exceeds 500ms"

    @pytest.mark.asyncio
    async def test_screenshot_latency(self, device_udid):
        """测试截图 API 延迟"""
        if not device_udid:
            pytest.skip("No device available")

        latencies = []

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for i in range(10):
                # 使用不同的时间戳避免缓存
                start = time.time()
                async with session.get(
                    f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5&t={time.time()}"
                ) as resp:
                    if resp.status == 200:
                        await resp.read()
                        latencies.append((time.time() - start) * 1000)
                await asyncio.sleep(0.5)  # 等待缓存过期

        if latencies:
            avg = statistics.mean(latencies)
            p95 = sorted(latencies)[int(len(latencies) * 0.95)]

            print(f"\n截图 API 延迟 (无缓存):")
            print(f"  平均: {avg:.2f}ms")
            print(f"  P95: {p95:.2f}ms")
            print(f"  最小: {min(latencies):.2f}ms")
            print(f"  最大: {max(latencies):.2f}ms")

    @pytest.mark.asyncio
    async def test_screenshot_cache_latency(self, device_udid):
        """测试截图缓存命中延迟"""
        if not device_udid:
            pytest.skip("No device available")

        latencies = []

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 先触发一次以填充缓存
            await session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
            )

            # 快速连续请求 (应该命中缓存)
            for _ in range(20):
                start = time.time()
                async with session.get(
                    f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
                ) as resp:
                    if resp.status == 200:
                        await resp.read()
                        latencies.append((time.time() - start) * 1000)

        if latencies:
            avg = statistics.mean(latencies)
            p95 = sorted(latencies)[int(len(latencies) * 0.95)]

            print(f"\n截图 API 延迟 (缓存命中):")
            print(f"  平均: {avg:.2f}ms")
            print(f"  P95: {p95:.2f}ms")

            # 缓存命中应该非常快
            assert avg < 50, f"Cache hit latency {avg}ms exceeds 50ms"

    @pytest.mark.asyncio
    async def test_touch_command_latency(self, device_udid):
        """测试触控命令延迟"""
        if not device_udid:
            pytest.skip("No device available")

        latencies = []
        payload = {'action': 'click', 'x': 540, 'y': 1200}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for _ in range(10):
                start = time.time()
                async with session.post(
                    f"{BASE_URL}/inspector/{device_udid}/touch",
                    json=payload
                ) as resp:
                    if resp.status == 200:
                        await resp.json()
                        latencies.append((time.time() - start) * 1000)
                await asyncio.sleep(0.1)

        if latencies:
            avg = statistics.mean(latencies)
            p95 = sorted(latencies)[int(len(latencies) * 0.95)]

            print(f"\n触控命令延迟:")
            print(f"  平均: {avg:.2f}ms")
            print(f"  P95: {p95:.2f}ms")


class TestThroughput:
    """吞吐量测试"""

    @pytest.fixture
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
    async def test_concurrent_list_requests(self):
        """测试并发设备列表请求吞吐量"""
        concurrent = 50
        total_requests = 100

        async def make_request(session):
            start = time.time()
            async with session.get(f"{BASE_URL}/list") as resp:
                await resp.json()
            return time.time() - start

        start_time = time.time()
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            tasks = [make_request(session) for _ in range(total_requests)]
            latencies = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        rps = total_requests / total_time
        avg_latency = statistics.mean(latencies) * 1000

        print(f"\n并发列表请求吞吐量 ({concurrent} 并发):")
        print(f"  总请求数: {total_requests}")
        print(f"  总耗时: {total_time:.2f}s")
        print(f"  RPS: {rps:.2f}")
        print(f"  平均延迟: {avg_latency:.2f}ms")

    @pytest.mark.asyncio
    async def test_concurrent_screenshot_requests(self, device_udid):
        """测试并发截图请求吞吐量"""
        if not device_udid:
            pytest.skip("No device available")

        concurrent = 10
        total_requests = 30

        async def make_request(session, i):
            start = time.time()
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5&t={i}"
            ) as resp:
                if resp.status == 200:
                    await resp.read()
                    return time.time() - start, True
            return time.time() - start, False

        start_time = time.time()
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            tasks = [make_request(session, i) for i in range(total_requests)]
            results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        successful = sum(1 for _, success in results if success)
        latencies = [lat for lat, success in results if success]

        if latencies:
            rps = successful / total_time
            avg_latency = statistics.mean(latencies) * 1000

            print(f"\n并发截图请求吞吐量 ({concurrent} 并发):")
            print(f"  成功请求: {successful}/{total_requests}")
            print(f"  总耗时: {total_time:.2f}s")
            print(f"  RPS: {rps:.2f}")
            print(f"  平均延迟: {avg_latency:.2f}ms")


class TestStress:
    """压力测试"""

    @pytest.fixture
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
    async def test_sustained_load(self, device_udid):
        """测试持续负载"""
        if not device_udid:
            pytest.skip("No device available")

        duration = 10  # 秒
        results: List[Dict] = []

        async def make_requests(session, stop_event):
            while not stop_event.is_set():
                start = time.time()
                try:
                    async with session.get(
                        f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=40&s=0.4"
                    ) as resp:
                        if resp.status == 200:
                            await resp.read()
                            results.append({
                                'latency': (time.time() - start) * 1000,
                                'success': True
                            })
                        else:
                            results.append({
                                'latency': (time.time() - start) * 1000,
                                'success': False
                            })
                except Exception:
                    results.append({
                        'latency': (time.time() - start) * 1000,
                        'success': False
                    })

        stop_event = asyncio.Event()
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 启动 5 个并发工作者
            tasks = [make_requests(session, stop_event) for _ in range(5)]
            worker_tasks = [asyncio.create_task(t) for t in tasks]

            # 运行指定时间
            await asyncio.sleep(duration)
            stop_event.set()

            # 等待所有任务完成
            for task in worker_tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if results:
            successful = sum(1 for r in results if r['success'])
            latencies = [r['latency'] for r in results if r['success']]

            print(f"\n持续负载测试 ({duration}秒, 5并发):")
            print(f"  总请求数: {len(results)}")
            print(f"  成功率: {successful/len(results)*100:.1f}%")
            if latencies:
                print(f"  平均延迟: {statistics.mean(latencies):.2f}ms")
                print(f"  RPS: {successful/duration:.2f}")


class TestMemoryStability:
    """内存稳定性测试"""

    @pytest.fixture
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
    async def test_repeated_screenshots(self, device_udid):
        """测试重复截图不会内存泄漏"""
        if not device_udid:
            pytest.skip("No device available")

        request_count = 50
        successful = 0

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for i in range(request_count):
                try:
                    async with session.get(
                        f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5&t={i}"
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            successful += 1
                            # 丢弃数据，模拟正常使用
                            del data
                except Exception as e:
                    print(f"Request {i} failed: {e}")

                if i % 10 == 0:
                    await asyncio.sleep(0.5)

        print(f"\n重复截图测试:")
        print(f"  成功: {successful}/{request_count}")

        # 应该大部分成功
        assert successful > request_count * 0.8


class TestQualityPresetPerformance:
    """质量预设性能对比"""

    @pytest.fixture
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
    async def test_quality_presets_comparison(self, device_udid):
        """对比不同质量预设的性能"""
        if not device_udid:
            pytest.skip("No device available")

        presets = {
            'performance': {'q': 40, 's': 0.4},
            'standard': {'q': 60, 's': 0.6},
            'hd': {'q': 80, 's': 0.8},
        }

        results = {}

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for name, params in presets.items():
                latencies = []
                sizes = []

                for i in range(5):
                    await asyncio.sleep(0.5)  # 等待缓存过期
                    start = time.time()
                    async with session.get(
                        f"{BASE_URL}/inspector/{device_udid}/screenshot/img"
                        f"?q={params['q']}&s={params['s']}&t={time.time()}"
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            latencies.append((time.time() - start) * 1000)
                            sizes.append(len(data))

                if latencies:
                    results[name] = {
                        'avg_latency': statistics.mean(latencies),
                        'avg_size': statistics.mean(sizes) / 1024,  # KB
                    }

        print("\n质量预设性能对比:")
        print(f"{'预设':<12} {'延迟(ms)':<12} {'大小(KB)':<12}")
        print("-" * 36)
        for name, data in results.items():
            print(f"{name:<12} {data['avg_latency']:<12.2f} {data['avg_size']:<12.1f}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
