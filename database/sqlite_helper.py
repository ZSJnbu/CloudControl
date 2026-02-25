# encoding: utf-8
"""
--------------------------------------
@describe SQLite数据库操作 (替代MongoDB)
@version: 2.0
@project: CloudControl
@file: sqlite_helper.py
@time: 2024
---------------------------------------
"""
import os
import json
import aiosqlite
from datetime import datetime
from common.logger import logger
from config import conf


class SQLiteHelper:
    """
    SQLite数据库助手类，提供与MotorHelper相同的接口
    """

    def __init__(self):
        """
        初始化SQLite数据库连接
        """
        # 数据库文件路径
        db_dir = os.path.dirname(os.path.abspath(__file__))
        self.db_path = os.path.join(db_dir, 'cloudcontrol.db')
        self._initialized = False
        logger.debug(f"SQLite database path: {self.db_path}")

    async def _ensure_initialized(self):
        """
        确保数据库表已创建
        """
        if self._initialized:
            return

        async with aiosqlite.connect(self.db_path) as db:
            # 创建 devices 表
            await db.execute('''
                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    udid TEXT UNIQUE NOT NULL,
                    serial TEXT,
                    ip TEXT,
                    port INTEGER,
                    present INTEGER DEFAULT 0,
                    ready INTEGER DEFAULT 0,
                    using_device INTEGER DEFAULT 0,
                    is_server INTEGER DEFAULT 0,
                    is_mock INTEGER DEFAULT 0,
                    update_time TEXT,
                    model TEXT,
                    brand TEXT,
                    version TEXT,
                    sdk INTEGER,
                    memory TEXT,
                    cpu TEXT,
                    battery TEXT,
                    display TEXT,
                    owner TEXT,
                    provider TEXT,
                    agent_version TEXT,
                    hwaddr TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    extra_data TEXT
                )
            ''')

            # 创建 installed_file 表
            await db.execute('''
                CREATE TABLE IF NOT EXISTS installed_file (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    filesize INTEGER,
                    upload_time TEXT,
                    who TEXT,
                    extra_data TEXT,
                    UNIQUE(group_name, filename)
                )
            ''')

            # 创建索引
            await db.execute('CREATE INDEX IF NOT EXISTS idx_devices_udid ON devices(udid)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_devices_present ON devices(present)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_files_group ON installed_file(group_name)')

            await db.commit()

        self._initialized = True
        logger.debug("SQLite database initialized successfully")

    def _device_to_dict(self, row, columns):
        """
        将数据库行转换为字典，模拟MongoDB文档格式
        """
        if row is None:
            return None

        result = {}
        for i, col in enumerate(columns):
            value = row[i]
            # 处理JSON字段
            if col in ('memory', 'cpu', 'battery', 'display', 'extra_data') and value:
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    pass
            # 处理布尔字段
            elif col in ('present', 'ready', 'using_device', 'is_server', 'is_mock'):
                value = bool(value)
            # 字段名映射
            if col == 'group_name':
                col = 'group'
            elif col == 'using_device':
                col = 'using'
            elif col == 'agent_version':
                col = 'agentVersion'
            elif col == 'created_at':
                col = 'createdAt'
            elif col == 'updated_at':
                col = 'updatedAt'

            result[col] = value

        # 移除 id 字段（模拟 MongoDB 的 _id: 0）
        result.pop('id', None)

        return result

    def _prepare_device_data(self, item):
        """
        准备设备数据用于插入/更新
        """
        data = {}
        field_mapping = {
            'udid': 'udid',
            'serial': 'serial',
            'ip': 'ip',
            'port': 'port',
            'present': 'present',
            'ready': 'ready',
            'using': 'using_device',
            'is_server': 'is_server',
            'is_mock': 'is_mock',
            'update_time': 'update_time',
            'model': 'model',
            'brand': 'brand',
            'version': 'version',
            'sdk': 'sdk',
            'owner': 'owner',
            'provider': 'provider',
            'agentVersion': 'agent_version',
            'hwaddr': 'hwaddr',
            'createdAt': 'created_at',
            'updatedAt': 'updated_at',
        }

        for mongo_key, sqlite_key in field_mapping.items():
            if mongo_key in item:
                value = item[mongo_key]
                # 布尔值转整数
                if isinstance(value, bool):
                    value = 1 if value else 0
                data[sqlite_key] = value

        # JSON字段
        for json_field in ('memory', 'cpu', 'battery', 'display'):
            if json_field in item:
                data[json_field] = json.dumps(item[json_field]) if item[json_field] else None

        # 额外数据
        extra = {k: v for k, v in item.items() if k not in field_mapping and k not in ('memory', 'cpu', 'battery', 'display')}
        if extra:
            data['extra_data'] = json.dumps(extra)

        return data

    async def insert_many(self, items):
        """
        批量插入设备
        :param items: 设备列表
        """
        await self._ensure_initialized()

        async with aiosqlite.connect(self.db_path) as db:
            for item in items:
                data = self._prepare_device_data(item)
                if not data:
                    continue

                columns = ', '.join(data.keys())
                placeholders = ', '.join(['?' for _ in data])
                values = list(data.values())

                try:
                    await db.execute(
                        f'INSERT OR REPLACE INTO devices ({columns}) VALUES ({placeholders})',
                        values
                    )
                except Exception as e:
                    logger.error(f"Insert error: {e}")

            await db.commit()

    async def upsert(self, condition, item):
        """
        根据udid更新或插入设备
        :param condition: udid
        :param item: 设备数据
        """
        await self._ensure_initialized()

        data = self._prepare_device_data(item)
        if 'udid' not in data:
            data['udid'] = condition

        try:
            async with aiosqlite.connect(self.db_path, timeout=30) as db:
                # 使用 INSERT ... ON CONFLICT 实现 upsert
                columns = ', '.join(data.keys())
                placeholders = ', '.join(['?' for _ in data])
                update_clause = ', '.join([f'{k} = excluded.{k}' for k in data.keys() if k != 'udid'])
                values = list(data.values())

                sql = f'''
                    INSERT INTO devices ({columns}) VALUES ({placeholders})
                    ON CONFLICT(udid) DO UPDATE SET {update_clause}
                '''
                await db.execute(sql, values)
                await db.commit()
                logger.debug(f"[SQLite] Device upserted: {condition}")

        except Exception as e:
            logger.error(f"[SQLite] Upsert error for {condition}: {e}")
            import traceback
            traceback.print_exc()

    async def update(self, condition, item):
        """
        根据udid更新设备（不插入）
        :param condition: udid
        :param item: 设备数据
        """
        await self._ensure_initialized()

        data = self._prepare_device_data(item)
        if not data:
            return

        async with aiosqlite.connect(self.db_path) as db:
            set_clause = ', '.join([f'{k} = ?' for k in data.keys()])
            values = list(data.values()) + [condition]
            await db.execute(f'UPDATE devices SET {set_clause} WHERE udid = ?', values)
            await db.commit()

    async def find_by_udid(self, udid):
        """
        根据udid查询设备
        :param udid: 设备唯一标识
        :return: 设备字典或None
        """
        await self._ensure_initialized()
        logger.debug(f"udid >>>>>> {udid}")

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM devices WHERE udid = ?', (udid,))
            row = await cursor.fetchone()

            if row:
                columns = [description[0] for description in cursor.description]
                return self._device_to_dict(row, columns)
            return None

    async def find_device_list(self):
        """
        获取在线设备列表
        :return: 设备列表
        """
        await self._ensure_initialized()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT * FROM devices WHERE present = 1')
            columns = [description[0] for description in cursor.description]
            rows = await cursor.fetchall()

            return [self._device_to_dict(row, columns) for row in rows]

    async def query_device_list_by_present(self):
        """
        根据present状态查询在线设备
        :return: 设备列表
        """
        return await self.find_device_list()

    async def query_install_file(self, group, start, end):
        """
        分页查询已上传文件
        :param group: 分组
        :param start: 起始位置
        :param end: 数量限制
        :return: 文件列表
        """
        await self._ensure_initialized()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT * FROM installed_file WHERE group_name = ? LIMIT ? OFFSET ?',
                (group, end, start)
            )
            columns = [description[0] for description in cursor.description]
            rows = await cursor.fetchall()

            result = []
            for row in rows:
                item = {}
                for i, col in enumerate(columns):
                    value = row[i]
                    if col == 'group_name':
                        col = 'group'
                    elif col == 'extra_data' and value:
                        try:
                            extra = json.loads(value)
                            item.update(extra)
                            continue
                        except:
                            pass
                    item[col] = value
                item.pop('id', None)
                result.append(item)

            return result

    async def query_all_install_file(self):
        """
        查询所有已安装文件数量
        :return: 文件数量
        """
        await self._ensure_initialized()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT COUNT(*) FROM installed_file')
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def save_install_file(self, file):
        """
        保存上传文件信息
        :param file: 文件信息字典
        """
        await self._ensure_initialized()

        group = file.get('group', '')
        filename = file.get('filename', '')
        filesize = file.get('filesize')
        upload_time = file.get('upload_time', datetime.now().isoformat())
        who = file.get('who', '')

        # 其他额外数据
        extra_keys = set(file.keys()) - {'group', 'filename', 'filesize', 'upload_time', 'who'}
        extra_data = json.dumps({k: file[k] for k in extra_keys}) if extra_keys else None

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT OR REPLACE INTO installed_file
                (group_name, filename, filesize, upload_time, who, extra_data)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (group, filename, filesize, upload_time, who, extra_data))
            await db.commit()

    async def delect_install_file_by_id(self, group, filename):
        """
        删除文件记录
        :param group: 分组
        :param filename: 文件名
        """
        await self._ensure_initialized()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'DELETE FROM installed_file WHERE group_name = ? AND filename = ?',
                (group, filename)
            )
            await db.commit()

    async def delect_devices(self):
        """
        删除所有设备记录
        """
        await self._ensure_initialized()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM devices')
            await db.commit()

        logger.debug("All devices deleted from SQLite")


# 单例实例
motor = SQLiteHelper()
