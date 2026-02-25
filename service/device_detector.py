# encoding: utf-8
"""
--------------------------------------
@describe 自动检测USB连接的Android设备 (实时监听版)
@version: 2.1
@project: CloudControl
@file: device_detector.py
@note: 支持多种设备名称格式:
       - USB设备: ABCDEF123456, R58N12345678
       - 模拟器: emulator-5554, 127.0.0.1:5555
       - WiFi连接: 192.168.1.100:5555
       - 特殊格式: usb:1-2.3, adb-SERIAL-device
---------------------------------------
"""
import asyncio
import subprocess
import re
import threading
import time
import hashlib
from datetime import datetime
from typing import List, Dict, Optional, Set, Callable
from queue import Queue

from common.logger import logger


# 设备类型常量
DEVICE_TYPE_USB = 'usb'
DEVICE_TYPE_EMULATOR = 'emulator'
DEVICE_TYPE_WIFI = 'wifi'
DEVICE_TYPE_UNKNOWN = 'unknown'


def detect_device_type(serial: str) -> str:
    """
    根据设备序列号检测设备类型
    :param serial: 设备序列号
    :return: 设备类型
    """
    if not serial:
        return DEVICE_TYPE_UNKNOWN

    # WiFi 设备: IP:PORT 格式
    # 例如: 192.168.1.100:5555, 10.0.2.2:5555
    ip_port_pattern = r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)$'
    if re.match(ip_port_pattern, serial):
        return DEVICE_TYPE_WIFI

    # 模拟器: emulator-XXXX 或 127.0.0.1:XXXX
    if serial.startswith('emulator-') or serial.startswith('127.0.0.1:'):
        return DEVICE_TYPE_EMULATOR

    # USB 设备: 通常是字母数字组合
    # 例如: ABCDEF123456, R58N12345678, abc123def456
    if re.match(r'^[A-Za-z0-9]+$', serial):
        return DEVICE_TYPE_USB

    # 特殊格式也视为 USB
    # 例如: usb:1-2.3, adb-SERIAL-device
    return DEVICE_TYPE_USB


def is_wifi_device(serial: str) -> bool:
    """
    判断是否为 WiFi 连接的设备
    """
    device_type = detect_device_type(serial)
    return device_type == DEVICE_TYPE_WIFI


def sanitize_for_udid(text: str) -> str:
    """
    清理文本用于生成 UDID（只保留字母数字和下划线/连字符）
    """
    if not text:
        return "unknown"
    # 替换特殊字符
    text = re.sub(r'[^A-Za-z0-9_-]', '_', text)
    # 移除连续的下划线
    text = re.sub(r'_+', '_', text)
    # 移除首尾的下划线
    text = text.strip('_')
    return text or "unknown"


def generate_udid(serial: str, model: str) -> str:
    """
    生成设备唯一标识符 (UDID)
    :param serial: 设备序列号
    :param model: 设备型号
    :return: UDID
    """
    clean_serial = sanitize_for_udid(serial)
    clean_model = sanitize_for_udid(model)

    # 限制长度，避免过长的 UDID
    if len(clean_serial) > 30:
        # 使用 hash 缩短
        clean_serial = clean_serial[:15] + hashlib.md5(serial.encode()).hexdigest()[:8]

    if len(clean_model) > 30:
        clean_model = clean_model[:30]

    return f"{clean_serial}-{clean_model}"


def extract_ip_from_serial(serial: str) -> Optional[str]:
    """
    从设备序列号中提取 IP 地址（如果有的话）
    """
    # WiFi 格式: 192.168.1.100:5555
    match = re.match(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):\d+$', serial)
    if match:
        return match.group(1)

    # 模拟器本地格式: 127.0.0.1:5555
    if serial.startswith('127.0.0.1:'):
        return '127.0.0.1'

    return None


class DeviceEvent:
    """设备事件"""
    CONNECTED = 'connected'
    DISCONNECTED = 'disconnected'

    def __init__(self, event_type: str, serial: str):
        self.type = event_type
        self.serial = serial
        self.timestamp = time.time()


class ADBDeviceMonitor:
    """
    ADB设备实时监听器
    使用 adb track-devices 实现实时监听设备连接/断开
    在独立线程中运行，通过事件队列与主线程通信
    """

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._event_queue: Queue = Queue()
        self._known_devices: Set[str] = set()
        self._process: Optional[subprocess.Popen] = None

    def start(self):
        """启动监听线程"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="ADBMonitor")
        self._thread.start()
        logger.info("[ADB_MONITOR] 实时监听线程已启动")

    def stop(self):
        """停止监听"""
        self._running = False
        if self._process:
            self._process.terminate()
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("[ADB_MONITOR] 实时监听线程已停止")

    def get_event(self, timeout: float = 0.1) -> Optional[DeviceEvent]:
        """获取设备事件（非阻塞）"""
        try:
            return self._event_queue.get(timeout=timeout)
        except:
            return None

    def _parse_device_line(self, line: str) -> Optional[tuple]:
        """解析设备状态行"""
        line = line.strip()
        if not line or line.startswith('List'):
            return None

        parts = line.split('\t')
        if len(parts) >= 2:
            serial = parts[0].strip()
            status = parts[1].strip()
            return (serial, status)
        return None

    def _monitor_loop(self):
        """监听循环（在独立线程中运行）"""
        retry_count = 0
        max_retries = 5

        while self._running:
            try:
                # 使用 adb track-devices 持续监听
                logger.info("[ADB_MONITOR] 启动 adb track-devices 监听...")
                self._process = subprocess.Popen(
                    ['adb', 'track-devices'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0  # 无缓冲，实时读取
                )

                retry_count = 0  # 重置重试计数

                # 持续读取输出
                # track-devices 输出格式: 4字节十六进制长度 + 设备列表
                # 例如: "001f" + "emulator-5554\tdevice\n"
                while self._running and self._process.poll() is None:
                    # 读取4字节长度前缀
                    length_hex = self._process.stdout.read(4)
                    if not length_hex or len(length_hex) < 4:
                        continue

                    try:
                        # 解析长度（十六进制）
                        data_length = int(length_hex.decode('utf-8'), 16)
                        if data_length == 0:
                            # 空列表，所有设备已断开
                            self._process_device_list("")
                            continue

                        # 读取设备列表数据
                        data = self._process.stdout.read(data_length)
                        if data:
                            device_list = data.decode('utf-8')
                            self._process_device_list(device_list)

                    except (ValueError, UnicodeDecodeError) as e:
                        logger.debug(f"[ADB_MONITOR] 解析数据包错误: {e}")
                        continue

            except FileNotFoundError:
                logger.error("[ADB_MONITOR] ADB未找到，请安装 Android SDK Platform Tools")
                break

            except Exception as e:
                logger.error(f"[ADB_MONITOR] 监听错误: {e}")
                retry_count += 1

                if retry_count >= max_retries:
                    logger.error("[ADB_MONITOR] 重试次数过多，切换到轮询模式")
                    self._fallback_polling()
                    break

                time.sleep(2)  # 等待后重试

    def _process_device_list(self, data: str):
        """处理设备列表数据"""
        current_devices: Set[str] = set()

        for line in data.strip().split('\n'):
            result = self._parse_device_line(line)
            if result:
                serial, status = result
                if status == 'device':  # 只关注已授权的设备
                    current_devices.add(serial)

        # 检测新设备
        new_devices = current_devices - self._known_devices
        for serial in new_devices:
            logger.info(f"[ADB_MONITOR] 设备连接: {serial}")
            self._event_queue.put(DeviceEvent(DeviceEvent.CONNECTED, serial))

        # 检测断开的设备
        disconnected = self._known_devices - current_devices
        for serial in disconnected:
            logger.info(f"[ADB_MONITOR] 设备断开: {serial}")
            self._event_queue.put(DeviceEvent(DeviceEvent.DISCONNECTED, serial))

        self._known_devices = current_devices

    def _fallback_polling(self):
        """降级到轮询模式"""
        logger.info("[ADB_MONITOR] 使用轮询模式")

        while self._running:
            try:
                result = subprocess.run(
                    ['adb', 'devices'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                self._process_device_list(result.stdout)
            except Exception as e:
                logger.error(f"[ADB_MONITOR] 轮询错误: {e}")

            time.sleep(1)  # 轮询间隔1秒


class DeviceDetector:
    """
    自动检测并注册USB连接的Android设备
    使用实时监听 + 事件驱动架构
    """

    def __init__(self, check_interval: int = 5):
        """
        初始化设备检测器
        :param check_interval: 事件处理间隔(秒) - 仅用于备用轮询
        """
        self.check_interval = check_interval
        self._running = False
        self._known_devices: Dict[str, Dict] = {}  # serial -> device_info
        self._task: Optional[asyncio.Task] = None
        self._monitor = ADBDeviceMonitor()
        self._event_handlers: Dict[str, List[Callable]] = {
            DeviceEvent.CONNECTED: [],
            DeviceEvent.DISCONNECTED: []
        }

    def on_device_connected(self, handler: Callable):
        """注册设备连接回调"""
        self._event_handlers[DeviceEvent.CONNECTED].append(handler)

    def on_device_disconnected(self, handler: Callable):
        """注册设备断开回调"""
        self._event_handlers[DeviceEvent.DISCONNECTED].append(handler)

    def _run_adb_command(self, args: List[str]) -> str:
        """执行ADB命令"""
        try:
            result = subprocess.run(
                ['adb'] + args,
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.error("ADB command timeout")
            return ""
        except FileNotFoundError:
            logger.error("ADB not found. Please install Android SDK Platform Tools.")
            return ""
        except Exception as e:
            logger.error(f"ADB command error: {e}")
            return ""

    def get_connected_devices(self) -> List[str]:
        """
        获取当前连接的设备列表
        :return: 设备serial列表
        """
        output = self._run_adb_command(['devices'])
        devices = []

        for line in output.strip().split('\n')[1:]:
            if '\t' in line:
                serial, status = line.split('\t')
                if status == 'device':
                    devices.append(serial.strip())

        return devices

    def get_device_info(self, serial: str) -> Optional[Dict]:
        """
        获取设备详细信息
        支持多种设备名称格式：USB、模拟器、WiFi等
        :param serial: 设备序列号
        :return: 设备信息字典
        """
        try:
            # 检测设备类型
            device_type = detect_device_type(serial)
            logger.debug(f"[DETECTOR] 设备 {serial} 类型: {device_type}")

            def get_prop(prop: str) -> str:
                output = self._run_adb_command(['-s', serial, 'shell', 'getprop', prop])
                return output.strip()

            # 获取基本信息
            model = get_prop('ro.product.model') or 'Unknown'
            brand = get_prop('ro.product.brand') or 'Unknown'
            version = get_prop('ro.build.version.release') or 'Unknown'
            sdk = get_prop('ro.build.version.sdk') or '30'

            # 获取屏幕尺寸
            wm_output = self._run_adb_command(['-s', serial, 'shell', 'wm', 'size'])
            width, height = 1080, 1920
            if 'Physical size:' in wm_output:
                match = re.search(r'(\d+)x(\d+)', wm_output)
                if match:
                    width, height = int(match.group(1)), int(match.group(2))
            elif 'Override size:' in wm_output:
                # 有些设备返回 Override size
                match = re.search(r'Override size:\s*(\d+)x(\d+)', wm_output)
                if match:
                    width, height = int(match.group(1)), int(match.group(2))

            # 获取设备 IP 地址
            device_ip = None

            # 1. 首先尝试从 serial 中提取（WiFi设备）
            device_ip = extract_ip_from_serial(serial)

            # 2. 如果没有，尝试从设备获取
            if not device_ip:
                # 方法1: ip route
                ip_output = self._run_adb_command(['-s', serial, 'shell', 'ip', 'route'])
                for line in ip_output.split('\n'):
                    if 'src' in line:
                        match = re.search(r'src\s+(\d+\.\d+\.\d+\.\d+)', line)
                        if match:
                            ip = match.group(1)
                            # 排除 127.0.0.1
                            if not ip.startswith('127.'):
                                device_ip = ip
                                break

            if not device_ip:
                # 方法2: ip addr show wlan0
                ip_addr_output = self._run_adb_command(['-s', serial, 'shell', 'ip', 'addr', 'show', 'wlan0'])
                match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', ip_addr_output)
                if match:
                    device_ip = match.group(1)

            if not device_ip:
                # 方法3: ifconfig wlan0 (旧版Android)
                ifconfig_output = self._run_adb_command(['-s', serial, 'shell', 'ifconfig', 'wlan0'])
                match = re.search(r'inet addr:(\d+\.\d+\.\d+\.\d+)', ifconfig_output)
                if match:
                    device_ip = match.group(1)

            # 如果还是没有 IP，对于模拟器使用 10.0.2.15，其他使用 serial
            if not device_ip:
                if device_type == DEVICE_TYPE_EMULATOR:
                    device_ip = '10.0.2.15'  # 模拟器默认 IP
                else:
                    # 对于 USB 设备，后续会通过 ADB 端口转发
                    device_ip = serial

            # 获取电池电量
            battery_output = self._run_adb_command(['-s', serial, 'shell', 'dumpsys', 'battery'])
            battery_level = 100
            match = re.search(r'level:\s*(\d+)', battery_output)
            if match:
                battery_level = int(match.group(1))

            # 获取内存信息
            meminfo_output = self._run_adb_command(['-s', serial, 'shell', 'cat', '/proc/meminfo'])
            total_memory = 8000000000  # 默认 8GB
            match = re.search(r'MemTotal:\s*(\d+)\s*kB', meminfo_output)
            if match:
                total_memory = int(match.group(1)) * 1024  # 转换为字节

            # 获取 CPU 核心数
            cpu_output = self._run_adb_command(['-s', serial, 'shell', 'cat', '/proc/cpuinfo'])
            cpu_cores = cpu_output.count('processor')
            if cpu_cores == 0:
                cpu_cores = 8  # 默认值

            # 生成 UDID（使用新的安全方法）
            udid = generate_udid(serial, model)

            device_info = {
                'udid': udid,
                'serial': serial,
                'ip': device_ip,
                'port': 7912,
                'present': True,
                'ready': True,
                'using': False,
                'is_server': False,
                'model': model,
                'brand': brand,
                'version': version,
                'sdk': int(sdk) if sdk.isdigit() else 30,
                'memory': {'total': total_memory},
                'cpu': {'hardware': device_type, 'cores': cpu_cores},
                'battery': {'level': battery_level},
                'display': {'width': width, 'height': height},
                'device_type': device_type,  # 新增：设备类型
                'owner': None,
                'createdAt': datetime.now().isoformat(),
                'updatedAt': datetime.now().isoformat()
            }

            logger.info(f"[DETECTOR] 设备信息: {serial} -> {model} ({device_type})")
            return device_info

        except Exception as e:
            logger.error(f"[DETECTOR] 获取设备信息失败 {serial}: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def init_atx_agent(self, serial: str) -> bool:
        """
        初始化设备上的atx-agent服务
        支持 USB、模拟器、WiFi 等多种连接方式
        :param serial: 设备序列号
        :return: 是否成功
        """
        try:
            import uiautomator2 as u2

            logger.info(f"Initializing atx-agent on device: {serial}")

            # 根据设备类型选择连接方式
            device_type = detect_device_type(serial)

            if device_type in (DEVICE_TYPE_WIFI, DEVICE_TYPE_EMULATOR):
                # WiFi 设备和模拟器使用网络连接
                d = u2.connect(serial)
            else:
                # USB 设备使用 USB 连接
                d = u2.connect_usb(serial)

            info = d.info
            logger.info(f"Device {serial} atx-agent ready: {info.get('productName', 'Unknown')}")

            return True

        except Exception as e:
            logger.error(f"Failed to init atx-agent on {serial}: {e}")
            return False

    async def register_device(self, device_info: Dict) -> bool:
        """
        注册设备到数据库
        :param device_info: 设备信息
        :return: 是否成功
        """
        try:
            from database.motor_helper import motor

            await motor.upsert(device_info['udid'], device_info)
            logger.info(f"Device registered: {device_info['udid']} ({device_info['model']})")
            return True

        except Exception as e:
            logger.error(f"Failed to register device: {e}")
            return False

    async def unregister_device(self, serial: str) -> bool:
        """
        标记设备离线
        :param serial: 设备序列号
        :return: 是否成功
        """
        try:
            from database.motor_helper import motor

            if serial in self._known_devices:
                device_info = self._known_devices[serial]
                udid = device_info['udid']
                await motor.update(udid, {'present': False, 'updatedAt': datetime.now().isoformat()})
                logger.info(f"Device offline: {udid}")
                del self._known_devices[serial]
                return True

        except Exception as e:
            logger.error(f"Failed to unregister device: {e}")

        return False

    async def _handle_device_connected(self, serial: str):
        """处理设备连接事件"""
        if serial in self._known_devices:
            return  # 已经注册过了

        logger.info(f"[DETECTOR] 处理设备连接: {serial}")

        # 获取设备信息
        device_info = self.get_device_info(serial)
        if not device_info:
            logger.error(f"[DETECTOR] 无法获取设备信息: {serial}")
            return

        # 初始化atx-agent
        if await self.init_atx_agent(serial):
            # 注册到数据库
            if await self.register_device(device_info):
                self._known_devices[serial] = device_info

                # 触发回调
                for handler in self._event_handlers[DeviceEvent.CONNECTED]:
                    try:
                        await handler(device_info)
                    except Exception as e:
                        logger.error(f"[DETECTOR] 连接回调错误: {e}")

    async def _handle_device_disconnected(self, serial: str):
        """处理设备断开事件"""
        logger.info(f"[DETECTOR] 处理设备断开: {serial}")

        device_info = self._known_devices.get(serial)

        # 标记设备离线
        await self.unregister_device(serial)

        # 触发回调
        if device_info:
            for handler in self._event_handlers[DeviceEvent.DISCONNECTED]:
                try:
                    await handler(device_info)
                except Exception as e:
                    logger.error(f"[DETECTOR] 断开回调错误: {e}")

    async def _event_loop(self):
        """事件处理循环"""
        logger.info("[DETECTOR] 事件处理循环已启动")

        while self._running:
            # 获取事件（非阻塞）
            event = self._monitor.get_event(timeout=0.1)

            if event:
                if event.type == DeviceEvent.CONNECTED:
                    await self._handle_device_connected(event.serial)
                elif event.type == DeviceEvent.DISCONNECTED:
                    await self._handle_device_disconnected(event.serial)

            # 短暂等待，避免CPU空转
            await asyncio.sleep(0.05)

        logger.info("[DETECTOR] 事件处理循环已停止")

    async def start(self):
        """启动自动检测"""
        if self._running:
            return

        self._running = True

        # 初始扫描
        initial_devices = self.get_connected_devices()
        logger.info(f"Initial scan: found {len(initial_devices)} device(s)")

        for serial in initial_devices:
            device_info = self.get_device_info(serial)
            if device_info:
                if await self.init_atx_agent(serial):
                    await self.register_device(device_info)
                    self._known_devices[serial] = device_info

        # 启动ADB监听线程
        self._monitor.start()

        # 启动事件处理循环
        self._task = asyncio.create_task(self._event_loop())

    async def stop(self):
        """停止自动检测"""
        self._running = False

        # 停止监听线程
        self._monitor.stop()

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


# 全局实例
device_detector = DeviceDetector(check_interval=5)
