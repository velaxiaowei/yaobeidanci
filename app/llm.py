# -*- coding: utf-8 -*-
"""大模型对话模块。

作用：
    封装 DeepSeek API 调用，给查词页底部的"智能问答"对话框用。

设计：
    - 调用 chat(word, question) 函数，传入当前单词和用户的问题，返回大模型的回答
    - 把当前单词的释义作为上下文传给大模型，让回答更精准
    - API key 从环境变量 DEEPSEEK_API_KEY 读取（在 .env 文件里配置）
    - 有超时和异常处理，API 挂了不影响查词主流程

关于上下文：
    查词时用户已经看到了 abandon 的释义，现在问"这个词能用来表白吗"。
    我们把 abandon 的释义一起塞给大模型，它就知道"这个词"指的是什么，
    回答会比只传问题更准确。
"""

import json
import os
import urllib.request
from flask import current_app

# DeepSeek API 配置
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_TIMEOUT = 30  # 秒，大模型生成回答可能需要几秒到十几秒


def get_api_key():
    """从环境变量读取 DeepSeek API key。"""
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()


def chat(word, word_info, question):
    """向大模型提问。

    Args:
        word: 当前查的单词，例如 "abandon"
        word_info: 单词的释义信息字典（来自 lookup()），用于给大模型上下文
        question: 用户的问题，例如 "这个词可以用来表白吗"

    Returns:
        str: 大模型的回答文本。如果失败，返回错误提示字符串。
    """
    api_key = get_api_key()
    if not api_key or api_key.startswith("在此处"):
        return "⚠️ 还没配置 DeepSeek API key。请在项目根目录的 .env 文件里填入你的 API key，然后重启服务器。"

    # 组装上下文：把单词释义告诉大模型，这样它知道"这个词"是什么
    context_parts = [f"单词：{word}"]
    if word_info:
        if word_info.get("phonetic"):
            context_parts.append(f"音标：{word_info['phonetic']}")
        if word_info.get("translation"):
            context_parts.append(f"中文释义：{word_info['translation']}")
        if word_info.get("definition"):
            context_parts.append(f"英文释义：{word_info['definition'][:300]}")

    context = "\n".join(context_parts)

    # 系统提示词：设定大模型的角色和回答风格
    system_prompt = (
        "你是一个英语学习助手。用户正在查一个英语单词，会问你关于这个单词的用法、"
        "搭配、场景、辨析等问题。请结合给出的单词释义，用中文简洁地回答。"
        "如果用户问某个场景能不能用这个词，要明确回答能或不能，并举例说明。"
        "回答不要太长，重点突出。"
    )

    # 用户消息：上下文 + 问题
    user_message = f"【单词信息】\n{context}\n\n【我的问题】\n{question}"

    # 组装请求体
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.7,   # 0.7 是比较平衡的创造力
        "max_tokens": 1000,   # 限制回答长度，避免烧钱
    }

    try:
        req = urllib.request.Request(
            DEEPSEEK_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=DEEPSEEK_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # 从响应中提取回答文本
            return data["choices"][0]["message"]["content"]

    except urllib.error.HTTPError as e:
        # HTTP 错误：401（key 错了）、429（额度用完）、500（服务器挂了）等
        body = e.read().decode("utf-8", errors="ignore")
        return f"⚠️ 大模型 API 出错了（HTTP {e.code}）：{body[:200]}"

    except Exception as e:
        # 其他异常：网络超时、JSON 解析失败等
        return f"⚠️ 调用大模型失败：{type(e).__name__}: {str(e)[:100]}"
