# -*- coding: utf-8 -*-
"""词典查询模块。

作用：
    把"查单词释义"这件事封装成一个统一接口 lookup(word)。
    上层（words.py 的路由）只管调用 lookup("abandon")，拿到释义字典。
    底层用两个数据源：
      1. ECDICT 本地 SQLite 数据库（instance/ecdict.db）—— 音标、中英文释义、词性、
         考试标签、词频、词形变化等，离线可用。
      2. freeDictionaryAPI（在线）—— 补充英文例句。需要联网，失败不影响查词。

为什么要单独封装成一个模块？
    1. 词典库（ecdict.db）和用户生词库（words.db）是两个独立的数据库文件，
       查询逻辑也不一样，分开管理更清晰。
    2. 后期如果想换词典（比如换成柯林斯原版、或加个在线 API 兜底），
       只需要改这个文件里的 lookup() 函数，上层路由一行都不用动。
    3. 后期如果想"导入新词典"，只需把新数据导入成新的 ecdict.db 替换即可，
       或者在这里加多数据源查询逻辑。

接口说明：
    lookup(word) -> dict | None
        输入：英文单词字符串
        输出：包含释义的字典，字段有 word/phonetic/translation/definition/
              pos/examples 等；查不到返回 None。
"""

import json
import os
import socket
import sqlite3
import urllib.request
import requests
from flask import current_app, g

# ==================== 强制 IPv4 ====================
#
# 背景：在某些网络环境下，Python 用 IPv6 连接 api.dictionaryapi.dev 会超时，
#       但 IPv4 正常。这里把 socket.getaddrinfo 替换成只返回 IPv4 结果的版本，
#       让所有 HTTPS 请求都走 IPv4。
# 影响范围：本进程内所有用 socket 的网络请求（包括 urllib/requests）。
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_getaddrinfo(*args, **kwargs):
    """只返回 IPv4 地址的 getaddrinfo。"""
    res = _orig_getaddrinfo(*args, **kwargs)
    return [r for r in res if r[0] == socket.AF_INET]


socket.getaddrinfo = _ipv4_getaddrinfo


# ==================== 在线词典 API 配置 ====================

# freeDictionaryAPI：免费、无需 key，返回英文释义+例句
# 文档：https://dictionaryapi.dev/
DICT_API_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
DICT_API_TIMEOUT = 4  # 秒（国内访问可能慢，超时短一点不卡页面）

# 例句缓存：同一个词不用重复调 API
# 结构：{word: [example1, example2, ...]}
_example_cache = {}


def get_dict_db():
    """获取词典数据库连接（和 get_db() 一样的思路，每次请求复用）。

    词典库是独立的 SQLite 文件 instance/ecdict.db，
    和用户数据的 instance/words.db 互不干扰。
    """
    if "dict_db" not in g:
        dict_db_path = os.path.join(current_app.instance_path, "ecdict.db")
        g.dict_db = sqlite3.connect(dict_db_path)
        g.dict_db.row_factory = sqlite3.Row
    return g.dict_db


def close_dict_db(e=None):
    """请求结束时关闭词典数据库连接。"""
    db = g.pop("dict_db", None)
    if db is not None:
        db.close()


def fetch_examples(word):
    """从 freeDictionaryAPI 获取单词的英文例句。

    Args:
        word: 英文单词

    Returns:
        list[str]: 例句列表（可能为空）。
                   如果 API 调用失败，返回空列表（不抛异常，不影响查词）。

    设计要点：
      - 有缓存：同一个词只调一次 API
      - 有超时：10 秒，避免页面卡死
      - 有容错：API 挂了返回空列表，主流程不受影响
      - 强制 IPv4：解决国内网络环境下的超时问题
    """
    word_lower = word.lower()

    # 命中缓存 → 直接返回
    if word_lower in _example_cache:
        return _example_cache[word_lower]

    url = DICT_API_URL.format(word=urllib.request.quote(word_lower))
    examples = []

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=DICT_API_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

            # API 返回的是一个列表，每个元素是一个词条
            # 每个词条下有 meanings（按词性分组），每个 meaning 下有 definitions
            # 每个 definition 可能有 example 字段
            for entry in data:
                for meaning in entry.get("meanings", []):
                    for definition in meaning.get("definitions", []):
                        ex = definition.get("example")
                        if ex:
                            examples.append(ex)

    except Exception:
        # 任何异常都忽略：网络超时、JSON 解析失败、404 等
        # 查词主流程不能因为例句 API 挂了就崩
        pass

    # 存入缓存（即使是空列表也存，避免重复调失败的词）
    _example_cache[word_lower] = examples
    return examples


# Datamuse API：基于语料库的搭配数据，免费、无需 key
# rel_bga = 经常出现在该词前面的词；rel_bgb = 经常出现在该词后面的词
DATAMUSE_URL = "https://api.datamuse.com/words"
DATAMUSE_TIMEOUT = 4


# 英语停用词：冠词、代词、介词、连词、助动词等无实际搭配意义的功能词
# 过滤掉这些，才能得到有意义的固定搭配（如 "completely abandon" 而非 "the abandon"）
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "must", "of", "in", "to",
    "for", "with", "on", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "out", "off",
    "over", "under", "again", "further", "then", "once", "here", "there",
    "when", "where", "why", "how", "all", "any", "both", "each", "few",
    "more", "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "and", "but", "or",
    "because", "if", "while", "although", "though", "that", "this",
    "these", "those", "i", "you", "he", "she", "it", "we", "they", "me",
    "him", "her", "us", "them", "my", "your", "his", "its", "our",
    "their", "what", "which", "who", "whom", "its", "also", "just",
    "about", "up", "down", "out", "back", "still", "even", "get",
}


def get_collocations(word, max_per_side=4):
    """获取固定搭配。

    TODO: 当前 Datamuse 的 bigram 数据质量不好（返回 ". reminiscent"、
          "mood reminiscent" 这类无意义组合），暂时返回空列表。
          后续需要接入正式搭配语料库（如牛津搭配词典、COCA 等），
          才能给出 "comply with the law" 这种正确的固定搭配。
    """
    return []


# ==================== 柯林斯词典 API ====================
#
# 柯林斯官方 API：返回原版英文释义和例句。
# 文档：https://api.collinsdictionary.com/
# 注意：api.collinsdictionary.com 在中国大陆会被 Sucuri WAF 按国家封 IP，
#       后端调用时需要走代理（COLLINS_PROXY 环境变量）。
#       如果没配置 API key，自动降级用 ECDICT 本地英文释义。

COLLINS_API_URL = "https://api.collinsdictionary.com/api/v1/dictionaries/english-learner/word/{word}?format=json"
COLLINS_TIMEOUT = 15  # 秒

# Collins 数据缓存：{word: collins_dict}
_collins_cache = {}


def _get_collins_config():
    """从 Flask config 读取 Collins API key 和代理地址。

    Returns:
        tuple: (api_key: str, proxy: str)  都可能为空字符串
    """
    api_key = current_app.config.get("COLLINS_API_KEY", "") or ""
    proxy = current_app.config.get("COLLINS_PROXY", "") or ""
    return api_key, proxy


def fetch_collins(word):
    """从柯林斯官方 API 获取原版英文释义和例句。

    Args:
        word: 英文单词

    Returns:
        dict | None: 成功返回字典，包含：
            definition: 英文释义（多个义项用换行连接）
            examples:   柯林斯例句列表
        失败/无 key 时返回 None，由上层降级用 ECDICT 数据。

    设计要点：
      - 无 API key 时直接返回 None（不浪费时间调网络）
      - 支持 HTTP/SOCKS5 代理（解决国内 WAF 封锁）
      - 有缓存、超时、容错
    """
    word_lower = word.lower()

    # 命中缓存 → 直接返回（不管成功失败都缓存）
    if word_lower in _collins_cache:
        return _collins_cache[word_lower]

    api_key, proxy = _get_collins_config()

    # 没配置 key → 直接返回 None（上层会降级用 ECDICT）
    if not api_key:
        _collins_cache[word_lower] = None
        return None

    url = COLLINS_API_URL.format(word=requests.utils.quote(word_lower))
    headers = {"accessKey": api_key}

    # 组装代理配置：如果填了代理，HTTP/HTTPS 都走它
    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    try:
        resp = requests.get(url, headers=headers, proxies=proxies, timeout=COLLINS_TIMEOUT)
        resp.raise_for_status()  # 4xx/5xx 抛异常
        data = resp.json()

        # Collins API 返回结构：
        # data["results"] -> 多个 entry
        #   entry["entryContent"] 是 HTML 字符串，包含完整释义
        # 但对我们来说，更实用的是 entry["senses"]：
        #   senses[i]["definition"] -> 英文释义
        #   senses[i]["examples"] -> [{"text": "..."}] 例句列表
        # 实际 API 可能用不同字段名，这里做兼容处理。

        definitions = []
        examples = []

        results = data.get("results", [])
        for entry in results:
            # 提取释义：尝试多种可能的字段名
            for sense in entry.get("senses", []):
                d = sense.get("definition") or sense.get("def") or ""
                if d:
                    definitions.append(d.strip())
                # 提取例句
                for ex in sense.get("examples", []):
                    ex_text = ex.get("text") if isinstance(ex, dict) else str(ex)
                    if ex_text:
                        examples.append(ex_text.strip())

            # 有些 API 版本用 "homographs" 嵌套
            for homo in entry.get("homographs", []):
                for sense in homo.get("senses", []):
                    d = sense.get("definition") or sense.get("def") or ""
                    if d:
                        definitions.append(d.strip())
                    for ex in sense.get("examples", []):
                        ex_text = ex.get("text") if isinstance(ex, dict) else str(ex)
                        if ex_text:
                            examples.append(ex_text.strip())

        # 去重但保持顺序
        seen = set()
        def_unique = []
        for d in definitions:
            if d not in seen:
                seen.add(d)
                def_unique.append(d)
        seen.clear()
        ex_unique = []
        for e in examples:
            if e not in seen:
                seen.add(e)
                ex_unique.append(e)

        result = {
            "definition": "\n".join(def_unique) if def_unique else None,
            "examples": ex_unique,
        }
        _collins_cache[word_lower] = result
        return result

    except Exception:
        # 网络错误、WAF 拦截、JSON 解析失败等 → 缓存 None，降级用 ECDICT
        _collins_cache[word_lower] = None
        return None


# lookup 整体缓存：{word: result_dict}（同一进程内同一词只查一次）
_lookup_cache = {}


def lookup(word):
    """查单词释义（本地词典 + 在线例句）。

    Args:
        word: 英文单词，例如 "abandon"

    Returns:
        dict: 包含以下字段的字典；查不到返回 None。
            word        单词
            phonetic    音标
            translation 中文释义
            definition  英文释义
            pos         词性
            collins     柯林斯星级（1-5，越高越常用）
            oxford      是否牛津3000核心词
            tag         考试标签（cet4/cet6/ky/toefl/ielts 等）
            bnc         英国国家语料库词频排名
            frq         当代语料库词频排名
            exchange    词形变化
            examples    英文例句列表（来自在线 API，可能为空）

    查词规则：大小写不敏感，精确匹配单词本身。
    """
    if not word or not word.strip():
        return None

    word = word.strip()
    word_lower = word.lower()

    # 先查缓存
    if word_lower in _lookup_cache:
        return _lookup_cache[word_lower]

    db = get_dict_db()

    row = db.execute(
        "SELECT * FROM stardict WHERE LOWER(word) = LOWER(?)",
        (word,),
    ).fetchone()

    if row is None:
        return None

    # ECDICT 的 translation 里换行可能是字面量 \n，统一换成真换行符
    translation = (row["translation"] or "").replace("\\n", "\n")

    # 组装结果字典
    result = {
        "word": row["word"],
        "phonetic": row["phonetic"],
        "definition": row["definition"],
        "translation": translation,
        "pos": row["pos"],
        "collins": row["collins"],
        "oxford": row["oxford"],
        "tag": row["tag"],
        "bnc": row["bnc"],
        "frq": row["frq"],
        "exchange": row["exchange"],
    }

    # 补充在线例句（失败不影响主流程）
    result["examples"] = fetch_examples(row["word"])

    # 补充固定搭配（来自 Datamuse 语料库，失败不影响主流程）
    result["collocations"] = get_collocations(row["word"])

    # 补充柯林斯原版英文释义和例句（需要 API key，失败降级用 ECDICT）
    collins_data = fetch_collins(row["word"])
    if collins_data:
        # 有 Collins 数据 → 用柯林斯的英文释义和例句
        if collins_data.get("definition"):
            result["collins_definition"] = collins_data["definition"]
        if collins_data.get("examples"):
            # Collins 例句质量更高，优先用；ECDICT 例句作为补充
            result["collins_examples"] = collins_data["examples"]
            # 把 Collins 例句合并到主例句列表前面
            all_examples = collins_data["examples"] + result["examples"]
            seen = set()
            merged = []
            for ex in all_examples:
                if ex not in seen:
                    seen.add(ex)
                    merged.append(ex)
            result["examples"] = merged
    else:
        # 没 Collins 数据 → 用 ECDICT 的英文释义
        result["collins_definition"] = row["definition"]

    # 整体缓存（同一进程内同一词只查一次，包括在线 API 结果）
    _lookup_cache[word_lower] = result
    return result


def lookup_local(word):
    """只查本地 ECDICT 词典，不调任何在线 API。

    用于复习页面（释义、音标足够，不需要例句/搭配），避免网络卡顿。
    返回字段和 lookup 基本一致，但 examples/collocations 为空。
    """
    if not word or not word.strip():
        return None
    word = word.strip()
    word_lower = word.lower()

    # 复用 lookup 的缓存（如果已经查过完整数据，直接用）
    if word_lower in _lookup_cache:
        return _lookup_cache[word_lower]

    db = get_dict_db()
    row = db.execute(
        "SELECT * FROM stardict WHERE LOWER(word) = LOWER(?)",
        (word,),
    ).fetchone()
    if row is None:
        return None

    # ECDICT 的 translation 里换行可能是字面量 \n，统一换成真换行符
    translation = (row["translation"] or "").replace("\\n", "\n")

    result = {
        "word": row["word"],
        "phonetic": row["phonetic"],
        "definition": row["definition"],
        "translation": translation,
        "pos": row["pos"],
        "collins": row["collins"],
        "oxford": row["oxford"],
        "tag": row["tag"],
        "bnc": row["bnc"],
        "frq": row["frq"],
        "exchange": row["exchange"],
        "examples": [],
        "collocations": [],
        "collins_definition": row["definition"],
    }
    return result


def init_dict_app(app):
    """把词典模块挂到 Flask 应用上。

    - 告诉 Flask：每次请求结束，都跑一下 close_dict_db（自动关连接）
    """
    app.teardown_appcontext(close_dict_db)
