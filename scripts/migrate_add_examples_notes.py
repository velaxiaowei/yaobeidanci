# -*- coding: utf-8 -*-
"""迁移脚本：给现有数据库加 examples 和 notes 两张表。
不删除任何现有数据。"""
import sqlite3

conn = sqlite3.connect("instance/words.db")

conn.execute("""
CREATE TABLE IF NOT EXISTS examples (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    word_id    INTEGER NOT NULL,
    sentence   TEXT    NOT NULL,
    source     TEXT    NOT NULL DEFAULT 'manual',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, word_id, sentence),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE
)
""")

conn.execute("""
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    word_id    INTEGER NOT NULL,
    content    TEXT    NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE
)
""")

conn.commit()

# 验证
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("当前表:", tables)
print("examples 和 notes 已创建" if "examples" in tables and "notes" in tables else "创建失败")
conn.close()
