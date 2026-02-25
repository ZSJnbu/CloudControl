# encoding: utf-8
"""
--------------------------------------
@describe 各种系统自动化接口 目前只有android
@version: 1.0
@project: CloudControl
@file: device_service_impl.py
@author: yuanlang
@time: 2019-04-01 18:07
---------------------------------------
"""
from common import uidumplib
from common.logger import logger
from service.device_service import DeviceService


class AndroidDevice(DeviceService):
    """
    Android device - 支持 USB 和 WiFi 连接
    """

    def __init__(self, device_url, serial=None):
        import uiautomator2 as u2

        # 优先使用 serial 通过 USB 连接
        if serial:
            logger.debug(f"[AndroidDevice] USB连接: {serial}")
            self._d = u2.connect_usb(serial)
        else:
            # 解析地址
            addr = device_url.replace("http://", "")

            # 判断是 USB serial 还是 WiFi IP:PORT
            if self._is_usb_serial(addr):
                logger.debug(f"[AndroidDevice] USB连接: {addr}")
                self._d = u2.connect_usb(addr.split(":")[0])
            else:
                # WiFi ADB 连接 (ip:port 格式)
                logger.debug(f"[AndroidDevice] WiFi连接: {addr}")
                self._d = u2.connect(addr)

    def _is_usb_serial(self, addr):
        """判断是否为 USB serial（而非 IP:PORT）"""
        # USB serial 通常是字母数字组合，不是IP格式
        parts = addr.split(":")
        ip_part = parts[0]
        # IP 地址检查
        if ip_part.count(".") == 3:
            try:
                for octet in ip_part.split("."):
                    if not (0 <= int(octet) <= 255):
                        return True
                return False  # 是有效IP
            except ValueError:
                return True  # 不是IP，是serial
        return True  # 没有3个点，是serial

    def screenshot(self):
        """
        android 截图
        :return: PIL Image
        """
        return self._d.screenshot()

    def dump_hierarchy(self):
        """
        dump Android 界面文档树
        :return:
        """
        return uidumplib.get_android_hierarchy(self._d)

    @property
    def device(self):
        return self._d
