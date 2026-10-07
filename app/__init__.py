# -*- coding: utf-8 -*-
"""应用工厂模块（后端总管）。

这个文件有两个身份：
1. 因为 app 文件夹里有 __init__.py，Python 就把 app 当成一个"包"(package)，
   别的文件才能写 `from app import create_app`。
2. create_app() 叫"应用工厂"：每次调用它，就组装出一个完整的 Flask 程序，
负责 创建 app 对象、最后把三个蓝图（账号 / 生词本 / 复习）拼到一起

"蓝图(Blueprint)"可以理解为每个功能模块的工牌：
auth.py、words.py、review.py 各自在自己的文件里干活，
最后到这里统一"注册挂牌"，总管才知道它们存在。
"""

import os
from flask import Flask, render_template, g
from dotenv import load_dotenv  # 读取 .env 文件里的环境变量（API key 等）

# 同一个包里的模块，import 路径里的点表示"当前包"
from . import auth, words, review, settings, db, dictionary

# 加载项目根目录下的 .env 文件
# override=True 表示 .env 里的值会覆盖已有的环境变量
load_dotenv(override=True)


def create_app():
    # 1. 创建 Flask 应用对象，它是整个后端的总管
    app = Flask(__name__)

    # 2. 配置项
    # SECRET_KEY：给 session/flash 加密的钥匙
    #   —— flash 的错误消息、以后的登录状态都存在 session 里，需要钥匙加密
    #   开发期随便写一个固定值；正式上线要换成随机密钥并保密
    app.config["SECRET_KEY"] = "dev-secret-key-change-in-production"

    # 数据库文件放在项目根目录下的 instance/words.db
    #    Flask 会自动创建 instance 文件夹
    app.config["DATABASE"] = os.path.join(app.instance_path, "words.db")
    os.makedirs(app.instance_path, exist_ok=True)  # 确保 instance 文件夹存在

    # 柯林斯词典 API 配置（从 .env 读取）
    # COLLINS_API_KEY 为空时，查词自动降级用 ECDICT 本地英文释义
    app.config["COLLINS_API_KEY"] = os.environ.get("COLLINS_API_KEY", "")
    app.config["COLLINS_PROXY"] = os.environ.get("COLLINS_PROXY", "")

    # 3. 把数据库工具挂到总管上（注册"请求结束自动关连接"和 init-db 命令）
    db.init_app(app)

    # 3.5 把词典模块挂到总管上（注册词典库连接的自动关闭）
    dictionary.init_dict_app(app)

    # 4. 注册蓝图：把三个模块挂到总管身上
    #    例如 auth.py 里定义的 /hello，注册后实际访问地址是 /auth/hello
    app.register_blueprint(auth.bp, url_prefix="/auth")
    app.register_blueprint(words.bp, url_prefix="/words")
    app.register_blueprint(review.bp, url_prefix="/review")
    app.register_blueprint(settings.bp, url_prefix="/settings")

    # 3. 首页路由：显示学习概况（已登录）或欢迎页（未登录）
    @app.route("/")
    def index():
        # 未登录只渲染欢迎页，不查数据库
        if g.user is None:
            return render_template("index.html")

        # 已登录：查今日待复习数和生词本总数
        from .db import get_db
        db = get_db()
        due_count = db.execute(
            "SELECT COUNT(*) FROM reviews WHERE user_id = ? AND next_review <= DATE('now')",
            (g.user["id"],),
        ).fetchone()[0]
        word_count = db.execute(
            "SELECT COUNT(*) FROM words WHERE user_id = ?",
            (g.user["id"],),
        ).fetchone()[0]
        return render_template("index.html", due_count=due_count, word_count=word_count)

    # 4. 禁止浏览器缓存 HTML 页面（开发期专用，避免改了模板浏览器还显示旧的）
    #    通过 after_request 钩子，给每个响应加上"不要缓存"的 HTTP 头
    @app.after_request
    def no_cache(response):
        # 只对 HTML 页面生效，静态文件（CSS/JS）让浏览器正常缓存
        if response.content_type and "text/html" in response.content_type:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    return app
