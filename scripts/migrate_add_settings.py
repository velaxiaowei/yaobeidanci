# -*- coding: utf-8 -*-
"""迁移脚本：给现有数据库加 user_settings 表（用户学习偏好设置）。
不删除任何现有数据。给已有的用户自动插入默认设置。"""
import sqlite3

conn = sqlite3.connect("instance/words.db")

# 1. 建 user_settings 表
conn.execute("""
CREATE TABLE IF NOT EXISTS user_settings (
    user_id          INTEGER PRIMARY KEY,
    daily_count      INTEGER NOT NULL DEFAULT 20,     -- 每次复习的单词数
    spelling_enabled INTEGER NOT NULL DEFAULT 0,      -- 是否启用拼写巩固（0=否 1=是）
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
)
""")

# 2. 给已存在的用户补默认设置
existing = conn.execute(
    "SELECT id FROM users WHERE id NOT IN (SELECT user_id FROM user_settings)"
).fetchall()
for u in existing:
    conn.execute(
        "INSERT INTO user_settings (user_id) VALUES (?)", (u[0],)
    )

conn.commit()

# 3. 验证
rows = conn.execute(
    "SELECT u.username, s.daily_count, s.spelling_enabled "
    "FROM user_settings s JOIN users u ON s.user_id = u.id"
).fetchall()
print("用户设置：")
for r in rows:
    print(f"  {r[0]:15} 每日复习数={r[1]}  拼写巩固={'开' if r[2] else '关'}")

conn.close()
