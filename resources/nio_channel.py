# encoding: utf-8
"""
NIO 风格的通信模块
参考 Java NIO 设计：Channel + Buffer + Selector + 非阻塞

核心概念：
- Channel: WebSocket 双向通道，一个连接处理所有通信
- Buffer: 消息缓冲区，批量处理事件
- Selector: 事件多路复用，统一分发
- EventLoop: 异步事件循环
"""

import asyncio
import json
import time
import base64
from io import BytesIO
from typing import Dict, Optional, Callable, Any
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from aiohttp import web, WSMsgType
from common.logger import logger
from service.impl.phone_service_impl import phone_service
from service.impl.device_service_impl import AndroidDevice
from resources.aio_pool import hp_device_service


class EventType(Enum):
    """事件类型枚举"""
    SCREENSHOT = "screenshot"
    TOUCH = "touch"
    SWIPE = "swipe"
    INPUT = "input"
    KEYEVENT = "keyevent"
    HEARTBEAT = "heartbeat"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"


@dataclass
class Event:
    """事件对象 - 类似 NIO 的 ByteBuffer"""
    type: EventType
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(time.time_ns()))


@dataclass
class DeviceChannel:
    """
    设备通道 - 类似 Java NIO 的 SocketChannel
    封装与设备的连接，支持双向通信
    """
    udid: str
    device: AndroidDevice
    ip: str
    port: int
    last_active: float = field(default_factory=time.time)

    # 缓冲区 - 用于批量处理
    event_buffer: deque = field(default_factory=lambda: deque(maxlen=100))

    def is_active(self, timeout: float = 60.0) -> bool:
        """检查通道是否活跃"""
        return time.time() - self.last_active < timeout

    def touch(self):
        """更新活跃时间"""
        self.last_active = time.time()


class ChannelPool:
    """
    通道池 - 类似 NIO 的连接池
    管理所有设备连接，复用连接
    """

    def __init__(self, max_size: int = 50, idle_timeout: float = 120.0):
        self._channels: Dict[str, DeviceChannel] = {}
        self._max_size = max_size
        self._idle_timeout = idle_timeout
        self._lock = asyncio.Lock()

    async def get_channel(self, udid: str) -> Optional[DeviceChannel]:
        """获取或创建设备通道"""
        async with self._lock:
            # 检查是否已存在
            if udid in self._channels:
                channel = self._channels[udid]
                if channel.is_active(self._idle_timeout):
                    channel.touch()
                    return channel
                else:
                    # 过期了，移除
                    del self._channels[udid]

            # 创建新通道
            try:
                device_info = await phone_service.query_info_by_udid(udid)
                if not device_info:
                    return None

                ip = device_info['ip']
                port = device_info['port']
                device = AndroidDevice(f"http://{ip}:{port}")

                channel = DeviceChannel(
                    udid=udid,
                    device=device,
                    ip=ip,
                    port=port
                )

                # 检查池大小，清理过期连接
                if len(self._channels) >= self._max_size:
                    await self._cleanup()

                self._channels[udid] = channel
                return channel

            except Exception as e:
                logger.error(f"创建设备通道失败 {udid}: {e}")
                return None

    async def _cleanup(self):
        """清理过期的通道"""
        expired = [
            udid for udid, ch in self._channels.items()
            if not ch.is_active(self._idle_timeout)
        ]
        for udid in expired:
            del self._channels[udid]
            logger.debug(f"清理过期通道: {udid}")

    async def close_all(self):
        """关闭所有通道"""
        async with self._lock:
            self._channels.clear()


class EventProcessor:
    """
    事件处理器 - 类似 NIO 的 Selector
    多路复用处理事件
    """

    def __init__(self, channel_pool: ChannelPool):
        self._pool = channel_pool
        self._handlers: Dict[EventType, Callable] = {}
        self._running = False
        self._event_queue: asyncio.Queue = asyncio.Queue()

        # 注册默认处理器
        self._register_handlers()

    def _register_handlers(self):
        """注册事件处理器"""
        self._handlers[EventType.SCREENSHOT] = self._handle_screenshot
        self._handlers[EventType.TOUCH] = self._handle_touch
        self._handlers[EventType.SWIPE] = self._handle_swipe
        self._handlers[EventType.INPUT] = self._handle_input
        self._handlers[EventType.KEYEVENT] = self._handle_keyevent

    async def process_event(self, udid: str, event: Event) -> Dict[str, Any]:
        """处理单个事件"""
        channel = await self._pool.get_channel(udid)
        if not channel:
            return {"status": "error", "message": "Device not found"}

        handler = self._handlers.get(event.type)
        if not handler:
            return {"status": "error", "message": f"Unknown event type: {event.type}"}

        try:
            result = await handler(channel, event)
            channel.touch()
            return result
        except Exception as e:
            logger.error(f"处理事件失败 {event.type}: {e}")
            return {"status": "error", "message": str(e)}

    async def _handle_screenshot(self, channel: DeviceChannel, event: Event) -> Dict:
        """处理截图请求（使用高性能服务）"""
        quality = event.data.get("quality", 60)

        # 使用高性能服务（线程池+缓存）
        b64data = await hp_device_service.screenshot(channel.udid, quality)

        if b64data:
            return {
                "status": "ok",
                "type": "screenshot",
                "encoding": "base64",
                "data": b64data,
                "timestamp": time.time()
            }
        else:
            return {"status": "error", "message": "Screenshot failed"}

    async def _handle_touch(self, channel: DeviceChannel, event: Event) -> Dict:
        """处理触摸事件（使用高性能服务）"""
        x = event.data.get("x")
        y = event.data.get("y")
        if x is None or y is None:
            return {"status": "error", "message": "Missing coordinates"}

        success = await hp_device_service.touch(channel.udid, int(x), int(y))
        return {"status": "ok" if success else "error", "type": "touch"}

    async def _handle_swipe(self, channel: DeviceChannel, event: Event) -> Dict:
        """处理滑动事件（使用高性能服务）"""
        x1 = event.data.get("x1")
        y1 = event.data.get("y1")
        x2 = event.data.get("x2")
        y2 = event.data.get("y2")
        duration = event.data.get("duration", 0.2)

        success = await hp_device_service.swipe(
            channel.udid, int(x1), int(y1), int(x2), int(y2), duration
        )
        return {"status": "ok" if success else "error", "type": "swipe"}

    async def _handle_input(self, channel: DeviceChannel, event: Event) -> Dict:
        """处理文字输入（使用高性能服务）"""
        text = event.data.get("text", "")
        if text:
            success = await hp_device_service.input_text(channel.udid, text)
            return {"status": "ok" if success else "error", "type": "input"}
        return {"status": "ok", "type": "input"}

    async def _handle_keyevent(self, channel: DeviceChannel, event: Event) -> Dict:
        """处理按键事件"""
        key = event.data.get("key", "")
        key_map = {
            "Enter": "enter", "Backspace": "del", "Delete": "forward_del",
            "Home": "home", "Back": "back", "Tab": "tab", "Escape": "back",
            "ArrowUp": "dpad_up", "ArrowDown": "dpad_down",
            "ArrowLeft": "dpad_left", "ArrowRight": "dpad_right",
        }
        android_key = key_map.get(key, key.lower())
        channel.device.device.press(android_key)
        return {"status": "ok", "type": "keyevent"}


class WebSocketSession:
    """
    WebSocket 会话 - 类似 NIO 的 SelectionKey
    管理单个客户端的 WebSocket 连接
    """

    def __init__(self, ws: web.WebSocketResponse, udid: str, processor: EventProcessor):
        self.ws = ws
        self.udid = udid
        self.processor = processor
        self.subscriptions: set = set()
        self.running = False
        self._screenshot_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动会话"""
        self.running = True
        logger.info(f"WebSocket 会话启动: {self.udid}")

    async def stop(self):
        """停止会话"""
        self.running = False
        if self._screenshot_task:
            self._screenshot_task.cancel()
        logger.info(f"WebSocket 会话关闭: {self.udid}")

    async def handle_message(self, msg: str) -> Optional[Dict]:
        """处理收到的消息"""
        try:
            data = json.loads(msg)
            event_type = data.get("type", "")

            # 订阅/取消订阅截图流
            if event_type == "subscribe":
                target = data.get("target", "")
                if target == "screenshot":
                    await self._start_screenshot_stream(data.get("interval", 50))
                self.subscriptions.add(target)
                return {"status": "ok", "type": "subscribed", "target": target}

            elif event_type == "unsubscribe":
                target = data.get("target", "")
                if target == "screenshot":
                    await self._stop_screenshot_stream()
                self.subscriptions.discard(target)
                return {"status": "ok", "type": "unsubscribed", "target": target}

            # 处理普通事件
            event = Event(
                type=EventType(event_type),
                data=data.get("data", {})
            )
            return await self.processor.process_event(self.udid, event)

        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            return {"status": "error", "message": str(e)}

    async def _start_screenshot_stream(self, interval_ms: int = 50):
        """启动截图流推送"""
        if self._screenshot_task and not self._screenshot_task.done():
            return

        async def stream():
            interval = max(interval_ms, 30) / 1000.0  # 最小30ms
            while self.running and "screenshot" in self.subscriptions:
                try:
                    event = Event(type=EventType.SCREENSHOT, data={"quality": 50})
                    result = await self.processor.process_event(self.udid, event)
                    if self.running and not self.ws.closed:
                        await self.ws.send_json(result)
                    await asyncio.sleep(interval)
                except Exception as e:
                    logger.error(f"截图流错误: {e}")
                    await asyncio.sleep(0.5)

        self._screenshot_task = asyncio.create_task(stream())

    async def _stop_screenshot_stream(self):
        """停止截图流"""
        if self._screenshot_task:
            self._screenshot_task.cancel()
            self._screenshot_task = None


class NIOServer:
    """
    NIO 服务器 - 统一管理所有通信
    类似 Java NIO 的 ServerSocketChannel + Selector
    """

    def __init__(self):
        self.channel_pool = ChannelPool()
        self.processor = EventProcessor(self.channel_pool)
        self.sessions: Dict[str, WebSocketSession] = {}

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """处理 WebSocket 连接"""
        udid = request.match_info.get("udid", "")
        if not udid:
            raise web.HTTPBadRequest(text="Missing udid")

        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)

        # 创建会话
        session = WebSocketSession(ws, udid, self.processor)
        session_id = f"{udid}_{id(ws)}"
        self.sessions[session_id] = session

        await session.start()

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    result = await session.handle_message(msg.data)
                    if result and not ws.closed:
                        await ws.send_json(result)
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket 错误: {ws.exception()}")
                    break
        finally:
            await session.stop()
            del self.sessions[session_id]

        return ws

    async def handle_stats(self, request: web.Request) -> web.Response:
        """返回性能统计"""
        stats = hp_device_service.stats()
        return web.json_response(stats)

    def setup_routes(self, app: web.Application):
        """注册路由"""
        app.router.add_get("/nio/{udid}/ws", self.handle_websocket)
        app.router.add_get("/nio/stats", self.handle_stats)


# 全局实例
nio_server = NIOServer()


def setup_nio_routes(app: web.Application):
    """设置 NIO 路由"""
    nio_server.setup_routes(app)
