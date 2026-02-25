# encoding: utf-8
"""
--------------------------------------
@describe 数据库操作 - 兼容层
@version: 2.0
@project: CloudControl
@file: motor_helper.py
@note: 此文件现在是SQLite的兼容层，保持向后兼容
---------------------------------------
"""

# 从SQLite助手导入，保持接口兼容
from database.sqlite_helper import SQLiteHelper, motor

# 为了向后兼容，保留MotorHelper别名
MotorHelper = SQLiteHelper

__all__ = ['motor', 'MotorHelper', 'SQLiteHelper']
