# -*- coding: utf-8 -*-
"""把 ECDICT 的 ecdict.csv 转成 SQLite 数据库 ecdict.db。

用途：
    ECDICT 官方给的是 CSV 文件（76 万词条），直接用 CSV 查词又慢又占内存。
    这个脚本把 CSV 一次性导入 SQLite，建好索引，之后查词走数据库，毫秒级响应。

用法（在项目根目录执行）：
    venv\\Scripts\\python.exe scripts/import_ecdict.py

输入：项目根目录下的 ecdict.csv
输出：instance/ecdict.db

表结构（和 ECDICT 的 CSV 字段一一对应）：
    word        单词
    phonetic    音标
    definition  英文释义
    translation 中文释义
    pos         词性
    collins     柯林斯星级
    oxford      是否牛津3000核心词
    tag         考试标签（zk/gk/cet4/cet6/ky/toefl/ielts 等）
    bnc         英国国家语料库词频
    frq         当代语料库词频
    exchange    词形变化
    detail      扩展信息（JSON）
    audio       音频URL

关于"后期导入新词典"：
    词典库（ecdict.db）和用户生词库（words.db）是两个完全独立的 SQLite 文件。
    以后想换词典，只需：
      1. 准备新的词典数据（CSV 或其他格式）
      2. 改这个脚本（或写新脚本）导入成新的 ecdict.db
      3. 替换 instance/ecdict.db
    用户的生词本数据（words.db）不受任何影响。
"""

import csv
import os
import sqlite3
import sys

# 项目根目录 = 本脚本所在目录的上一级
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 输入：ECDICT 的 CSV 文件
CSV_PATH = os.path.join(PROJECT_ROOT, "ecdict.csv")
# 输出：SQLite 词典数据库
DB_PATH = os.path.join(PROJECT_ROOT, "instance", "ecdict.db")


def main():
    # 1. 检查 CSV 文件是否存在
    if not os.path.exists(CSV_PATH):
        print(f"[错误] 找不到 {CSV_PATH}")
        print("请先把 ECDICT 的 ecdict.csv 放到项目根目录。")
        print("下载地址：https://github.com/skywind3000/ECDICT")
        sys.exit(1)

    # 2. 确保 instance 目录存在
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    # 3. 如果旧的 ecdict.db 存在，先删掉（重建）
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"[信息] 已删除旧的 {DB_PATH}")

    # 4. 连接数据库（不存在会自动创建）
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 5. 建表
    # 字段和 ECDICT 的 CSV 一一对应，全部用 TEXT 存储（CSV 里本来都是字符串）
    # word 字段加 UNIQUE 约束，防止重复导入
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stardict (
            word        TEXT PRIMARY KEY,
            phonetic    TEXT,
            definition  TEXT,
            translation TEXT,
            pos         TEXT,
            collins     TEXT,
            oxford      TEXT,
            tag         TEXT,
            bnc         TEXT,
            frq         TEXT,
            exchange    TEXT,
            detail      TEXT,
            audio       TEXT
        )
    """)

    # 6. 读取 CSV 并批量导入
    # csv.DictReader 会把每一行读成字典，键就是表头（word, phonetic, ...）
    print(f"[信息] 正在读取 {CSV_PATH} 并导入数据库...")
    count = 0
    batch = []          # 批量插入的缓存，攒够一批再写一次，速度快
    BATCH_SIZE = 1000   # 每 1000 条写一次

    with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 把每行数据整理成元组，顺序要和 INSERT 里的列顺序一致
            batch.append((
                row.get("word", ""),
                row.get("phonetic", ""),
                row.get("definition", ""),
                row.get("translation", ""),
                row.get("pos", ""),
                row.get("collins", ""),
                row.get("oxford", ""),
                row.get("tag", ""),
                row.get("bnc", ""),
                row.get("frq", ""),
                row.get("exchange", ""),
                row.get("detail", ""),
                row.get("audio", ""),
            ))
            count += 1

            # 攒够一批就写入数据库
            if len(batch) >= BATCH_SIZE:
                cur.executemany(
                    "INSERT OR REPLACE INTO stardict "
                    "(word, phonetic, definition, translation, pos, collins, "
                    "oxford, tag, bnc, frq, exchange, detail, audio) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
                batch = []

                # 每 1 万条打印一次进度
                if count % 10000 == 0:
                    print(f"  已导入 {count} 条...")

    # 把最后剩下的不足一批的数据也写进去
    if batch:
        cur.executemany(
            "INSERT OR REPLACE INTO stardict "
            "(word, phonetic, definition, translation, pos, collins, "
            "oxford, tag, bnc, frq, exchange, detail, audio) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            batch,
        )

    # 7. 给 word 字段建索引（虽然 PRIMARY KEY 已经自带索引，但显式建一个更稳妥）
    #    实际上 PRIMARY KEY 已经有索引了，这里再建一个 LOWER(word) 的索引用于大小写不敏感查询
    cur.execute("CREATE INDEX IF NOT EXISTS idx_word_lower ON stardict (LOWER(word))")

    conn.commit()
    conn.close()

    print(f"[完成] 共导入 {count} 条词条到 {DB_PATH}")
    print(f"[完成] 词典数据库大小：{os.path.getsize(DB_PATH) / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
