# -*- coding: utf-8 -*-
"""导入"不背单词"App 导出的生词本 PDF 文本到本地生词本。

用法:
    python scripts/import_bbdc.py [用户名]
    不传用户名时默认导入到 wmy

前提:
    1. 用 WebFetch 把 PDF 转成文本，保存为 instance/bbdc_raw.txt
       （或直接把 PDF 文本内容粘贴进去）
    2. 文本格式：| 序号 | Word |  | 序号 |  | Meaning |
"""
import sys
import re
import sqlite3

# 默认导入到 wmy；命令行第一个参数可指定其他用户名
username = sys.argv[1] if len(sys.argv) > 1 else "wmy"

raw_path = "instance/bbdc_raw.txt"
db_path = "instance/words.db"

# ---------- 1. 读取 PDF 文本 ----------
with open(raw_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# ---------- 2. 解析每行，提取 (word, meaning) ----------
# 行格式：| 1 | resilience |  | 1 |  | n. 恢复力... |
# 按 | 分割后：['', ' 1 ', ' resilience ', '  ', ' 1 ', '  ', ' n. 恢复力... ', '']
# 索引 2 = word，索引 6 = meaning
words = []
for line in lines:
    parts = line.split("|")
    # 有效的数据行必须至少有 7 列（首尾空 + 6 列内容）
    if len(parts) < 7:
        continue
    # 第一列必须是数字（序号），否则跳过表头/页脚
    if not parts[1].strip().isdigit():
        continue
    word = parts[2].strip()
    meaning = parts[6].strip()
    if word and meaning:
        words.append((word, meaning))

print(f"解析到 {len(words)} 个单词")
# 打印前 5 个确认格式正确
for w, m in words[:5]:
    print(f"  {w:20} → {m[:40]}")

# ---------- 3. 连接数据库，找用户 ----------
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
user = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
if not user:
    print(f"错误：用户 '{username}' 不存在")
    sys.exit(1)
user_id = user["id"]
print(f"导入到用户: {username} (id={user_id})")

# ---------- 4. 批量插入 words + reviews ----------
inserted = 0
skipped = 0
for word, meaning in words:
    try:
        cursor = conn.execute(
            "INSERT INTO words (user_id, word, meaning) VALUES (?, ?, ?)",
            (user_id, word, meaning),
        )
        new_word_id = cursor.lastrowid
        # 同时建一条复习记录（默认立即待复习）
        conn.execute(
            "INSERT INTO reviews (user_id, word_id) VALUES (?, ?)",
            (user_id, new_word_id),
        )
        inserted += 1
    except sqlite3.IntegrityError:
        # UNIQUE(user_id, word) 约束 → 已经加过了，跳过
        skipped += 1

conn.commit()

# ---------- 5. 统计 ----------
total = conn.execute(
    "SELECT COUNT(*) FROM words WHERE user_id = ?", (user_id,)
).fetchone()[0]
print(f"\n导入完成！")
print(f"  新增: {inserted} 个")
print(f"  跳过（已存在）: {skipped} 个")
print(f"  当前生词总数: {total} 个")

conn.close()
