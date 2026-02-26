# encoding: utf-8
"""
设备检测模块测试
测试 DeviceDetector 的各项功能
"""
import pytest
import asyncio
import subprocess
from unittest.mock import Mock, patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from service.device_detector import (
    DeviceDetector,
    detect_device_type,
    generate_udid,
    DEVICE_TYPE_USB,
    DEVICE_TYPE_EMULATOR,
    DEVICE_TYPE_WIFI
)


class TestDeviceTypeDetection:
    """测试设备类型检测"""

    def test_detect_emulator_by_prefix(self):
        """测试模拟器检测 - emulator- 前缀"""
        assert detect_device_type('emulator-5554') == DEVICE_TYPE_EMULATOR
        assert detect_device_type('emulator-5556') == DEVICE_TYPE_EMULATOR

    def test_detect_emulator_by_localhost(self):
        """测试模拟器检测 - 127.0.0.1 前缀"""
        assert detect_device_type('127.0.0.1:5555') == DEVICE_TYPE_EMULATOR
        assert detect_device_type('127.0.0.1:62001') == DEVICE_TYPE_EMULATOR

    def test_detect_wifi_device(self):
        """测试 WiFi 设备检测"""
        assert detect_device_type('192.168.1.100:5555') == DEVICE_TYPE_WIFI
        assert detect_device_type('10.0.0.50:5555') == DEVICE_TYPE_WIFI
        assert detect_device_type('172.16.0.1:5555') == DEVICE_TYPE_WIFI

    def test_detect_usb_device(self):
        """测试 USB 设备检测"""
        assert detect_device_type('RF8M33XXXXX') == DEVICE_TYPE_USB
        assert detect_device_type('0123456789ABCDEF') == DEVICE_TYPE_USB
        assert detect_device_type('HVY0123456') == DEVICE_TYPE_USB

    def test_detect_empty_serial(self):
        """测试空序列号"""
        assert detect_device_type('') == DEVICE_TYPE_USB
        assert detect_device_type(None) == DEVICE_TYPE_USB


class TestUdidGeneration:
    """测试 UDID 生成"""

    def test_generate_udid_basic(self):
        """测试基本 UDID 生成"""
        udid = generate_udid('emulator-5554', 'sdk_gphone64_arm64')
        assert udid == 'emulator-5554-sdk_gphone64_arm64'

    def test_generate_udid_with_special_chars(self):
        """测试包含特殊字符的 UDID 生成"""
        # IP:Port 格式
        udid = generate_udid('192.168.1.100:5555', 'Pixel 6')
        assert ':' not in udid or udid.count('-') >= 1
        assert ' ' not in udid

    def test_generate_udid_empty_values(self):
        """测试空值的 UDID 生成"""
        udid = generate_udid('', '')
        assert 'unknown' in udid

    def test_generate_udid_none_values(self):
        """测试 None 值的 UDID 生成"""
        udid = generate_udid(None, None)
        assert 'unknown' in udid


class TestDeviceDetector:
    """测试 DeviceDetector 类"""

    @pytest.fixture
    def detector(self):
        """创建检测器实例"""
        return DeviceDetector()

    def test_detector_initialization(self, detector):
        """测试检测器初始化"""
        assert detector._running is False
        assert detector._devices == {}
        assert detector._poll_interval == 1.0

    @patch('subprocess.run')
    def test_get_adb_devices_success(self, mock_run, detector):
        """测试成功获取 ADB 设备"""
        mock_run.return_value = Mock(
            stdout="List of devices attached\nemulator-5554\tdevice\nemulator-5556\tdevice\n"
        )
        devices = detector.get_adb_devices()
        assert devices == {'emulator-5554', 'emulator-5556'}

    @patch('subprocess.run')
    def test_get_adb_devices_empty(self, mock_run, detector):
        """测试空设备列表"""
        mock_run.return_value = Mock(stdout="List of devices attached\n")
        devices = detector.get_adb_devices()
        assert devices == set()

    @patch('subprocess.run')
    def test_get_adb_devices_offline(self, mock_run, detector):
        """测试包含离线设备"""
        mock_run.return_value = Mock(
            stdout="List of devices attached\nemulator-5554\tdevice\nemulator-5556\toffline\n"
        )
        devices = detector.get_adb_devices()
        assert devices == {'emulator-5554'}  # 只返回在线设备

    @patch('subprocess.run')
    def test_get_adb_devices_timeout(self, mock_run, detector):
        """测试 ADB 命令超时"""
        mock_run.side_effect = subprocess.TimeoutExpired('adb', 5)
        devices = detector.get_adb_devices()
        assert devices == set()

    @patch('subprocess.run')
    def test_get_device_info(self, mock_run, detector):
        """测试获取设备信息"""
        # 模拟 adb shell 命令返回
        def mock_shell(args, **kwargs):
            cmd = args[-1] if args else ''
            returns = {
                'getprop ro.product.model': Mock(stdout='Pixel 6'),
                'getprop ro.product.brand': Mock(stdout='google'),
                'getprop ro.build.version.release': Mock(stdout='14'),
                'getprop ro.build.version.sdk': Mock(stdout='34'),
                'wm size': Mock(stdout='Physical size: 1080x2400'),
            }
            for key, val in returns.items():
                if key in cmd:
                    return val
            return Mock(stdout='')

        mock_run.side_effect = mock_shell

        info = detector.get_device_info('emulator-5554')
        assert info is not None
        assert info['model'] == 'Pixel 6'
        assert info['brand'] == 'google'
        assert info['version'] == '14'
        assert info['sdk'] == 34

    def test_get_devices_empty(self, detector):
        """测试获取设备列表 - 空"""
        devices = detector.get_devices()
        assert devices == []

    @pytest.mark.asyncio
    async def test_start_stop(self, detector):
        """测试启动和停止"""
        # 模拟 get_adb_devices 返回空
        with patch.object(detector, 'get_adb_devices', return_value=set()):
            await detector.start()
            assert detector._running is True

            await detector.stop()
            assert detector._running is False


class TestDeviceDetectorIntegration:
    """设备检测集成测试 (需要实际设备)"""

    @pytest.fixture
    def real_detector(self):
        """创建真实检测器"""
        return DeviceDetector()

    @pytest.mark.skipif(
        not os.path.exists('/usr/local/bin/adb') and not os.path.exists('/usr/bin/adb'),
        reason="ADB not installed"
    )
    def test_real_adb_devices(self, real_detector):
        """测试真实 ADB 设备检测"""
        devices = real_detector.get_adb_devices()
        # 只验证返回类型正确
        assert isinstance(devices, set)
        print(f"检测到 {len(devices)} 台设备: {devices}")

    @pytest.mark.skipif(
        not os.path.exists('/usr/local/bin/adb') and not os.path.exists('/usr/bin/adb'),
        reason="ADB not installed"
    )
    @pytest.mark.asyncio
    async def test_real_device_sync(self, real_detector):
        """测试真实设备同步"""
        await real_detector.sync_devices()
        devices = real_detector.get_devices()
        print(f"同步后设备数: {len(devices)}")
        for d in devices:
            print(f"  - {d.get('udid')}: {d.get('model')}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
