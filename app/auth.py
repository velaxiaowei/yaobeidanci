# -*- coding: utf-8 -*-
"""账号模块（蓝图）。

负责：注册 / 登录 / 登出。
这是"同步的根基"——用户登录后，后端才能识别请求来自哪位用户，
从而保证不同人的生词本互相隔离、电脑和手机看到同一份数据。
"""

from flask import (
    Blueprint,               # 蓝图
    render_template,         # 渲染模板（把牌子拿出来）
    request,                # 读取用户提交的表单数据
    redirect,               # 重定向（把用户甩到另一个网址）
    url_for,                # 根据函数名反查网址
    flash,                  # 闪现消息（一次性的错误/成功提示）
    session,                # 会话：服务器用来"记住"当前登录用户的小本子
    g,                      # g：本次请求的"便签本"，存当前登录用户供所有页面使用
)
# werkzeug 是 Flask 自带的安全工具包
# generate_password_hash：注册时把明文密码变成指纹存进库
# check_password_hash   ：登录时把用户输入的密码和库里的指纹比对，返回 True/False
from werkzeug.security import generate_password_hash, check_password_hash

from .db import get_db
from .sms import send_verify_code, verify_code, get_last_dev_code, is_dev_mode

# 创建蓝图对象。"auth" 是它在 Flask 里的唯一名
bp = Blueprint("auth", __name__)


# ==================== 登录拦截装饰器 ====================
#
# 装饰器（decorator）：给函数贴个"标签"，让它执行前先跑一段检查。
# 用法：在某个路由函数上面写 @login_required，访问那个路由时就会先检查登录。
# 没登录 → 甩去登录页；登录了 → 放行。
#
# 这样不用在每个需要登录的页面里都手写一遍 if session.get("user_id") is None。
import functools  # functools.wraps 用来保留原函数的名字和说明（规范写法）

def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        # session 里没存 user_id → 说明没登录
        if session.get("user_id") is None:
            return redirect(url_for("auth.login"))  # 甩去登录页
        # 登录了 → 正常执行原函数
        return view(**kwargs)
    return wrapped_view


# ==================== 每次请求前自动加载当前用户 ====================
#
# @bp.before_app_request：这个蓝图里注册的钩子，但会在"整个应用"的每次请求前都跑。
# 作用：如果用户已登录（session 里有 user_id），就把这个用户的完整信息查出来
#       贴到 g 这个便签本上。之后模板（base.html 等）就能直接用 g.user 拿到用户名。
@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")  # 从 session 取 user_id

    if user_id is None:
        g.user = None  # 没登录 → g.user 是空的
        g.settings = None
    else:
        # 登录了 → 去数据库把这个用户的信息查出来贴到 g 上
        g.user = get_db().execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        # 顺便把用户的学习偏好设置也贴到 g 上，复习页要用
        g.settings = get_db().execute(
            "SELECT daily_count, spelling_enabled, default_accent, auto_pronounce "
            "FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()


# ==================== 注册 ====================

# methods=("GET", "POST") 表示这个路由同时接待两种请求：
#   GET  → 用户刚打开注册页，只是想"看"表单
#   POST → 用户点了"注册"按钮，提交了表单数据
@bp.route("/register", methods=("GET", "POST"))
def register():
    # ---------- POST 分支：用户点了注册按钮 ----------
    if request.method == "POST":
        # request.form 是一个字典，键就是 HTML 里 <input name="xxx"> 的 xxx
        username = request.form["username"]    # 取出用户填的用户名
        password = request.form["password"]    # 取出密码
        confirm  = request.form["confirm"]     # 取出确认密码
        phone    = request.form.get("phone", "").strip()  # 手机号（可选）

        db = get_db()                          # 拿到数据库连接
        error = None                           # 先假设没有错误

        # ---------- 输入校验 ----------
        if not username:
            error = "请输入用户名"
        elif not password:
            error = "请输入密码"
        elif password != confirm:
            error = "两次输入的密码不一致"
        elif phone and (len(phone) != 11 or not phone.isdigit()):
            error = "手机号格式不正确"
        elif phone and db.execute(
            "SELECT id FROM users WHERE phone = ?", (phone,)
        ).fetchone() is not None:
            error = "该手机号已被注册"
        elif db.execute(
            # 查一下这个用户名是否已经被人注册了
            # ? 是占位符，(username,) 里的值会安全地填进去
            # 防止 SQL 注入——永远不要用字符串拼接拼 SQL！
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone() is not None:
            error = f"用户名 '{username}' 已被注册，请换一个"

        # ---------- 没有错误 → 哈希密码并存入数据库 ----------
        if error is None:
            cursor = db.execute(
                # 只填两列，id 和 created_at 数据库自动补
                # generate_password_hash 会把 '123456' 变成指纹字符串
                "INSERT INTO users (username, password_hash, phone) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), phone or None),
            )
            new_user_id = cursor.lastrowid
            # 同时给新用户建一条默认设置（每日20个，拼写巩固关）
            db.execute(
                "INSERT INTO user_settings (user_id) VALUES (?)",
                (new_user_id,),
            )
            db.commit()  # 提交事务：真正写进数据库文件
            # 注册成功，把用户甩到登录页
            return redirect(url_for("auth.login"))

        # 如果有错误，用 flash 把错误消息存起来，页面会显示它
        flash(error)

    # ---------- GET 分支（或 POST 有错误回到表单）----------
    # 显示注册页面
    return render_template("auth/register.html")


# ==================== 登录 ====================

@bp.route("/login", methods=("GET", "POST"))
def login():
    # ---------- POST 分支：用户点了登录按钮 ----------
    if request.method == "POST":
        username = request.form["username"]  # 取出用户名
        password = request.form["password"]  # 取出密码

        db = get_db()
        error = None

        # 第一步：根据用户名去数据库查这个用户
        # 如果用户名不存在，user 就是 None
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        # 第二步：校验
        # 注意：故意把"用户名不存在"和"密码错误"合并成同一句提示
        #       防止攻击者靠不同提示猜哪些用户名已经注册
        if user is None:
            error = "用户名或密码错误"
        elif not check_password_hash(user["password_hash"], password):
            # check_password_hash(库里存的指纹, 用户输入的明文密码)
            # 内部会把 password 也哈希一遍，再和 user["password_hash"] 比对
            error = "用户名或密码错误"

        # 第三步：没错 → 登录成功，把 user_id 写进 session
        if error is None:
            # session 是一个字典，Flask 会自动：
            #   1. 把 {"user_id": 1} 签上名
            #   2. 塞进 cookie 发回浏览器
            # 之后每个请求，Flask 会自动验签、把 user_id 还给我们
            session.clear()                       # 先清空旧的（防止旧会话残留）
            session["user_id"] = user["id"]       # 记下当前是谁登录了
            return redirect(url_for("index"))     # 登录成功去首页

        flash(error)

    # ---------- GET 分支（或 POST 有错误回到表单）----------
    return render_template("auth/login.html")


# ==================== 登出 ====================

@bp.route("/logout")
def logout():
    # 登出就是把 session 清空——撕掉那张带火漆印的纸条
    # session.clear() 会把 session 字典清空，浏览器再请求时就带不上有效的 user_id 了
    session.clear()
    return redirect(url_for("index"))  # 登出后回首页


# ==================== 找回密码（手机号 + 短信验证码）====================

@bp.route("/forgot-password", methods=("GET", "POST"))
def forgot_password():
    """找回密码：输入用户名 → 给绑定的手机号发短信验证码 → 重置密码。

    流程分三步，全在同一个路由里，靠 session 里的 step 标记推进：
      step 1 (GET/POST 无 action)：输入用户名
      step 2 (action=send_code)  ：发短信验证码
      step 3 (action=reset)       ：验验证码 + 设新密码
    """
    # POST 处理
    if request.method == "POST":
        action = request.form.get("action", "")
        db = get_db()

        # ---- 第一步：提交用户名，检查是否绑定了手机号 ----
        if action == "submit_username":
            username = request.form.get("username", "").strip()
            user = db.execute(
                "SELECT id, username, phone FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if user is None:
                flash("用户名不存在")
                return render_template("auth/forgot_password.html", step=1)
            if not user["phone"]:
                flash("该账号未绑定手机号，无法用短信找回，请联系管理员")
                return render_template("auth/forgot_password.html", step=1)
            # 用户名合法，进入第二步
            session["fp_user_id"] = user["id"]
            session["fp_username"] = user["username"]
            session["fp_phone"] = user["phone"]
            return render_template(
                "auth/forgot_password.html",
                step=2,
                username=user["username"],
                phone=user["phone"],
            )

        # ---- 第二步：发送短信验证码 ----
        if action == "send_code":
            phone = session.get("fp_phone", "")
            if not phone:
                return redirect(url_for("auth.forgot_password"))
            send_verify_code(phone)
            # 开发模式直接在页面显示验证码
            if is_dev_mode():
                dev = get_last_dev_code()
                if dev:
                    flash(f"【开发模式】验证码：{dev['code']}（真实环境会发短信，不会显示）")
                else:
                    flash("验证码已发送，请查看 instance/dev_sms_code.txt 文件")
            else:
                flash("验证码已发送到手机，请查收")
            return render_template(
                "auth/forgot_password.html",
                step=2,
                username=session.get("fp_username", ""),
                phone=phone,
            )

        # ---- 第三步：验验证码 + 重置密码 ----
        if action == "reset":
            phone = session.get("fp_phone", "")
            user_id = session.get("fp_user_id")
            code = request.form.get("code", "").strip()
            new_password = request.form.get("new_password", "")
            confirm = request.form.get("confirm", "")

            if not phone or not user_id:
                return redirect(url_for("auth.forgot_password"))
            if not code:
                flash("请输入验证码")
            elif not new_password:
                flash("请输入新密码")
            elif new_password != confirm:
                flash("两次输入的密码不一致")
            elif not verify_code(phone, code):
                flash("验证码错误或已过期")
            else:
                # 校验通过，更新密码
                db.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new_password), user_id),
                )
                db.commit()
                # 清理 session
                session.pop("fp_user_id", None)
                session.pop("fp_username", None)
                session.pop("fp_phone", None)
                flash("密码已重置，请用新密码登录")
                return redirect(url_for("auth.login"))

            return render_template(
                "auth/forgot_password.html",
                step=2,
                username=session.get("fp_username", ""),
                phone=phone,
            )

    # GET：默认第一步
    return render_template("auth/forgot_password.html", step=1)


# ==================== 原占位路由（验证蓝图用，可删可留）====================

@bp.route("/hello")
def hello():
    return "账号模块座位已就位：注册 / 登录 / 登出 将来写在这里。"
