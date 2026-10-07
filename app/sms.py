# -*- coding: utf-8 -*-
"""短信验证码模块。

两种模式：
1. 开发模式（默认）：验证码写文件 + 页面显示，不真发短信。
   用于本地开发，不用花钱。
2. 阿里云短信：在 .env 里配好 ALIYUN_SMS_* 后自动启用，真发短信。

使用方法：
    from .sms import send_verify_code, verify_code
    code = send_verify_code(phone)   # 发送验证码，返回验证码字符串
    ok = verify_code(phone, code)    # 校验（5分钟内有效）

开发模式查看验证码：
    - 文件 instance/dev_sms_code.txt（最新一条）
    - 页面 flash 消息（自动显示）
    - 终端 stderr（部分终端可能看不到）
"""

import random
import time
import os
import sys

from flask import current_app


# 验证码存储：{phone: {"code": "1234", "expire": 时间戳}}
# 生产环境应该用 Redis，这里用内存字典够单机用
_code_store = {}

# 开发模式下最近一条验证码（页面显示用）
_last_dev_code = {"phone": "", "code": "", "time": 0}

# 验证码有效期（秒）
CODE_EXPIRE = 300  # 5分钟

# 项目根目录
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 开发模式验证码文件路径
_DEV_CODE_FILE = os.path.join(_BASE_DIR, "instance", "dev_sms_code.txt")


def generate_code():
    """生成6位数字验证码。"""
    return "".join(random.choices("0123456789", k=6))


def send_verify_code(phone):
    """给手机号发送验证码，返回验证码字符串。

    如果配了阿里云 SMS 配置就真发，否则走开发模式。
    """
    code = generate_code()
    _code_store[phone] = {"code": code, "expire": time.time() + CODE_EXPIRE}

    # 尝试用阿里云短信发送（配了 .env 才启用）
    if _send_aliyun_sms(phone, code):
        return code

    # 开发模式：三种方式记录验证码，总有一种能看到
    msg = f"[短信验证码] {phone} 的验证码是：{code}（5分钟内有效）"

    # 方式1：写到文件（最可靠）
    try:
        with open(_DEV_CODE_FILE, "w", encoding="utf-8") as f:
            f.write(f"{phone} 的验证码：{code}\n生成时间：{time.strftime('%H:%M:%S')}")
    except Exception:
        pass

    # 方式2：存到内存，页面读取显示（最方便）
    _last_dev_code["phone"] = phone
    _last_dev_code["code"] = code
    _last_dev_code["time"] = time.time()

    # 方式3：打印到终端（可能被 Flask 吞掉，但有时能显示）
    print(msg, file=sys.stderr, flush=True)

    return code


def get_last_dev_code():
    """获取开发模式下最近一条验证码（页面显示用）。

    只在5分钟内有效，过期返回 None。
    生产环境（配了阿里云）不暴露此函数的结果。
    """
    if time.time() - _last_dev_code["time"] > CODE_EXPIRE:
        return None
    if not _last_dev_code["code"]:
        return None
    return {"phone": _last_dev_code["phone"], "code": _last_dev_code["code"]}


def is_dev_mode():
    """是否处于开发模式（没配阿里云短信）。"""
    ak_id = os.environ.get("ALIYUN_SMS_ACCESS_KEY_ID", "").strip()
    return not ak_id


def verify_code(phone, code):
    """校验验证码是否正确且未过期。"""
    record = _code_store.get(phone)
    if not record:
        return False
    if time.time() > record["expire"]:
        del _code_store[phone]
        return False
    if record["code"] != code:
        return False
    # 验证成功后删除，防止重复使用
    del _code_store[phone]
    return True


def _send_aliyun_sms(phone, code):
    """用阿里云短信 API 发送验证码。

    需要在 .env 里配置：
        ALIYUN_SMS_ACCESS_KEY_ID=你的AccessKeyId
        ALIYUN_SMS_ACCESS_KEY_SECRET=你的AccessKeySecret
        ALIYUN_SMS_SIGN_NAME=你的短信签名
        ALIYUN_SMS_TEMPLATE_CODE=你的模板CODE

    没配置就返回 False，走开发模式。
    """
    import urllib.request
    import urllib.parse
    import hmac
    import hashlib
    import base64
    import json

    ak_id = os.environ.get("ALIYUN_SMS_ACCESS_KEY_ID", "").strip()
    ak_secret = os.environ.get("ALIYUN_SMS_ACCESS_KEY_SECRET", "").strip()
    sign_name = os.environ.get("ALIYUN_SMS_SIGN_NAME", "").strip()
    template_code = os.environ.get("ALIYUN_SMS_TEMPLATE_CODE", "").strip()

    if not all([ak_id, ak_secret, sign_name, template_code]):
        return False  # 没配全，走开发模式

    try:
        # 阿里云短信 API 签名（简化版）
        params = {
            "PhoneNumbers": phone,
            "SignName": sign_name,
            "TemplateCode": template_code,
            "TemplateParam": json.dumps({"code": code}),
            "Action": "SendSms",
            "Version": "2017-05-25",
            "Format": "JSON",
            "AccessKeyId": ak_id,
            "SignatureMethod": "HMAC-SHA1",
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "SignatureVersion": "1.0",
            "SignatureNonce": str(time.time()),
        }

        # 签名
        sorted_params = sorted(params.items())
        query = urllib.parse.urlencode(sorted_params)
        string_to_sign = "GET&%2F&" + urllib.parse.quote(query, safe="")
        signature = base64.b64encode(
            hmac.new(
                (ak_secret + "&").encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")
        params["Signature"] = signature

        url = "https://dysmsapi.aliyuncs.com/?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("Code") == "OK":
                return True
            print(f"[阿里云短信] 发送失败: {result}")
            return False
    except Exception as e:
        print(f"[阿里云短信] 异常: {e}")
        return False
