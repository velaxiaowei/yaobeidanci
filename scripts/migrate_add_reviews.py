# -*- coding: utf-8 -*-
"""迁移脚本：给现有数据库加 reviews 表（复习进度）。
不删除任何现有数据。给已有的生词自动插入初始复习记录。"""
import sqlite3
from datetime import datetime

conn = sqlite3.connect("instance/words.db")
conn.execute("PRAGMA foreign_keys = ON")

# 1. 建 reviews 表
conn.execute("""
CREATE TABLE IF NOT EXISTS reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    word_id      INTEGER NOT NULL UNIQUE,
    ef           REAL    NOT NULL DEFAULT 2.5,
    rep          INTEGER NOT NULL DEFAULT 0,
    interval     INTEGER NOT NULL DEFAULT 0,
    last_review  TIMESTAMP,
    next_review  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE
)
""")

# 2. 给已存在的生词自动补复习记录
#    选出所有还没有 reviews 行的 words，给它们各插一条初始记录
orphan_words = conn.execute(
    "SELECT id, user_id FROM words WHERE id NOT IN (SELECT word_id FROM reviews)"
).fetchall()
for w in orphan_words:
    conn.execute(
        "INSERT INTO reviews (user_id, word_id) VALUES (?, ?)",
        (w["user_id"], w["id"]) if isinstance(w, sqlite3.Row) else (w[1], w[0]),
    )

conn.commit()

# 3. 验证
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
review_count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
word_count = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]

print(f"当前表: {tables}")
print(f"reviews 表已创建" if "reviews" in tables else "reviews 表创建失败")
print(f"生词总数: {word_count} 条")
print(f"复习记录数: {review_count} 条")
print(f"全部生词都有复习记录:", review_count == word_count)

conn.close()
