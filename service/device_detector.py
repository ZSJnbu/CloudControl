# encoding: utf-8
"""
--------------------------------------
@describe 自动检测Android设备 (简化稳定版)
@version: 3.0
@project: CloudControl
@file: device_detector.py
---------------------------------------
"""
import asyncio
import subprocess
import re
import hashlib
from datetime import datetime
from typing import Dict, Optional, Set
from common.logger import logger


# 设备类型常量
DEVICE_TYPE_USB = 'usb'
DEVICE_TYPE_EMULATOR = 'emulator'
DEVICE_TYPE_WIFI = 'wifi'


def detect_device_type(serial: str) -> str:
    """根据序列号检测设备类型"""
    if not serial:
        return DEVICE_TYPE_USB
    # 先检查模拟器 (emulator- 或 127.0.0.1:)
    if serial.startswith('emulator-') or serial.startswith('127.0.0.1:'):
        return DEVICE_TYPE_EMULATOR
    # 再检查 WiFi 设备 (IP:Port 格式)
    if re.match(r'^\d+\.\d+\.\d+\.\d+:\d+$', serial):
        return DEVICE_TYPE_WIFI
    return DEVICE_TYPE_USB


def generate_udid(serial: str, model: str) -> str:
    """生成设备唯一标识符"""
    clean_serial = re.sub(r'[^A-Za-z0-9_-]', '_', serial or 'unknown')
    clean_model = re.sub(r'[^A-Za-z0-9_-]', '_', model or 'unknown')
    return f"{clean_serial}-{clean_model}"


class DeviceDetector:
    """
    简化的设备检测器 - 使用快速轮询确保实时响应
    """

    def __init__(self):
        self._running = False
        self._devices: Dict[str, dict] = {}  # serial -> device_info
        self._poll_interval = 1.0  # 轮询间隔(秒)

    def get_adb_devices(self) -> Set[str]:
        """获取当前ADB连接的设备列表"""
        try:
            result = subprocess.run(
                ['adb', 'devices'],
                capture_output=True,
                text=True,
                timeout=5
            )

            devices = set()
            for line in result.stdout.strip().split('\n')[1:]:  # 跳过标题行
                parts = line.strip().split('\t')
                if len(parts) >= 2 and parts[1] == 'device':
                    devices.add(parts[0])

            return devices

        except Exception as e:
            logger.error(f"[DETECTOR] 获取设备列表失败: {e}")
            return set()

    def get_device_info(self, serial: str) -> Optional[dict]:
        """获取设备详细信息"""
        try:
            def adb_shell(cmd):
                result = subprocess.run(
                    ['adb', '-s', serial, 'shell', cmd],
                    capture_output=True, text=True, timeout=5
                )
                return result.stdout.strip()

            model = adb_shell('getprop ro.product.model')
            brand = adb_shell('getprop ro.product.brand')
            version = adb_shell('getprop ro.build.version.release')
            sdk = adb_shell('getprop ro.build.version.sdk')

            # 获取屏幕分辨率
            wm_size = adb_shell('wm size')
            width, height = 1080, 1920
            match = re.search(r'(\d+)x(\d+)', wm_size)
            if match:
                width, height = int(match.group(1)), int(match.group(2))

            device_type = detect_device_type(serial)
            udid = generate_udid(serial, model)

            # 获取设备IP (用于atx-agent通信)
            if device_type == DEVICE_TYPE_WIFI:
                ip = serial.split(':')[0]
            else:
                ip = adb_shell('ip route | grep wlan0 | awk \'{print $9}\'') or '10.0.2.16'

            return {
                'udid': udid,
                'serial': serial,
                'ip': ip,
                'port': 7912,
                'model': model or 'Unknown',
                'brand': brand or 'Unknown',
                'version': version or 'Unknown',
                'sdk': int(sdk) if sdk.isdigit() else 0,
                'display': {'width': width, 'height': height},
                'device_type': device_type,
                'present': True,
                'ready': True,
                'using': False,
                'is_server': False,
                'is_mock': False,
                'memory': {'total': 0},
                'cpu': {'cores': 0},
                'battery': {'level': 100},
                'createdAt': datetime.now().isoformat(),
                'updatedAt': datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"[DETECTOR] 获取设备 {serial} 信息失败: {e}")
            return None

    async def init_atx_agent(self, serial: str) -> bool:
        """初始化设备上的atx-agent"""
        try:
            import uiautomator2 as u2

            logger.info(f"[DETECTOR] 初始化 atx-agent: {serial}")

            device_type = detect_device_type(serial)
            if device_type in (DEVICE_TYPE_WIFI, DEVICE_TYPE_EMULATOR):
                d = u2.connect(serial)
            else:
                d = u2.connect_usb(serial)

            info = d.info
            logger.info(f"[DETECTOR] atx-agent 就绪: {serial} ({info.get('productName', 'Unknown')})")
            return True

        except Exception as e:
            logger.error(f"[DETECTOR] atx-agent 初始化失败 {serial}: {e}")
            return False

    async def register_device(self, device_info: dict):
        """注册设备到数据库"""
        from database.sqlite_helper import motor

        try:
            await motor.upsert(device_info['udid'], device_info)
            logger.info(f"[DETECTOR] 设备注册成功: {device_info['udid']}")
        except Exception as e:
            logger.error(f"[DETECTOR] 设备注册失败: {e}")

    async def unregister_device(self, serial: str):
        """标记设备离线"""
        from database.sqlite_helper import motor

        if serial not in self._devices:
            return

        device_info = self._devices[serial]
        try:
            await motor.update(device_info['udid'], {'present': False})
            logger.info(f"[DETECTOR] 设备离线: {device_info['udid']}")
        except Exception as e:
            logger.error(f"[DETECTOR] 更新设备状态失败: {e}")

    async def sync_devices(self):
        """同步设备状态 - 核心检测逻辑"""
        # 获取当前ADB设备
        current_serials = self.get_adb_devices()
        known_serials = set(self._devices.keys())

        # 检测新设备
        new_serials = current_serials - known_serials
        for serial in new_serials:
            logger.info(f"[DETECTOR] 发现新设备: {serial}")

            # 获取设备信息
            device_info = self.get_device_info(serial)
            if not device_info:
                continue

            # 初始化atx-agent
            if await self.init_atx_agent(serial):
                # 注册到数据库
                await self.register_device(device_info)
                self._devices[serial] = device_info
                logger.info(f"[DETECTOR] 设备已注册: {device_info['udid']}")
            else:
                logger.warning(f"[DETECTOR] 设备 {serial} atx-agent 初始化失败，跳过")

        # 检测断开的设备
        disconnected_serials = known_serials - current_serials
        for serial in disconnected_serials:
            logger.info(f"[DETECTOR] 设备断开: {serial}")
            await self.unregister_device(serial)
            del self._devices[serial]

    async def _poll_loop(self):
        """轮询循环"""
        logger.info(f"[DETECTOR] 启动设备轮询 (间隔: {self._poll_interval}s)")

        while self._running:
            try:
                await self.sync_devices()
            except Exception as e:
                logger.error(f"[DETECTOR] 同步错误: {e}")

            await asyncio.sleep(self._poll_interval)

    async def start(self):
        """启动设备检测"""
        if self._running:
            return

        self._running = True

        # 初始同步
        logger.info("[DETECTOR] 执行初始设备扫描...")
        await self.sync_devices()
        logger.info(f"[DETECTOR] 初始扫描完成，发现 {len(self._devices)} 台设备")

        # 启动轮询任务
        asyncio.create_task(self._poll_loop())

    async def stop(self):
        """停止设备检测"""
        self._running = False
        logger.info("[DETECTOR] 设备检测已停止")

    def get_devices(self) -> list:
        """获取当前在线设备列表"""
        return list(self._devices.values())


# 全局实例
device_detector = DeviceDetector()
