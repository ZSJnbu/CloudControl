# encoding: utf-8
"""
--------------------------------------
@describe 
@version: 1.0
@project: CloudControl
@file: websocket_server.py
@author: yuanlang
@time: 2019-03-17 09:40
---------------------------------------
"""
import os

import aiohttp
import json
import asyncio
import base64
import time
import aiohttp_jinja2
from io import BytesIO
from cryptography import fernet
from common.logger import logger
from common.utils import get_host_ip
from config import conf
from aiohttp import web
from aiohttp_session import setup
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from service.impl.phone_service_impl import phone_service
from service.impl.device_service_impl import AndroidDevice
from service.impl.file_service_impl import file_service

route = web.RouteTableDef()
# 获取存储手机信息session
localhost = get_host_ip()
session = {}
loop = None
minitouch_list = []
minitouchs = []

# 设备连接缓存，避免每次操作都重新连接
_device_cache = {}
_device_cache_time = {}

# 设备信息缓存 (避免每次都查数据库)
_device_info_cache = {}
_device_info_cache_time = {}
DEVICE_INFO_CACHE_TTL = 300  # 5分钟缓存

# 截图缓存 (超短TTL，减少重复请求)
_screenshot_cache = {}
_screenshot_cache_time = {}
SCREENSHOT_CACHE_TTL = 0.30  # 300ms 缓存 (提高命中率)

# 截图请求去重 (避免并发请求同一设备)
_screenshot_pending = {}  # cache_key -> asyncio.Future

def get_cached_screenshot(udid):
    """获取缓存的截图"""
    now = time.time()
    if udid in _screenshot_cache:
        if now - _screenshot_cache_time.get(udid, 0) < SCREENSHOT_CACHE_TTL:
            return _screenshot_cache[udid]
    return None

def set_cached_screenshot(udid, data):
    """设置截图缓存"""
    _screenshot_cache[udid] = data
    _screenshot_cache_time[udid] = time.time()
    # 清理旧缓存 (最多保留20个)
    if len(_screenshot_cache) > 20:
        oldest = min(_screenshot_cache_time, key=_screenshot_cache_time.get)
        del _screenshot_cache[oldest]
        del _screenshot_cache_time[oldest]

def get_cached_device_info(udid):
    """获取缓存的设备信息，避免频繁数据库查询"""
    now = time.time()
    if udid in _device_info_cache:
        if now - _device_info_cache_time.get(udid, 0) < DEVICE_INFO_CACHE_TTL:
            return _device_info_cache[udid]
    return None

def set_cached_device_info(udid, info):
    """设置设备信息缓存"""
    _device_info_cache[udid] = info
    _device_info_cache_time[udid] = time.time()

def get_cached_device(ip, port, serial=None):
    """获取缓存的设备连接，60秒过期"""
    # 优先使用 serial 作为缓存键
    cache_key = serial if serial else f"{ip}:{port}"
    now = time.time()

    if cache_key in _device_cache:
        if now - _device_cache_time.get(cache_key, 0) < 60:
            return _device_cache[cache_key]

    # 创建新连接
    if serial:
        # USB 连接：使用 serial
        d = AndroidDevice(device_url=None, serial=serial)
    else:
        # WiFi 连接：使用 IP:PORT
        d = AndroidDevice(f"http://{ip}:{port}")

    _device_cache[cache_key] = d
    _device_cache_time[cache_key] = now
    return d


@route.get("/")
async def index(request):
    """
    首页
    :param request:
    :return:
    """
    logger.info(request)
    return web.FileResponse(os.path.join(os.path.dirname(__file__), "templates/index.html"))


@route.get("/devices/{udid}/remote")
@aiohttp_jinja2.template('remote.html')
async def remote(request: web.Request):
    """
    远程控制一台
    :param request:
    :return:
    """
    udid = request.match_info.get("udid", "")
    logger.debug(str(request.url) + " >>>>>> " + udid)
    if udid != "":
        device = await phone_service.query_info_by_udid(udid)
        return {"IP": device["ip"], "Port": device["port"], "Udid": udid,
                "deviceInfo": device, "device": json.dumps(device), "v": {}}
    else:
        # 参数请求错误,重定向到400
        raise web.HTTPBadRequest()


@route.post("/async")
@aiohttp_jinja2.template("device_synchronous.html")
async def async_list(request: web.Request):
    """
    云机同步
    :param request:
    :return:
    """
    form = await request.post()
    udids = form["devices"]
    udid_list = udids.split(",")
    logger.info(f"[GROUP_CONTROL] 收到设备列表: {udid_list}, 共 {len(udid_list)} 台")
    device, ip_list = None, []
    # 根据udid查询info
    for i in range(0, len(udid_list)):
        _device = await phone_service.query_info_by_udid(udid_list[i])
        if i == 0:
            device = _device
        # ip_list.append(_device)
        ip_list.append({"src": _device['ip'], "des": _device['ip'], "width": _device["display"]["width"],
                        "height": _device["display"]["height"], "port": _device['port'],"udid": _device['udid'],
                        "model": _device.get('model', '')})

    logger.info(f"[GROUP_CONTROL] 构建设备列表完成: {len(ip_list)} 台设备")
    for idx, d in enumerate(ip_list):
        logger.info(f"  [{idx}] udid={d['udid']}, ip={d['src']}")

    result = {'list': json.dumps(ip_list), 'IP': device['ip'], 'Port': device['port'],
              'Width': device["display"]["width"], 'Height': device["display"]["height"], 'Udid': device['udid'],
              'deviceInfo': {}, 'device': {}, 'v': '{{v.des}}'}
    return result


@route.get("/atxagent")
async def atxagent(request: web.Request):
    """
    控制手机 atx-agent
    :param request:
    :return:
    """
    method = request.query["method"]
    udid = request.query["udid"]
    device = await phone_service.query_info_by_udid(udid)
    # 判断手机是否安装了server服务
    if not device["is_server"]:
        # 如果没有安装则上传文件并启动
        async with aiohttp.ClientSession() as _session:
            url = f"http://127.0.0.1:{conf.server['port']}/upload"
            data = aiohttp.FormData()
            headers = {"Access-Control-Allow-Origin": udid}
            data.add_field(name='path', value="/data/local/tmp/")
            data.add_field(name='power', value="755")
            data.add_field(name='file',
                           value=open(os.path.join(os.path.dirname(__file__), "static/server"), "rb"),
                           filename='server',
                           content_type='application/octet-stream')
            data.add_field(name='file',
                           value=open(os.path.join(os.path.dirname(__file__), "static/atx.sh"), "rb"),
                           filename='atx.sh',
                           content_type='application/octet-stream')
            async with _session.post(url=url, headers=headers, data=data) as resp:
                if resp.status != 200:
                    return web.Response(text="服务安装失败", status=404)

            #更新 is_server 字段
            await phone_service.update_filed(identifier=udid, item={"is_server": True})

            # 启动服务
            url = f"http://localhost:{conf.server['port']}/shell"
            headers = {"Access-Control-Allow-Origin": udid}
            data = {
                "command": f"./data/local/tmp/server >/dev/null 2>&1 &"
            }
            async with _session.post(url, headers=headers, data=data) as resp:
                if resp.status != 200:
                    return web.Response(text="server服务启动失败", status=404)

    # atx-agent服务调度
    url = f"http://{device['ip']}:8001/api/v1.0/{method}"
    data = {
        "ip": f"{localhost}:{conf.server['port']}"
    }
    async with aiohttp.ClientSession() as _session:
        async with _session.post(url, data=data) as resp:
            if resp.status != 200:
                return web.Response(text=f"atx-agent[{method}]失败", status=404)
            else:
                return web.Response(text=f"atx-agent[{method}]成功")


@route.post("/shell")
async def shell(request: web.Request):
    """
    执行脚步,下发命令到选中手机
    :param request:
    :return:
    """
    udid = request.headers["Access-Control-Allow-Origin"]
    device = await phone_service.query_info_by_udid(udid)
    if udid != "":
        # 文件权限更改
        reader = await request.post()
        command = reader["command"]
        async with aiohttp.ClientSession() as _session:
            url = f"http://{device['ip']}:{device['port']}/shell"
            params = {
                "command": command
            }
            logger.debug(url + "  " + command)
            await _session.get(url=url, params=params)
        return web.Response(text='{} sized of {} successfully stored'
                                 ''.format(udid, 0))
    else:
        raise web.HTTPBadRequest()


@route.get("/devices/{query}/reserved")
async def reserved(request):
    """
    remote.html 中心跳检查
    :param request:
    :return:
    """
    logger.debug("ws reserved:" + str(request.url))
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async for msg in ws:
        if msg.type == web.WSMsgType.text:
            await ws.send_str("Hello, {}".format(msg.data))
        elif msg.type == web.WSMsgType.binary:
            await ws.send_bytes(msg.data)
        elif msg.type == web.WSMsgType.close:
            break

    return ws


@route.get("/devices/{udid}/info")
async def query_info(request: web.Request):
    """
    获取单台的info信息
    :param request:
    :return:
    """
    udid = request.match_info.get("udid", "")
    logger.debug(str(request.url) + " >>>>>> " + udid)
    if udid != "":
        device = await phone_service.query_info_by_udid(udid)
        return web.json_response(text=json.dumps(device))
    else:
        # 参数请求错误,重定向到400
        raise web.HTTPBadRequest()


@route.get("/list")
async def async_list(request: web.Request):
    """
    手机列表查询
    :param request:
    :return:
    """
    logger.debug(request.url)
    device = await phone_service.query_device_list()
    return web.json_response(text=json.dumps(device))


@route.get("/feeds")
async def feeds(request: web.Request):
    logger.debug("ws feeds:" + str(request.url))
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async for msg in ws:
        if msg.type == web.WSMsgType.text:
            # TODO: Queue存放变化的device
            result = {"error": False}
            await ws.send_str(json.dumps(result))
        elif msg.type == web.WSMsgType.binary:
            await ws.send_bytes(msg.data)
        elif msg.type == web.WSMsgType.close:
            break

    return ws


@route.post("/heartbeat")
async def heartbeat(request: web.Request):
    """
    心跳检测手机是否连接
    :param request: 心跳包
    :return:
    """
    global session
    global loop
    # 解析心跳包
    form = await request.post()
    logger.debug(str(request.url) + "\t>>>>>>\t identifier=" + form["identifier"])
    # 获取表单提交的identifier
    identifier = form["identifier"]
    remote_host = request.remote
    # 如果session中有identifier，判断ip是否一致
    phone_session = session[identifier] if identifier in session else None
    if phone_session is not None:
        if phone_session["remote_host"] != remote_host:
            # on_reconnected
            await phone_service.re_connected(identifier, remote_host)
        # 重置timer 倒计时
        t = time.time()
        session[identifier]["timer"] = t + 20
    # 如果没有，进入onconnected,阻塞
    else:
        # onconnected
        phone_seesion = get_phone_session(identifier, remote_host, time.time() + 20)
        session[identifier] = phone_seesion
        await phone_service.on_connected(identifier, remote_host)

        # run timer定时器
        async def consumer(_identifier, _session: dict):
            _phone_seesion = _session[_identifier]
            while True:
                await asyncio.sleep(1)
                _t = time.time()
                # logger.debug(str(_phone_seesion["timer"]) + ">>>>" + str(t))
                if _phone_seesion["timer"] < _t:
                    # offline_onconected()
                    _session.pop(_identifier)
                    return await phone_service.offline_connected(_identifier)

        asyncio.run_coroutine_threadsafe(consumer(identifier, session), loop)
        # loop.call_soon_threadsafe(consumer,identifier, session)
    return web.Response(text="hello kitty")


@route.post("/upload")
async def store_file_handler(request: web.Request):
    """
    文件上传
    :param request:
    :return:
    """
    reader = await request.multipart()
    udid: str = request.headers["Access-Control-Allow-Origin"]

    data = await reader.next()
    assert data.name == "path"
    path: str = await data.text()
    if path == "":
        path = "/data/local/tmp/"

    data = await reader.next()
    assert data.name == "power"
    power: str = await data.text()

    if udid != "":
        device = await phone_service.query_info_by_udid(udid)
        names = []
        # 转到其他手机端
        async with aiohttp.ClientSession() as _session:
            while True:
                try:
                    field = await reader.next()
                    assert field.name == "file"
                except Exception as e:
                    break
                name: str = field.filename
                names.append(name)

                data = aiohttp.FormData()
                data.add_field('file', field, filename=name, content_type='application/octet-stream')
                url = f"http://{device['ip']}:{device['port']}/upload{path.replace('_', '/')}"

                await _session.post(url=url, data=data)
                # 文件权限更改
                url = f"http://localhost:{conf.server['port']}/shell"
                headers = {
                    "Access-Control-Allow-Origin": udid
                }
                data = {
                    "command": f"chmod {power} {path}{name}"
                }
                await _session.post(url=url, data=data, headers=headers)

                # apk安装
                if name.endswith(".apk"):
                    data = {
                        "command": f"pm install {path}{name}"
                    }
                    await _session.post(url=url, data=data, headers=headers)

        return web.Response(text='upload {} successfully stored'
                                 ''.format(",".join(names), 0))
    else:
        raise web.HTTPBadRequest()


# 模拟截图数据（用于压力测试）
_MOCK_SCREENSHOT_DATA = None

def _get_mock_screenshot():
    """获取模拟截图数据（懒加载）"""
    global _MOCK_SCREENSHOT_DATA
    if _MOCK_SCREENSHOT_DATA is None:
        # 创建一个简单的测试图片
        try:
            from PIL import Image
            img = Image.new('RGB', (1080, 2400), color=(50, 50, 50))
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=50)
            _MOCK_SCREENSHOT_DATA = base64.b64encode(buffer.getvalue()).decode('utf-8')
        except:
            # 如果PIL不可用，使用空数据
            _MOCK_SCREENSHOT_DATA = ""
    return _MOCK_SCREENSHOT_DATA


@route.get("/inspector/{udid}/screenshot")
async def inspector_screenshot(request: web.Request):
    """
    文档树结构screenshot快照（使用缓存连接）
    支持模拟设备用于压力测试
    :param request:
    :return:
    """
    udid = request.match_info.get("udid", "")
    logger.debug(str(request.url) + " >>>>>> " + udid)
    if udid != "":
        device = await phone_service.query_info_by_udid(udid)

        # 检查设备是否存在
        if device is None:
            return web.json_response({"status": "error", "message": "Device not found"}, status=404)

        # 检查是否是模拟设备（用于压力测试）
        if device.get('is_mock', False):
            response = {
                "type": "jpeg",
                "encoding": "base64",
                "data": _get_mock_screenshot(),
            }
            return web.json_response(text=json.dumps(response))

        # 真实设备：使用缓存的设备连接
        serial = device.get('serial')
        d = get_cached_device(device['ip'], device['port'], serial=serial)

        # 获取质量参数 (默认70，平衡质量和速度)
        quality = int(request.query.get('quality', 70))
        quality = max(30, min(95, quality))

        # 获取缩放参数 (可选，减少数据量)
        scale = float(request.query.get('scale', 1.0))
        scale = max(0.25, min(1.0, scale))

        buffer = BytesIO()
        img = d.screenshot()

        # 可选缩放
        if scale < 1.0:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, resample=1)  # 1 = BILINEAR, 快速

        # 保存为JPEG，优化压缩
        img.convert("RGB").save(buffer, format='JPEG', quality=quality, optimize=True)
        b64data = base64.b64encode(buffer.getvalue())
        response = {
            "type": "jpeg",
            "encoding": "base64",
            "data": b64data.decode('utf-8'),
        }
        return web.json_response(text=json.dumps(response))
    else:
        # 参数请求错误,重定向到400
        raise web.HTTPBadRequest()


@route.post("/inspector/{udid}/touch")
async def inspector_touch(request: web.Request):
    """
    触摸操作 - 优化版 (火速响应)
    使用缓存避免数据库查询，使用fire-and-forget模式
    """
    udid = request.match_info.get("udid", "")
    if udid != "":
        try:
            data = await request.json()
            action = data.get("action", "click")
            x = data.get("x")
            y = data.get("y")

            # 验证坐标
            if x is None or y is None:
                return web.json_response({"status": "error", "message": "Missing coordinates"}, status=400)

            # 尝试从缓存获取设备信息
            device = get_cached_device_info(udid)
            if device is None:
                device = await phone_service.query_info_by_udid(udid)
                if device:
                    set_cached_device_info(udid, device)

            # 检查设备是否存在
            if device is None:
                return web.json_response({"status": "error", "message": "Device not found"}, status=404)

            # 检查是否是模拟设备
            if device.get('is_mock', False):
                return web.json_response({"status": "ok"})

            # 获取缓存的设备连接
            serial = device.get('serial')
            d = get_cached_device(device['ip'], device['port'], serial=serial)

            # Fire-and-forget: 在后台执行，立即返回响应
            import asyncio
            loop = asyncio.get_event_loop()

            def execute_touch():
                try:
                    if action == "click":
                        d.device.click(int(x), int(y))
                    elif action == "swipe":
                        x2 = data.get("x2", x)
                        y2 = data.get("y2", y)
                        duration = data.get("duration", 200) / 1000.0
                        duration = max(0.05, min(2.0, duration))
                        d.device.swipe(int(x), int(y), int(x2), int(y2), duration=duration)
                except Exception as e:
                    logger.error(f"[TOUCH] 执行失败 {udid}: {e}")

            # 不等待完成，立即返回
            loop.run_in_executor(None, execute_touch)

            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"触摸操作失败: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)
    else:
        raise web.HTTPBadRequest()


@route.post("/inspector/{udid}/input")
async def inspector_input(request: web.Request):
    """
    键盘输入文字 - 优化版 (支持中文, fire-and-forget)
    """
    udid = request.match_info.get("udid", "")
    if udid != "":
        try:
            data = await request.json()
            text = data.get("text", "")

            if not text:
                return web.json_response({"status": "ok"})

            # 尝试从缓存获取设备信息
            device = get_cached_device_info(udid)
            if device is None:
                device = await phone_service.query_info_by_udid(udid)
                if device:
                    set_cached_device_info(udid, device)

            if device is None:
                return web.json_response({"status": "error", "message": "Device not found"}, status=404)

            serial = device.get('serial')
            d = get_cached_device(device['ip'], device['port'], serial=serial)

            # Fire-and-forget
            import asyncio
            loop = asyncio.get_event_loop()

            def execute_input():
                try:
                    d.device.set_fastinput_ime(True)
                    d.device.send_keys(text, clear=False)
                except Exception as e:
                    logger.error(f"[INPUT] 执行失败 {udid}: {e}")

            loop.run_in_executor(None, execute_input)

            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"输入失败: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)
    else:
        raise web.HTTPBadRequest()


@route.post("/inspector/{udid}/keyevent")
async def inspector_keyevent(request: web.Request):
    """
    发送按键事件 - 优化版 (fire-and-forget)
    """
    udid = request.match_info.get("udid", "")
    if udid != "":
        try:
            data = await request.json()
            key = data.get("key", "")

            # 尝试从缓存获取设备信息
            device = get_cached_device_info(udid)
            if device is None:
                device = await phone_service.query_info_by_udid(udid)
                if device:
                    set_cached_device_info(udid, device)

            if device is None:
                return web.json_response({"status": "error", "message": "Device not found"}, status=404)

            serial = device.get('serial')
            d = get_cached_device(device['ip'], device['port'], serial=serial)

            # Android keycode 映射 (支持大小写)
            key_map = {
                "Enter": "enter",
                "Backspace": "del",
                "Delete": "forward_del",
                "DEL": "del",
                "Home": "home",
                "HOME": "home",
                "home": "home",
                "Back": "back",
                "BACK": "back",
                "back": "back",
                "Tab": "tab",
                "Escape": "back",
                "ArrowUp": "dpad_up",
                "ArrowDown": "dpad_down",
                "ArrowLeft": "dpad_left",
                "ArrowRight": "dpad_right",
                "Menu": "menu",
                "MENU": "menu",
                "menu": "menu",
                "Power": "power",
                "POWER": "power",
                "power": "power",
                "WAKEUP": "wakeup",
                "wakeup": "wakeup",
            }

            android_key = key_map.get(key, key.lower())

            # Fire-and-forget
            import asyncio
            loop = asyncio.get_event_loop()

            def execute_keyevent():
                try:
                    d.device.press(android_key)
                except Exception as e:
                    logger.error(f"[KEYEVENT] 执行失败 {udid}: {e}")

            loop.run_in_executor(None, execute_keyevent)

            return web.json_response({"status": "ok"})
        except Exception as e:
            logger.error(f"按键失败: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)
    else:
        raise web.HTTPBadRequest()


@route.post("/inspector/{udid}/upload")
async def inspector_upload(request: web.Request):
    """
    上传文件到手机
    """
    udid = request.match_info.get("udid", "")
    if udid != "":
        try:
            reader = await request.multipart()
            field = await reader.next()

            if field is None:
                return web.json_response({"status": "error", "message": "No file uploaded"}, status=400)

            filename = field.filename
            # 保存到临时文件
            import tempfile
            import os as os_module

            temp_dir = tempfile.gettempdir()
            temp_path = os_module.path.join(temp_dir, filename)

            # 读取并保存文件
            with open(temp_path, 'wb') as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    f.write(chunk)

            device = await phone_service.query_info_by_udid(udid)
            serial = device.get('serial') if device else None
            d = get_cached_device(device['ip'], device['port'], serial=serial)

            # 根据文件类型决定目标路径
            ext = os_module.path.splitext(filename)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                # 图片放到 DCIM 目录
                device_path = f"/sdcard/DCIM/{filename}"
            elif ext in ['.mp4', '.avi', '.mov', '.mkv']:
                # 视频放到 Movies 目录
                device_path = f"/sdcard/Movies/{filename}"
            elif ext in ['.apk']:
                # APK 放到 Download 目录
                device_path = f"/sdcard/Download/{filename}"
            else:
                # 其他文件放到 Download 目录
                device_path = f"/sdcard/Download/{filename}"

            # 推送文件到手机
            d.device.push(temp_path, device_path)

            # 删除临时文件
            os_module.remove(temp_path)

            # 如果是图片，通知媒体库扫描
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                d.device.shell(f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{device_path}')

            return web.json_response({
                "status": "ok",
                "message": f"文件已上传到: {device_path}",
                "path": device_path
            })
        except Exception as e:
            logger.error(f"上传失败: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)
    else:
        raise web.HTTPBadRequest()


@route.get("/inspector/{udid}/screenshot/img")
async def inspector_screenshot_img(request: web.Request):
    """
    直接返回截图图片 - 高性能优化版
    - 截图缓存 (150ms TTL)
    - 设备信息缓存
    - 线程池执行
    - 默认低质量高压缩
    """
    udid = request.match_info.get("udid", "")
    if udid != "":
        try:
            # 获取优化参数 (默认更低质量以提高速度)
            quality = int(request.query.get('q', 40))  # 降低到40
            quality = max(20, min(90, quality))
            scale = float(request.query.get('s', 0.4))  # 默认缩放40%
            scale = max(0.2, min(1.0, scale))

            import asyncio

            # 构建缓存键
            cache_key = f"{udid}_{quality}_{scale}"

            # 检查截图缓存
            cached = get_cached_screenshot(cache_key)
            if cached:
                headers = {
                    'Cache-Control': 'no-cache',
                    'X-Cache': 'HIT'
                }
                return web.Response(body=cached, content_type='image/jpeg', headers=headers)

            # 请求去重: 如果已有请求在进行中，等待其结果
            if cache_key in _screenshot_pending:
                try:
                    img_data = await _screenshot_pending[cache_key]
                    headers = {
                        'Cache-Control': 'no-cache',
                        'X-Cache': 'DEDUP'
                    }
                    return web.Response(body=img_data, content_type='image/jpeg', headers=headers)
                except Exception:
                    pass  # 原请求失败，继续尝试新请求

            # 创建 Future 用于去重
            loop = asyncio.get_event_loop()
            future = loop.create_future()
            _screenshot_pending[cache_key] = future

            try:
                # 获取设备信息 (使用缓存)
                device = get_cached_device_info(udid)
                if device is None:
                    device = await phone_service.query_info_by_udid(udid)
                    if device:
                        set_cached_device_info(udid, device)

                if device is None:
                    raise web.HTTPNotFound()

                serial = device.get('serial')
                d = get_cached_device(device['ip'], device['port'], serial=serial)

                def capture_screenshot():
                    buffer = BytesIO()
                    img = d.screenshot()

                    # 缩放以减少数据量 (使用最快的NEAREST算法)
                    if scale < 1.0:
                        new_size = (int(img.width * scale), int(img.height * scale))
                        img = img.resize(new_size, resample=0)  # NEAREST (最快)

                    # 使用更激进的压缩
                    img.convert("RGB").save(buffer, format='JPEG', quality=quality, optimize=False)
                    return buffer.getvalue()

                img_data = await loop.run_in_executor(None, capture_screenshot)

                # 缓存截图
                set_cached_screenshot(cache_key, img_data)

                # 通知等待的请求
                if not future.done():
                    future.set_result(img_data)

                headers = {
                    'Cache-Control': 'no-cache',
                    'X-Cache': 'MISS'
                }
                return web.Response(body=img_data, content_type='image/jpeg', headers=headers)
            except Exception as e:
                if not future.done():
                    future.set_exception(e)
                raise
            finally:
                # 清理 pending 状态
                _screenshot_pending.pop(cache_key, None)
        except Exception as e:
            logger.error(f"截图失败: {e}")
            raise web.HTTPNotFound()
    else:
        raise web.HTTPBadRequest()


@route.get("/inspector/{udid}/hierarchy")
async def inspector_hierarchy(request: web.Request):
    """
    文档树结构
    :param request:
    :return:
    """
    udid = request.match_info.get("udid", "")
    logger.debug(str(request.url) + " >>>>>> " + udid)
    if udid != "":
        device = await phone_service.query_info_by_udid(udid)
        # 连接用uiautomator2连接atx-agent
        d = AndroidDevice(f"http://{device['ip']}:{device['port']}")
        hierarchy = d.dump_hierarchy()
        logger.debug(hierarchy)
        return web.json_response(text=json.dumps(hierarchy))
    else:
        # 参数请求错误,重定向到400
        raise web.HTTPBadRequest()


@route.get("/installfile")
@aiohttp_jinja2.template("file.html")
async def installfile(request: web.Request):
    """
    apk安装
    :param request:
    :return:
    """
    logger.debug(request.url)
    return {}


# /files?sort=&page=1&per_page=10
@route.get("/files")
async def files(request: web.Request):
    """
    apk安装
    :param request:
    :return:
    """
    logger.debug(request.url)

    sort = request.query.get("sort", "")
    page = int(request.query["page"])
    # per_page = int(request.query["per_page"])
    start = (page - 1) * 5
    end = start + 5
    _list = await file_service.query_install_file(0, start, 5, sort)
    total = await file_service.query_all_install_file()
    last_page = int(total / 5) + 1
    # logger.debug(str(page) + " ------- " + str(per_page) + ">>>>>> " + str(list))
    if page < last_page:
        next_page_url = "http://172.17.2.233:8000/files?page=" + str((page + 1))
        prev_page_url = "http://172.17.2.233:8000/files?page=" + str(page)
        if page > 1:
            prev_page_url = "http://172.17.2.233:8000/files?page=" + str((page - 1))
    else:
        next_page_url = "http://172.17.2.233:8000/files?page=" + str(page)
        prev_page_url = "http://172.17.2.233:8000/files?page=" + str((page - 1))

    result = {"total": total, "per_page": 5, "current_page": page, "last_page": last_page,
              "next_page_url": next_page_url, "prev_page_url": prev_page_url, "from": start, "to": end, "data": _list}
    # logger.debug(result)
    return web.json_response(text=json.dumps(result))


# /files?sort=&page=1&per_page=10
@route.get("/file/delete/{group}/{filename}")
async def files(request: web.Request):
    """
    apk安装
    :param request:
    :return:
    """
    logger.debug(request.url)
    group = int(request.match_info.get("group", ""))
    filename = request.match_info.get("filename", "")

    if id != "":
        await file_service.delect_install_file_by_id(group, filename)
        raise web.HTTPFound('/installfile')
    else:
        raise web.HTTPBadRequest()


@route.post("/upload_group/{path}")
async def upload_group(request: web.Request):
    """
    文件上传,批量上传到所在gourd组的手机
    :param request:
    :return:
    """
    path: str = request.match_info.get("path", "")
    logger.debug(path)
    reader = await request.multipart()
    field = await reader.next()
    name = field.filename
    # 上传文件到所在group组的手机
    # group = request.headers["Access-Control-Allow-Origin"]
    # /!\ Don't forget to validate your inputs /!\
    # reader.next() will `yield` the fields of your form

    _list = await phone_service.query_device_list_by_present()
    exception_ip = []
    async with aiohttp.ClientSession() as _session:
        for device in _list:
            # 转到其他手机端
            data = aiohttp.FormData()
            data.add_field('file',
                           field,
                           filename=name,
                           content_type='application/octet-stream')
            url = f"http://{device['ip']}:{device['port']}/upload/{path.replace('_', '/')}/"
            logger.debug("upload url>>>>>> " + url)
            try:
                # proxy="http://localhost:8888"
                async with _session.post(url=url, data=data, timeout=5) as resp:
                    content = await resp.read()
                    text = content.decode(encoding="utf-8")
                    logger.debug(text)
                # apk安装
                if name.endswith(".apk"):
                    url = f"http://localhost:{conf.server['port']}/shell"
                    headers = {
                        "Access-Control-Allow-Origin": device['udid']
                    }
                    data = {
                        "command": f"pm install /{path.replace('_', '/')}/{name}"
                    }
                    async with _session.post(url=url, data=data, headers=headers) as resp:
                        logger.debug(await resp.read())
            except Exception as e:
                logger.warn("Exception:" + str(e) + "   >>>>>> ip:" + device['ip'])
                exception_ip.append("Exception:" + str(e) + "   >>>>>> ip:" + device['ip'])

    current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
    file = {"group": 0, "filename": name, "filesize": 0, "upload_time": current_time, "who": "admin"}
    await file_service.save_install_file(file)
    result = {}
    if len(exception_ip) != 0:
        result["exception"] = "true"
        result["exception_data"] = exception_ip
    return web.json_response(text=json.dumps(result))


def get_phone_session(identifier, remote_host, timer):
    """
    heartbeat 方法中用到的用于生成session的
    :param identifier:
    :param remote_host:
    :param timer:
    :return:
    """
    phone_seesion = {"identifier": identifier, "remote_host": remote_host, "timer": timer, "timeout": "",
                     "heartbeat": ""}
    return phone_seesion


@route.post("/api/wifi-connect")
async def wifi_connect(request: web.Request):
    """
    通过 WiFi 连接设备
    1. 使用 adb connect 连接设备
    2. 初始化 atx-agent
    3. 添加到数据库
    """
    import subprocess
    import uiautomator2 as u2
    from datetime import datetime

    try:
        data = await request.json()
        address = data.get("address", "").strip()

        if not address:
            return web.json_response({"status": "error", "message": "Missing address"}, status=400)

        # 验证格式
        if ":" not in address:
            return web.json_response({"status": "error", "message": "Invalid format. Use IP:PORT"}, status=400)

        ip, port = address.rsplit(":", 1)
        logger.info(f"[WiFi Connect] Connecting to {address}...")

        # Step 1: 使用 adb connect
        try:
            result = subprocess.run(
                ["adb", "connect", address],
                capture_output=True,
                text=True,
                timeout=10
            )
            output = result.stdout + result.stderr
            logger.info(f"[WiFi Connect] adb connect output: {output}")

            if "connected" not in output.lower() and "already" not in output.lower():
                return web.json_response({
                    "status": "error",
                    "message": f"ADB connect failed: {output.strip()}"
                }, status=500)
        except subprocess.TimeoutExpired:
            return web.json_response({
                "status": "error",
                "message": "ADB connect timeout"
            }, status=500)
        except FileNotFoundError:
            return web.json_response({
                "status": "error",
                "message": "ADB not found. Please install Android SDK."
            }, status=500)

        # Step 2: 等待设备就绪
        import asyncio
        await asyncio.sleep(2)

        # Step 3: 使用 uiautomator2 连接并初始化 atx-agent
        try:
            logger.info(f"[WiFi Connect] Initializing uiautomator2 for {address}...")
            d = u2.connect(address)
            info = d.device_info
            logger.info(f"[WiFi Connect] Device info: {info}")

            # 获取设备信息
            model = info.get("productName", "Unknown")
            brand = info.get("brand", "Unknown")
            version = str(info.get("version", "Unknown"))
            serial = info.get("serial", address.replace(":", "-"))

            # 获取屏幕尺寸
            width, height = d.window_size()

        except Exception as e:
            logger.error(f"[WiFi Connect] uiautomator2 error: {e}")
            return web.json_response({
                "status": "error",
                "message": f"Failed to initialize device: {str(e)}"
            }, status=500)

        # Step 4: 保存到数据库
        try:
            udid = f"{address.replace(':', '-')}-{model.replace(' ', '_')}"
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            device_data = {
                "udid": udid,
                "serial": address,
                "ip": ip,
                "port": 7912,
                "present": True,
                "ready": True,
                "using": False,
                "is_server": False,
                "model": model,
                "brand": brand,
                "version": version,
                "sdk": info.get("sdk", 30),
                "display": {"width": width, "height": height},
                "update_time": now
            }

            # 使用 update_filed 保存/更新设备
            await phone_service.update_filed(udid, device_data)
            logger.info(f"[WiFi Connect] Device saved: {udid}")

            return web.json_response({
                "status": "ok",
                "message": "Device connected successfully",
                "udid": udid,
                "model": f"{brand} {model}",
                "ip": ip
            })

        except Exception as e:
            logger.error(f"[WiFi Connect] Database error: {e}")
            return web.json_response({
                "status": "error",
                "message": f"Failed to save device: {str(e)}"
            }, status=500)

    except Exception as e:
        logger.error(f"[WiFi Connect] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({
            "status": "error",
            "message": str(e)
        }, status=500)


def setup_routes(_loop, app: web.Application):
    global loop
    loop = _loop
    # 应用静态资源
    app.router.add_routes(route)
    # setup_session
    # secret_key must be 32 url-safe base64-encoded bytes
    fernet_key = fernet.Fernet.generate_key()
    secret_key = base64.urlsafe_b64decode(fernet_key)
    setup(app, EncryptedCookieStorage(secret_key))
