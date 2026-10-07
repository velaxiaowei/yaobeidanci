# -*- coding: utf-8 -*-
"""设置模块（蓝图）。

负责用户学习偏好设置：
- daily_count：每次复习的单词数（15/20/25/30/35/40）
- spelling_enabled：复习完后是否进入拼写巩固（开/关）
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session

from .auth import login_required
from .db import get_db
from .sms import send_verify_code, verify_code, get_last_dev_code, is_dev_mode

bp = Blueprint("settings", __name__)


@bp.route("/", methods=("GET", "POST"))
@login_required
def index():
    """设置页：GET 显示当前设置，POST 保存新设置。"""
    db = get_db()

    if request.method == "POST":
        daily_count = request.form.get("daily_count", type=int)
        spelling_enabled = 1 if request.form.get("spelling_enabled") else 0
        default_accent = request.form.get("default_accent", "en")
        auto_pronounce = 1 if request.form.get("auto_pronounce") else 0

        # 校验 daily_count 必须在允许的列表里
        allowed = [15, 20, 25, 30, 35, 40]
        if daily_count not in allowed:
            daily_count = 20

        # 校验发音只能是 en 或 us
        if default_accent not in ("en", "us"):
            default_accent = "en"

        db.execute(
            "UPDATE user_settings SET daily_count = ?, spelling_enabled = ?, "
            "default_accent = ?, auto_pronounce = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (daily_count, spelling_enabled, default_accent, auto_pronounce, g.user["id"]),
        )
        db.commit()
        flash("设置已保存")
        return redirect(url_for("settings.index"))

    # GET：读取当前设置
    settings = db.execute(
        "SELECT daily_count, spelling_enabled, default_accent, auto_pronounce "
        "FROM user_settings WHERE user_id = ?",
        (g.user["id"],),
    ).fetchone()

    phone = db.execute(
        "SELECT phone FROM users WHERE id = ?", (g.user["id"],)
    ).fetchone()["phone"]

    return render_template("settings.html", settings=settings, phone=phone)


@bp.route("/bind-phone", methods=("POST",))
@login_required
def bind_phone():
    """绑定/更换手机号：发短信验证码 → 验证通过后保存。"""
    action = request.form.get("action", "")
    db = get_db()
    phone = request.form.get("phone", "").strip()

    if action == "send_code":
        if not phone or len(phone) != 11 or not phone.isdigit():
            flash("请输入正确的11位手机号")
        else:
            # 检查手机号是否已被其他账号绑定
            existing = db.execute(
                "SELECT id FROM users WHERE phone = ? AND id != ?",
                (phone, g.user["id"]),
            ).fetchone()
            if existing:
                flash("该手机号已被其他账号绑定")
            else:
                send_verify_code(phone)
                session["bind_phone"] = phone
                if is_dev_mode():
                    dev = get_last_dev_code()
                    if dev:
                        flash(f"【开发模式】验证码：{dev['code']}（真实环境会发短信，不会显示）")
                    else:
                        flash("验证码已发送，请查看 instance/dev_sms_code.txt 文件")
                else:
                    flash("验证码已发送到手机，请查收")
        return redirect(url_for("settings.index"))

    if action == "verify":
        code = request.form.get("code", "").strip()
        pending_phone = session.get("bind_phone", "")
        if not pending_phone:
            flash("请先发送验证码")
        elif not code:
            flash("请输入验证码")
        elif not verify_code(pending_phone, code):
            flash("验证码错误或已过期")
        else:
            db.execute(
                "UPDATE users SET phone = ? WHERE id = ?",
                (pending_phone, g.user["id"]),
            )
            db.commit()
            session.pop("bind_phone", None)
            flash("手机号绑定成功")
        return redirect(url_for("settings.index"))

    return redirect(url_for("settings.index"))
