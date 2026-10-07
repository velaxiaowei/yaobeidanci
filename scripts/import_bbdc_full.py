# -*- coding: utf-8 -*-
"""导入"不背单词"App 导出的生词本 PDF 到本地生词本。

步骤：
1. 用 requests 下载 PDF
2. 用 pypdf 提取所有页面的文本
3. 解析每行（| 序号 | Word |  | 序号 |  | Meaning |）
4. 批量导入 words 表 + reviews 表

用法:
    python scripts/import_bbdc_full.py [用户名]
"""
import sys
import re
import sqlite3
import requests
from pypdf import PdfReader

# ---------- 配置 ----------
PDF_URL = "https://static.beingfine.cn/pdf/bbdc_99883343_20261006205713.pdf"
PDF_PATH = "instance/bbdc.pdf"
DB_PATH = "instance/words.db"
username = sys.argv[1] if len(sys.argv) > 1 else "wmy"

# ---------- 1. 下载 PDF ----------
print("下载 PDF ...")
# 加上浏览器 User-Agent，避免被服务器 403
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": "https://www.beingfine.cn/",
}
resp = requests.get(PDF_URL, headers=headers, timeout=60)
resp.raise_for_status()
with open(PDF_PATH, "wb") as f:
    f.write(resp.content)
print(f"下载完成，大小 {len(resp.content)} 字节")

# ---------- 2. 提取所有页面文本 ----------
print("提取文本 ...")
reader = PdfReader(PDF_PATH)
all_lines = []
for i, page in enumerate(reader.pages):
    text = page.extract_text()
    if text:
        all_lines.extend(text.split("\n"))
print(f"共 {len(reader.pages)} 页，{len(all_lines)} 行文本")

# 保存一份原始文本方便排查
with open("instance/bbdc_full_raw.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(all_lines))

# ---------- 3. 解析每行 ----------
# pypdf 提取的文本格式可能和 WebFetch 不同，需要适配。
# 先看看前几行长什么样
print("\n前 10 行:")
for line in all_lines[:10]:
    print(repr(line))

# pypdf 提取的文本结构：每页分两半
#   上半：Word Meaning 标题 + 序号 单词 列表
#   下半：Word Meaning 标题 + 序号 释义 列表（释义可能跨多行）
# 所以要分别收集 "序号→单词" 和 "序号→释义"，最后按序号配对。
words_dict = {}      # {序号: 单词}
meanings_dict = {}   # {序号: 释义}
current_section = None  # "word" 或 "meaning"
last_meaning_num = None  # 用于释义跨行续接

for line in all_lines:
    line = line.strip()
    if not line:
        continue

    # 遇到 "Word Meaning" 切换收集方向
    # 第一次遇到 → 开始收集单词；第二次 → 开始收集释义
    if line == "Word Meaning":
        if current_section == "word":
            current_section = "meaning"
        elif current_section == "meaning":
            # 又遇到 Word Meaning 但已经在收集释义了 → 新的一页开始
            current_section = "word"
        else:
            current_section = "word"
        last_meaning_num = None
        continue

    # 跳过页脚/页眉
    if line.startswith("⽣词本") or line.startswith("扫码") or line.startswith("纸上") \
       or line.startswith("共") or line.startswith("不背单词"):
        continue

    # 匹配 "序号 内容"
    m = re.match(r"^(\d+)\s+(.+)$", line)
    if m:
        num = int(m.group(1))
        content = m.group(2).strip()
        if current_section == "word":
            words_dict[num] = content
        elif current_section == "meaning":
            meanings_dict[num] = content
            last_meaning_num = num
    else:
        # 不以数字开头 → 释义的续行，追加到上一条释义
        if current_section == "meaning" and last_meaning_num is not None:
            meanings_dict[last_meaning_num] += " " + line

# 按序号配对
words = []
for num in sorted(words_dict.keys()):
    word = words_dict[num]
    meaning = meanings_dict.get(num, "")
    if word and meaning:
        words.append((word, meaning))

print(f"\n解析到 {len(words)} 个单词")
for w, m in words[:5]:
    print(f"  {w:20} → {m[:50]}")
print("...")
for w, m in words[-3:]:
    print(f"  {w:20} → {m[:50]}")

# ---------- 4. 导入数据库 ----------
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
user = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
if not user:
    print(f"错误：用户 '{username}' 不存在")
    sys.exit(1)
user_id = user["id"]
print(f"\n导入到用户: {username} (id={user_id})")

inserted = 0
skipped = 0
for word, meaning in words:
    try:
        cursor = conn.execute(
            "INSERT INTO words (user_id, word, meaning) VALUES (?, ?, ?)",
            (user_id, word, meaning),
        )
        conn.execute(
            "INSERT INTO reviews (user_id, word_id) VALUES (?, ?)",
            (user_id, cursor.lastrowid),
        )
        inserted += 1
    except sqlite3.IntegrityError:
        skipped += 1

conn.commit()
total = conn.execute(
    "SELECT COUNT(*) FROM words WHERE user_id = ?", (user_id,)
).fetchone()[0]
print(f"\n导入完成！新增 {inserted}，跳过（已存在）{skipped}，当前总数 {total}")
conn.close()
