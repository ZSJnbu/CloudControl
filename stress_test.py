#!/usr/bin/env python3
# encoding: utf-8
"""
CloudControl 压力测试工具
目标：支持 1000 台手机同时连接和操作

测试项目：
1. WebSocket 连接并发
2. 截图请求并发
3. 触控操作并发
4. 混合操作压力测试

使用方法：
    python stress_test.py --connections 1000 --duration 60
"""

import asyncio
import aiohttp
import argparse
import time
import json
import random
import statistics
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import defaultdict
import sys


@dataclass
class TestResult:
    """测试结果"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    response_times: List[float] = field(default_factory=list)
    errors: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    start_time: float = 0
    end_time: float = 0

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0
        return self.successful_requests / self.total_requests * 100

    @property
    def qps(self) -> float:
        if self.duration == 0:
            return 0
        return self.successful_requests / self.duration

    @property
    def avg_response_time(self) -> float:
        if not self.response_times:
            return 0
        return statistics.mean(self.response_times) * 1000  # ms

    @property
    def p50_response_time(self) -> float:
        if not self.response_times:
            return 0
        return statistics.median(self.response_times) * 1000

    @property
    def p95_response_time(self) -> float:
        if not self.response_times:
            return 0
        sorted_times = sorted(self.response_times)
        idx = int(len(sorted_times) * 0.95)
        return sorted_times[idx] * 1000

    @property
    def p99_response_time(self) -> float:
        if not self.response_times:
            return 0
        sorted_times = sorted(self.response_times)
        idx = int(len(sorted_times) * 0.99)
        return sorted_times[min(idx, len(sorted_times) - 1)] * 1000


class StressTestClient:
    """压力测试客户端"""

    def __init__(self, base_url: str, device_id: int):
        self.base_url = base_url
        self.device_id = device_id
        self.udid = f"stress-test-device-{device_id}"
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
        self.result = TestResult()

    async def connect(self) -> bool:
        """建立连接"""
        try:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
            return True
        except Exception as e:
            self.result.errors[str(type(e).__name__)] += 1
            return False

    async def disconnect(self):
        """断开连接"""
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.session:
            await self.session.close()

    async def connect_websocket(self) -> bool:
        """连接 WebSocket"""
        try:
            ws_url = f"{self.base_url.replace('http', 'ws')}/nio/{self.udid}/ws"
            self.ws = await self.session.ws_connect(ws_url, heartbeat=30)
            return True
        except Exception as e:
            self.result.errors[f"WS_{type(e).__name__}"] += 1
            return False

    async def send_screenshot_request(self) -> bool:
        """发送截图请求（HTTP模式）"""
        start = time.time()
        try:
            async with self.session.get(
                f"{self.base_url}/inspector/{self.udid}/screenshot"
            ) as resp:
                elapsed = time.time() - start
                self.result.total_requests += 1
                if resp.status == 200:
                    self.result.successful_requests += 1
                    self.result.response_times.append(elapsed)
                    return True
                else:
                    self.result.failed_requests += 1
                    self.result.errors[f"HTTP_{resp.status}"] += 1
                    return False
        except Exception as e:
            elapsed = time.time() - start
            self.result.total_requests += 1
            self.result.failed_requests += 1
            self.result.errors[type(e).__name__] += 1
            return False

    async def send_touch_request(self, x: int = 500, y: int = 500) -> bool:
        """发送触控请求"""
        start = time.time()
        try:
            async with self.session.post(
                f"{self.base_url}/inspector/{self.udid}/touch",
                json={"action": "click", "x": x, "y": y}
            ) as resp:
                elapsed = time.time() - start
                self.result.total_requests += 1
                if resp.status == 200:
                    self.result.successful_requests += 1
                    self.result.response_times.append(elapsed)
                    return True
                else:
                    self.result.failed_requests += 1
                    self.result.errors[f"HTTP_{resp.status}"] += 1
                    return False
        except Exception as e:
            self.result.total_requests += 1
            self.result.failed_requests += 1
            self.result.errors[type(e).__name__] += 1
            return False

    async def send_ws_message(self, msg_type: str, data: dict = None) -> bool:
        """发送 WebSocket 消息"""
        if not self.ws or self.ws.closed:
            return False

        start = time.time()
        try:
            message = {"type": msg_type, "data": data or {}}
            await self.ws.send_json(message)

            # 等待响应
            response = await asyncio.wait_for(self.ws.receive(), timeout=10)
            elapsed = time.time() - start

            self.result.total_requests += 1
            if response.type == aiohttp.WSMsgType.TEXT:
                self.result.successful_requests += 1
                self.result.response_times.append(elapsed)
                return True
            else:
                self.result.failed_requests += 1
                return False

        except asyncio.TimeoutError:
            self.result.total_requests += 1
            self.result.failed_requests += 1
            self.result.errors["Timeout"] += 1
            return False
        except Exception as e:
            self.result.total_requests += 1
            self.result.failed_requests += 1
            self.result.errors[type(e).__name__] += 1
            return False


class StressTest:
    """压力测试主类"""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        num_connections: int = 100,
        duration: int = 60,
        mode: str = "mixed"
    ):
        self.base_url = base_url
        self.num_connections = num_connections
        self.duration = duration
        self.mode = mode
        self.clients: List[StressTestClient] = []
        self.running = False
        self.global_result = TestResult()

    async def setup(self):
        """初始化测试客户端"""
        print(f"\n{'='*60}")
        print(f"  CloudControl 压力测试")
        print(f"{'='*60}")
        print(f"  目标服务器: {self.base_url}")
        print(f"  并发连接数: {self.num_connections}")
        print(f"  测试时长: {self.duration} 秒")
        print(f"  测试模式: {self.mode}")
        print(f"{'='*60}\n")

        print("正在创建测试客户端...")
        for i in range(self.num_connections):
            client = StressTestClient(self.base_url, i)
            self.clients.append(client)
            if (i + 1) % 100 == 0:
                print(f"  已创建 {i + 1}/{self.num_connections} 个客户端")

        print("\n正在建立连接...")
        connect_tasks = [client.connect() for client in self.clients]
        results = await asyncio.gather(*connect_tasks, return_exceptions=True)
        connected = sum(1 for r in results if r is True)
        print(f"  成功连接: {connected}/{self.num_connections}")

        if self.mode == "websocket":
            print("\n正在建立 WebSocket 连接...")
            ws_tasks = [client.connect_websocket() for client in self.clients]
            ws_results = await asyncio.gather(*ws_tasks, return_exceptions=True)
            ws_connected = sum(1 for r in ws_results if r is True)
            print(f"  WebSocket 连接成功: {ws_connected}/{self.num_connections}")

    async def run_client_test(self, client: StressTestClient, end_time: float):
        """运行单个客户端的测试"""
        while time.time() < end_time and self.running:
            if self.mode == "screenshot":
                await client.send_screenshot_request()
            elif self.mode == "touch":
                x = random.randint(100, 900)
                y = random.randint(100, 1800)
                await client.send_touch_request(x, y)
            elif self.mode == "websocket":
                if client.ws and not client.ws.closed:
                    await client.send_ws_message("screenshot", {"quality": 50})
                else:
                    await client.send_screenshot_request()
            else:  # mixed
                choice = random.choice(["screenshot", "touch", "touch"])
                if choice == "screenshot":
                    await client.send_screenshot_request()
                else:
                    x = random.randint(100, 900)
                    y = random.randint(100, 1800)
                    await client.send_touch_request(x, y)

            # 短暂休息，模拟真实用户行为
            await asyncio.sleep(random.uniform(0.1, 0.5))

    async def run(self):
        """运行压力测试"""
        await self.setup()

        print(f"\n开始压力测试，持续 {self.duration} 秒...")
        print("-" * 60)

        self.running = True
        self.global_result.start_time = time.time()
        end_time = self.global_result.start_time + self.duration

        # 启动所有客户端测试任务
        tasks = [
            self.run_client_test(client, end_time)
            for client in self.clients
        ]

        # 显示进度
        progress_task = asyncio.create_task(self.show_progress(end_time))

        # 等待所有测试完成
        await asyncio.gather(*tasks, return_exceptions=True)
        self.running = False
        progress_task.cancel()

        self.global_result.end_time = time.time()

        # 汇总结果
        await self.aggregate_results()
        await self.cleanup()
        self.print_report()

    async def show_progress(self, end_time: float):
        """显示测试进度"""
        try:
            while self.running:
                await asyncio.sleep(5)
                elapsed = time.time() - self.global_result.start_time
                remaining = max(0, end_time - time.time())

                total_requests = sum(c.result.total_requests for c in self.clients)
                successful = sum(c.result.successful_requests for c in self.clients)
                qps = successful / elapsed if elapsed > 0 else 0

                print(f"  [{int(elapsed)}s] 请求: {total_requests}, "
                      f"成功: {successful}, QPS: {qps:.1f}, "
                      f"剩余: {int(remaining)}s")

        except asyncio.CancelledError:
            pass

    async def aggregate_results(self):
        """汇总所有客户端的结果"""
        for client in self.clients:
            self.global_result.total_requests += client.result.total_requests
            self.global_result.successful_requests += client.result.successful_requests
            self.global_result.failed_requests += client.result.failed_requests
            self.global_result.response_times.extend(client.result.response_times)
            for error, count in client.result.errors.items():
                self.global_result.errors[error] += count

    async def cleanup(self):
        """清理资源"""
        print("\n正在清理连接...")
        cleanup_tasks = [client.disconnect() for client in self.clients]
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)

    def print_report(self):
        """打印测试报告"""
        r = self.global_result

        print(f"\n{'='*60}")
        print(f"  压力测试报告")
        print(f"{'='*60}")
        print(f"\n  基本信息:")
        print(f"    - 并发连接数: {self.num_connections}")
        print(f"    - 测试时长: {r.duration:.1f} 秒")
        print(f"    - 测试模式: {self.mode}")

        print(f"\n  请求统计:")
        print(f"    - 总请求数: {r.total_requests}")
        print(f"    - 成功请求: {r.successful_requests}")
        print(f"    - 失败请求: {r.failed_requests}")
        print(f"    - 成功率: {r.success_rate:.2f}%")

        print(f"\n  性能指标:")
        print(f"    - QPS (每秒请求数): {r.qps:.1f}")
        print(f"    - 平均响应时间: {r.avg_response_time:.1f} ms")
        print(f"    - P50 响应时间: {r.p50_response_time:.1f} ms")
        print(f"    - P95 响应时间: {r.p95_response_time:.1f} ms")
        print(f"    - P99 响应时间: {r.p99_response_time:.1f} ms")

        if r.errors:
            print(f"\n  错误统计:")
            for error, count in sorted(r.errors.items(), key=lambda x: -x[1]):
                print(f"    - {error}: {count}")

        # 判断是否通过测试
        print(f"\n{'='*60}")
        passed = (
            r.success_rate >= 95 and  # 成功率 >= 95%
            r.p95_response_time < 5000 and  # P95 < 5秒
            self.num_connections >= 1000  # 支持1000连接
        )

        if passed:
            print(f"  ✅ 测试通过！系统可以支持 {self.num_connections} 台设备")
        else:
            print(f"  ❌ 测试未通过")
            if r.success_rate < 95:
                print(f"     - 成功率不足 95% (当前: {r.success_rate:.1f}%)")
            if r.p95_response_time >= 5000:
                print(f"     - P95 响应时间过长 (当前: {r.p95_response_time:.0f}ms)")
            if self.num_connections < 1000:
                print(f"     - 并发数不足 1000 (当前: {self.num_connections})")

        print(f"{'='*60}\n")

        # 返回测试结果
        return passed


async def main():
    parser = argparse.ArgumentParser(description="CloudControl 压力测试工具")
    parser.add_argument(
        "--url", "-u",
        default="http://localhost:8000",
        help="服务器地址 (默认: http://localhost:8000)"
    )
    parser.add_argument(
        "--connections", "-c",
        type=int,
        default=100,
        help="并发连接数 (默认: 100)"
    )
    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=60,
        help="测试时长(秒) (默认: 60)"
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["screenshot", "touch", "websocket", "mixed"],
        default="mixed",
        help="测试模式 (默认: mixed)"
    )
    parser.add_argument(
        "--ramp-up",
        action="store_true",
        help="逐步增加连接数"
    )

    args = parser.parse_args()

    if args.ramp_up:
        # 逐步增加连接数测试
        connection_levels = [10, 50, 100, 200, 500, 1000]
        for level in connection_levels:
            if level > args.connections:
                break
            print(f"\n\n{'#'*60}")
            print(f"# 测试阶段: {level} 并发连接")
            print(f"{'#'*60}")

            test = StressTest(
                base_url=args.url,
                num_connections=level,
                duration=min(30, args.duration),
                mode=args.mode
            )
            await test.run()
            await asyncio.sleep(5)  # 阶段间休息
    else:
        test = StressTest(
            base_url=args.url,
            num_connections=args.connections,
            duration=args.duration,
            mode=args.mode
        )
        await test.run()


if __name__ == "__main__":
    asyncio.run(main())
