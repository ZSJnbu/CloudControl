# encoding: utf-8
"""
--------------------------------------
@describe asyncio http server 配置
@version: 1.0
@project: CloudControl
@file: main.py.py
@author: yuanlang
@time: 2019-03-15 14:00
---------------------------------------
"""
import asyncio
import jinja2
import aiohttp_jinja2
from aiohttp import web
from resources.routes_control import setup_routes
from resources.nio_channel import setup_nio_routes
from resources.aio_pool import init_aio_service, shutdown_aio_service
from middlewares import setup_middlewares
from service.impl.phone_service_impl import phone_service
from service.device_detector import device_detector
from config import conf
from common.logger import logger


def setup_templates(app):
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader('./resources/templates'))


def setup_static_routes(app):
    app.router.add_static('/static/',
                          path='./resources/static',
                          name='static')


def init_db(_loop):
    """
    删除表atxserver.devices
    :return:
    """
    task = _loop.create_task(phone_service.delect_devices())
    asyncio.gather(task)


async def init(_loop):
    """
    初始化
    :param _loop:
    :return:
    """
    app = web.Application()
    # 初始化数据库
    init_db(_loop)
    # 配置路由
    setup_routes(_loop, app)
    # 配置 NIO WebSocket 路由
    setup_nio_routes(app)
    # 配置页面跳转中间件
    setup_middlewares(app)
    # 配置静态资源
    setup_static_routes(app)
    # 配置静态资源模板
    setup_templates(app)
    # 启动 AIO 高性能服务
    await init_aio_service()
    logger.info('AIO 高性能服务已启动')

    # 启动自动设备检测
    await device_detector.start()
    logger.info('USB 设备自动检测已启动')

    # 启动服务
    # noinspection PyDeprecation
    srv = await _loop.create_server(app.make_handler(), '0.0.0.0', conf.server["port"])
    logger.info('http://0.0.0.0:'+str(conf.server["port"]))
    return srv


loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(init(loop))
loop.run_forever()


# app['config'] = config
# web.run_app(app, host="0.0.0.0", port=8000)
