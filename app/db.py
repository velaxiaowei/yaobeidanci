# -*- coding: utf-8 -*-
"""数据库连接工具。

本模块给后端提供三把"钥匙"：
1. get_db()   ：拿到一条通往 SQLite 数据库文件的连接（同一个请求内复用）
2. close_db() ：请求结束时关闭连接（自动调用，不用手动管）
3. init_db()  ：读取 schema.sql，把所有表建出来
"""

import sqlite3
from flask import current_app, g


def get_db():
    """获取数据库连接。

    g 是 flask 提供的"本次请求临时便签本"：
    如果便签上已经贴了 'db'（说明这次请求已经连过库），就直接拿；
    否则就新建一条连接，贴到便签上，方便同一个请求后面复用。
    """
    if "db" not in g:
        # current_app.config['DATABASE'] 存的是数据库文件的路径
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,  # 让 SQLite 自动识别时间类型
        )
        # 让查询结果以"行对象"返回，可以像字典一样用列名取值
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    """请求结束时关闭数据库连接。

    从便签 g 上把 db 取下来，如果有就关掉，便签上也擦掉。
    这个函数会被注册到 Flask 的"请求结束钩子"上，自动执行。
    """
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """执行 schema.sql，把所有表建出来。"""
    db = get_db()
    # 以文本方式读取 schema.sql，把里面的 SQL 全部交给数据库执行
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf-8"))
    db.commit()


def init_app(app):
    """把数据库工具挂到 Flask 应用上。

    - 告诉 Flask：每次请求结束，都跑一下 close_db（自动关连接）
    - 注册一个命令行命令 `flask --app run init-db`，用来一键建表
    """
    app.teardown_appcontext(close_db)  # 请求结束钩子

    # 注册自定义命令：flask --app run init-db
    @app.cli.command("init-db")
    def init_db_command():
        init_db()
        print("数据库建表完成。")
