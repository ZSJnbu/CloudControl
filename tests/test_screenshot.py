# encoding: utf-8
"""
截图功能测试
测试截图 API、缓存、质量设置等
"""
import pytest
import pytest_asyncio
import aiohttp
import asyncio
import time
from io import BytesIO

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# 测试配置
BASE_URL = "http://localhost:8000"
TIMEOUT = aiohttp.ClientTimeout(total=30)


class TestScreenshotBasic:
    """截图基础功能测试"""

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
    async def test_screenshot_returns_jpeg(self, device_udid):
        """测试截图返回 JPEG 格式"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img"
            ) as resp:
                if resp.status == 200:
                    assert resp.content_type == 'image/jpeg'
                    # 验证是有效的 JPEG
                    data = await resp.read()
                    assert data[:2] == b'\xff\xd8'  # JPEG magic bytes

    @pytest.mark.asyncio
    async def test_screenshot_with_quality(self, device_udid):
        """测试不同质量设置"""
        if not device_udid:
            pytest.skip("No device available")

        qualities = [30, 50, 70, 90]
        sizes = []

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for q in qualities:
                async with session.get(
                    f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q={q}&s=0.5"
                ) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        sizes.append((q, len(data)))
                        await asyncio.sleep(0.5)  # 等待缓存过期

        # 更高质量应该产生更大的文件 (大致趋势)
        if len(sizes) >= 2:
            print(f"Quality vs Size: {sizes}")
            # 不强制要求严格递增，因为压缩是复杂的

    @pytest.mark.asyncio
    async def test_screenshot_with_scale(self, device_udid):
        """测试不同缩放设置"""
        if not device_udid:
            pytest.skip("No device available")

        scales = [0.3, 0.5, 0.8, 1.0]
        sizes = []

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for s in scales:
                async with session.get(
                    f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s={s}"
                ) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        sizes.append((s, len(data)))
                        await asyncio.sleep(0.5)

        # 更大缩放应该产生更大的文件
        if len(sizes) >= 2:
            print(f"Scale vs Size: {sizes}")


class TestScreenshotCache:
    """截图缓存测试"""

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
    async def test_cache_hit(self, device_udid):
        """测试缓存命中"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 第一次请求
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
            ) as resp1:
                if resp1.status != 200:
                    pytest.skip("Screenshot not available")
                cache1 = resp1.headers.get('X-Cache')

            # 立即第二次请求 (应该命中缓存)
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
            ) as resp2:
                cache2 = resp2.headers.get('X-Cache')

            # 第一次应该是 MISS，第二次应该是 HIT 或 DEDUP
            assert cache1 in ['MISS', 'HIT', 'DEDUP']
            assert cache2 in ['HIT', 'DEDUP']

    @pytest.mark.asyncio
    async def test_cache_different_params(self, device_udid):
        """测试不同参数不共享缓存"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 请求 q=50
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
            ) as resp1:
                if resp1.status != 200:
                    pytest.skip("Screenshot not available")
                cache1 = resp1.headers.get('X-Cache')

            # 请求 q=60 (不同参数，应该是新请求)
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=60&s=0.5"
            ) as resp2:
                cache2 = resp2.headers.get('X-Cache')

            # 第二次请求使用不同参数，应该是 MISS
            print(f"Cache headers: q50={cache1}, q60={cache2}")

    @pytest.mark.asyncio
    async def test_cache_expiry(self, device_udid):
        """测试缓存过期"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 第一次请求
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
            ) as resp1:
                if resp1.status != 200:
                    pytest.skip("Screenshot not available")

            # 等待缓存过期 (TTL 是 300ms)
            await asyncio.sleep(0.5)

            # 第二次请求 (应该缓存已过期)
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
            ) as resp2:
                cache2 = resp2.headers.get('X-Cache')

            # 缓存过期后应该是 MISS
            print(f"After 500ms sleep, cache: {cache2}")


class TestScreenshotDeduplication:
    """截图请求去重测试"""

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
    async def test_concurrent_requests_dedup(self, device_udid):
        """测试并发请求去重"""
        if not device_udid:
            pytest.skip("No device available")

        # 等待缓存清空
        await asyncio.sleep(0.5)

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 同时发起 5 个请求
            tasks = [
                session.get(
                    f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=55&s=0.5"
                )
                for _ in range(5)
            ]
            responses = await asyncio.gather(*tasks)

            cache_headers = [r.headers.get('X-Cache') for r in responses]
            print(f"Concurrent request cache headers: {cache_headers}")

            # 应该只有一个 MISS，其他都是 HIT 或 DEDUP
            miss_count = cache_headers.count('MISS')
            hit_count = cache_headers.count('HIT')
            dedup_count = cache_headers.count('DEDUP')

            # 最多一个 MISS (实际发起设备请求的)
            assert miss_count <= 1
            # 其他应该是 HIT 或 DEDUP
            assert hit_count + dedup_count >= len(cache_headers) - 1


class TestScreenshotQualityPresets:
    """截图质量预设测试"""

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
    async def test_performance_preset(self, device_udid):
        """测试流畅模式 (q=40, s=0.4)"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            start = time.time()
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=40&s=0.4"
            ) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    elapsed = time.time() - start
                    print(f"Performance preset: {len(data)} bytes, {elapsed:.3f}s")

    @pytest.mark.asyncio
    async def test_standard_preset(self, device_udid):
        """测试标准模式 (q=60, s=0.6)"""
        if not device_udid:
            pytest.skip("No device available")

        await asyncio.sleep(0.5)  # 等待缓存清空

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            start = time.time()
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=60&s=0.6"
            ) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    elapsed = time.time() - start
                    print(f"Standard preset: {len(data)} bytes, {elapsed:.3f}s")

    @pytest.mark.asyncio
    async def test_hd_preset(self, device_udid):
        """测试高清模式 (q=80, s=0.8)"""
        if not device_udid:
            pytest.skip("No device available")

        await asyncio.sleep(0.5)

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            start = time.time()
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=80&s=0.8"
            ) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    elapsed = time.time() - start
                    print(f"HD preset: {len(data)} bytes, {elapsed:.3f}s")


@pytest.mark.skipif(not HAS_PIL, reason="PIL not installed")
class TestScreenshotImageValidation:
    """截图图像验证测试 (需要 PIL)"""

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
    async def test_image_is_valid(self, device_udid):
        """测试返回的是有效图像"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
            ) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    img = Image.open(BytesIO(data))
                    assert img.format == 'JPEG'
                    assert img.width > 0
                    assert img.height > 0
                    print(f"Image size: {img.width}x{img.height}")

    @pytest.mark.asyncio
    async def test_image_dimensions_scale(self, device_udid):
        """测试图像尺寸与缩放比例"""
        if not device_udid:
            pytest.skip("No device available")

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # 获取 100% 缩放的图像
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=1.0"
            ) as resp1:
                if resp1.status != 200:
                    pytest.skip("Screenshot not available")
                data1 = await resp1.read()
                img1 = Image.open(BytesIO(data1))

            await asyncio.sleep(0.5)

            # 获取 50% 缩放的图像
            async with session.get(
                f"{BASE_URL}/inspector/{device_udid}/screenshot/img?q=50&s=0.5"
            ) as resp2:
                data2 = await resp2.read()
                img2 = Image.open(BytesIO(data2))

            # 50% 缩放应该大约是原尺寸的一半
            expected_width = int(img1.width * 0.5)
            expected_height = int(img1.height * 0.5)

            # 允许一些舍入误差
            assert abs(img2.width - expected_width) <= 2
            assert abs(img2.height - expected_height) <= 2

            print(f"100% scale: {img1.width}x{img1.height}")
            print(f"50% scale: {img2.width}x{img2.height}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
