# -*- coding: utf-8 -*-
"""迁移脚本：给 user_settings 表加发音相关字段。
- default_accent：默认发音，'en'=英音，'us'=美音
- auto_pronounce：是否自动朗读，0=否 1=是
不删除任何现有数据，已有用户默认英音、关闭自动朗读。
"""
import sqlite3

conn = sqlite3.connect("instance/words.db")

# 加字段（IF NOT EXISTS 需要 SQLite 3.35+，用 try 兼容旧版本）
try:
    conn.execute("ALTER TABLE user_settings ADD COLUMN default_accent TEXT NOT NULL DEFAULT 'en'")
    print("已加字段 default_accent")
except sqlite3.OperationalError:
    print("字段 default_accent 已存在，跳过")

try:
    conn.execute("ALTER TABLE user_settings ADD COLUMN auto_pronounce INTEGER NOT NULL DEFAULT 0")
    print("已加字段 auto_pronounce")
except sqlite3.OperationalError:
    print("字段 auto_pronounce 已存在，跳过")

conn.commit()

# 验证
rows = conn.execute(
    "SELECT u.username, s.default_accent, s.auto_pronounce "
    "FROM user_settings s JOIN users u ON s.user_id = u.id"
).fetchall()
print("\n用户发音设置：")
for r in rows:
    accent = "英音" if r[1] == "en" else "美音"
    auto = "开" if r[2] else "关"
    print(f"  {r[0]:15} 默认发音={accent}  自动朗读={auto}")

conn.close()
