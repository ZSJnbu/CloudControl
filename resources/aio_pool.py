# encoding: utf-8
"""
AIO 异步连接池和线程池优化模块
参考 Java NIO/AIO + 线程池设计

核心优化：
1. ThreadPoolExecutor - 处理阻塞的设备操作
2. ConnectionPool - 智能连接池管理
3. AsyncBatchProcessor - 批量处理请求
4. ScreenshotCache - 截图缓存优化
"""

import asyncio
import time
import base64
import hashlib
from io import BytesIO
from typing import Dict, Optional, List, Callable, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from functools import partial
import threading

from common.logger import logger
from service.impl.phone_service_impl import phone_service
from service.impl.device_service_impl import AndroidDevice


# ============== 线程池执行器 ==============
class DeviceThreadPool:
    """
    设备操作线程池
    类似 Java 的 ThreadPoolExecutor
    用于执行阻塞的设备操作（截图、触控等）
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_pool()
        return cls._instance

    def _init_pool(self):
        # 针对 1000 设备高并发优化
        # IO密集型任务，线程数可以较高
        import os
        core_count = os.cpu_count() or 4

        # 计算最优线程数：
        # - 对于IO密集型，建议 CPU核心数 * (1 + 等待时间/计算时间)
        # - 截图操作等待时间约为计算时间的10倍
        # - 但也不能太高，避免上下文切换开销
        max_workers = min(core_count * 20, 200)  # 最多200线程

        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="DeviceWorker"
        )
        logger.info(f"[AIO] 线程池初始化: 最大线程数={max_workers} (CPU核心数={core_count})")

    async def run_blocking(self, func: Callable, *args, **kwargs) -> Any:
        """
        在线程池中执行阻塞操作
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            partial(func, *args, **kwargs)
        )

    def shutdown(self):
        """关闭线程池"""
        self.executor.shutdown(wait=True)


# ============== 智能连接池 ==============
@dataclass
class PooledConnection:
    """连接池中的连接对象"""
    device: AndroidDevice
    udid: str
    ip: str
    port: int
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    use_count: int = 0
    is_healthy: bool = True

    def touch(self):
        self.last_used = time.time()
        self.use_count += 1


class SmartConnectionPool:
    """
    智能连接池
    类似 Java 的 HikariCP 连接池

    特点：
    1. 连接复用
    2. 健康检查
    3. 自动清理
    4. LRU 淘汰策略
    """

    def __init__(
        self,
        max_size: int = 1200,  # 支持1000+设备
        min_idle: int = 10,
        max_idle_time: float = 600.0,  # 10分钟
        health_check_interval: float = 120.0
    ):
        self._pool: OrderedDict[str, PooledConnection] = OrderedDict()
        self._max_size = max_size
        self._min_idle = min_idle
        self._max_idle_time = max_idle_time
        self._health_check_interval = health_check_interval
        self._lock = asyncio.Lock()
        self._thread_pool = DeviceThreadPool()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动连接池"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("[AIO] 连接池已启动")

    async def stop(self):
        """停止连接池"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        async with self._lock:
            self._pool.clear()
        logger.info("[AIO] 连接池已停止")

    async def get_connection(self, udid: str) -> Optional[PooledConnection]:
        """获取连接（复用或创建新连接）"""
        async with self._lock:
            # 检查是否已有连接
            if udid in self._pool:
                conn = self._pool[udid]
                if conn.is_healthy and self._is_alive(conn):
                    conn.touch()
                    # 移到末尾（LRU）
                    self._pool.move_to_end(udid)
                    return conn
                else:
                    # 不健康的连接，移除
                    del self._pool[udid]

            # 创建新连接
            try:
                device_info = await phone_service.query_info_by_udid(udid)
                if not device_info:
                    return None

                ip = device_info['ip']
                port = device_info['port']

                # 在线程池中创建连接（可能阻塞）
                device = await self._thread_pool.run_blocking(
                    AndroidDevice, f"http://{ip}:{port}"
                )

                conn = PooledConnection(
                    device=device,
                    udid=udid,
                    ip=ip,
                    port=port
                )

                # 检查池大小
                while len(self._pool) >= self._max_size:
                    # 移除最久未使用的连接（LRU）
                    oldest_key = next(iter(self._pool))
                    del self._pool[oldest_key]
                    logger.debug(f"[AIO] 移除最久未用连接: {oldest_key}")

                self._pool[udid] = conn
                logger.debug(f"[AIO] 创建新连接: {udid}")
                return conn

            except Exception as e:
                logger.error(f"[AIO] 创建连接失败 {udid}: {e}")
                return None

    def _is_alive(self, conn: PooledConnection) -> bool:
        """检查连接是否存活"""
        return time.time() - conn.last_used < self._max_idle_time

    async def _cleanup_loop(self):
        """定期清理过期连接"""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self._cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[AIO] 清理任务错误: {e}")

    async def _cleanup(self):
        """清理过期连接"""
        async with self._lock:
            now = time.time()
            expired = []

            for udid, conn in self._pool.items():
                if now - conn.last_used > self._max_idle_time:
                    expired.append(udid)

            # 保留最小空闲连接数
            keep_count = max(0, len(self._pool) - len(expired))
            if keep_count < self._min_idle:
                expired = expired[:len(expired) - (self._min_idle - keep_count)]

            for udid in expired:
                del self._pool[udid]
                logger.debug(f"[AIO] 清理过期连接: {udid}")

    def stats(self) -> Dict:
        """返回连接池统计信息"""
        return {
            "total": len(self._pool),
            "max_size": self._max_size,
            "connections": [
                {
                    "udid": conn.udid,
                    "use_count": conn.use_count,
                    "idle_seconds": round(time.time() - conn.last_used, 1)
                }
                for conn in self._pool.values()
            ]
        }


# ============== 截图缓存 ==============
class ScreenshotCache:
    """
    截图缓存
    减少重复截图请求

    策略：
    1. 短时间内（如 50ms）的重复请求返回缓存
    2. LRU 淘汰
    """

    def __init__(self, max_size: int = 10, ttl_ms: float = 50):
        self._cache: OrderedDict[str, tuple] = OrderedDict()  # (data, timestamp)
        self._max_size = max_size
        self._ttl = ttl_ms / 1000.0
        self._lock = threading.Lock()

    def get(self, udid: str) -> Optional[bytes]:
        """获取缓存的截图"""
        with self._lock:
            if udid in self._cache:
                data, ts = self._cache[udid]
                if time.time() - ts < self._ttl:
                    self._cache.move_to_end(udid)
                    return data
                else:
                    del self._cache[udid]
            return None

    def set(self, udid: str, data: bytes):
        """设置截图缓存"""
        with self._lock:
            if udid in self._cache:
                self._cache.move_to_end(udid)
            self._cache[udid] = (data, time.time())

            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)


# ============== 异步批处理器 ==============
class AsyncBatchProcessor:
    """
    异步批处理器
    将多个请求合并处理

    适用于：
    - 批量触控事件
    - 批量截图请求
    """

    def __init__(self, batch_size: int = 10, flush_interval: float = 0.05):
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._queue: asyncio.Queue = asyncio.Queue()
        self._handlers: Dict[str, Callable] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def register_handler(self, event_type: str, handler: Callable):
        """注册事件处理器"""
        self._handlers[event_type] = handler

    async def start(self):
        """启动处理器"""
        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("[AIO] 批处理器已启动")

    async def stop(self):
        """停止处理器"""
        self._running = False
        if self._task:
            self._task.cancel()

    async def submit(self, event_type: str, data: Dict) -> asyncio.Future:
        """提交事件"""
        future = asyncio.get_event_loop().create_future()
        await self._queue.put((event_type, data, future))
        return future

    async def _process_loop(self):
        """处理循环"""
        while self._running:
            batch = []
            deadline = time.time() + self._flush_interval

            # 收集批次
            while len(batch) < self._batch_size:
                timeout = max(0, deadline - time.time())
                try:
                    item = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=timeout
                    )
                    batch.append(item)
                except asyncio.TimeoutError:
                    break

            if batch:
                await self._process_batch(batch)

    async def _process_batch(self, batch: List[tuple]):
        """处理批次"""
        # 按事件类型分组
        groups: Dict[str, List] = {}
        for event_type, data, future in batch:
            if event_type not in groups:
                groups[event_type] = []
            groups[event_type].append((data, future))

        # 并发处理各组
        tasks = []
        for event_type, items in groups.items():
            handler = self._handlers.get(event_type)
            if handler:
                tasks.append(self._process_group(handler, items))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_group(self, handler: Callable, items: List[tuple]):
        """处理一组事件"""
        for data, future in items:
            try:
                result = await handler(data)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)


# ============== 高性能设备服务 ==============
class HighPerformanceDeviceService:
    """
    高性能设备服务
    整合所有优化组件
    """

    def __init__(self):
        self.connection_pool = SmartConnectionPool()
        self.thread_pool = DeviceThreadPool()
        self.screenshot_cache = ScreenshotCache()
        self.batch_processor = AsyncBatchProcessor()

    async def start(self):
        """启动服务"""
        await self.connection_pool.start()
        await self.batch_processor.start()
        logger.info("[AIO] 高性能设备服务已启动")

    async def stop(self):
        """停止服务"""
        await self.batch_processor.stop()
        await self.connection_pool.stop()
        self.thread_pool.shutdown()

    async def screenshot(self, udid: str, quality: int = 60) -> Optional[str]:
        """
        获取截图（优化版）
        1. 先查缓存
        2. 使用线程池执行阻塞操作
        3. 更新缓存
        """
        # 检查缓存
        cached = self.screenshot_cache.get(udid)
        if cached:
            return base64.b64encode(cached).decode('utf-8')

        # 获取连接
        conn = await self.connection_pool.get_connection(udid)
        if not conn:
            return None

        try:
            # 在线程池中执行截图
            def take_screenshot():
                buffer = BytesIO()
                conn.device.screenshot().convert("RGB").save(
                    buffer, format='JPEG', quality=quality
                )
                return buffer.getvalue()

            data = await self.thread_pool.run_blocking(take_screenshot)

            # 更新缓存
            self.screenshot_cache.set(udid, data)

            return base64.b64encode(data).decode('utf-8')

        except Exception as e:
            logger.error(f"[AIO] 截图失败 {udid}: {e}")
            conn.is_healthy = False
            return None

    async def touch(self, udid: str, x: int, y: int) -> bool:
        """触控操作（优化版）"""
        conn = await self.connection_pool.get_connection(udid)
        if not conn:
            return False

        try:
            await self.thread_pool.run_blocking(
                conn.device.device.click, x, y
            )
            return True
        except Exception as e:
            logger.error(f"[AIO] 触控失败 {udid}: {e}")
            conn.is_healthy = False
            return False

    async def swipe(self, udid: str, x1: int, y1: int, x2: int, y2: int, duration: float = 0.2) -> bool:
        """滑动操作（优化版）"""
        conn = await self.connection_pool.get_connection(udid)
        if not conn:
            return False

        try:
            await self.thread_pool.run_blocking(
                conn.device.device.swipe, x1, y1, x2, y2, duration
            )
            return True
        except Exception as e:
            logger.error(f"[AIO] 滑动失败 {udid}: {e}")
            conn.is_healthy = False
            return False

    async def input_text(self, udid: str, text: str) -> bool:
        """输入文字（优化版）"""
        conn = await self.connection_pool.get_connection(udid)
        if not conn:
            return False

        try:
            def do_input():
                conn.device.device.set_fastinput_ime(True)
                conn.device.device.send_keys(text, clear=False)

            await self.thread_pool.run_blocking(do_input)
            return True
        except Exception as e:
            logger.error(f"[AIO] 输入失败 {udid}: {e}")
            return False

    def stats(self) -> Dict:
        """返回性能统计"""
        return {
            "connection_pool": self.connection_pool.stats(),
            "thread_pool": {
                "active_threads": self.thread_pool.executor._threads.__len__()
                if hasattr(self.thread_pool.executor, '_threads') else 0
            }
        }


# 全局实例
hp_device_service = HighPerformanceDeviceService()


async def init_aio_service():
    """初始化 AIO 服务"""
    await hp_device_service.start()


async def shutdown_aio_service():
    """关闭 AIO 服务"""
    await hp_device_service.stop()
