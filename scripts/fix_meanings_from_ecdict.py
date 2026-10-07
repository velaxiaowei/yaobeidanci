# -*- coding: utf-8 -*-
"""用 ECDICT 本地词典的干净释义覆盖 words 表里弄脏的 meaning 字段。

不调用在线 API，只查本地 ecdict.db 的 translation 字段，速度快。
"""
import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

app = create_app()

with app.app_context():
    # 打开两个数据库：用户库 words.db + 词典库 ecdict.db
    words_db = sqlite3.connect("instance/words.db")
    words_db.row_factory = sqlite3.Row
    dict_db = sqlite3.connect(os.path.join(app.instance_path, "ecdict.db"))
    dict_db.row_factory = sqlite3.Row

    rows = words_db.execute(
        "SELECT id, word, meaning FROM words WHERE user_id = 1"
    ).fetchall()

    updated = 0
    not_found = 0
    for r in rows:
        row = dict_db.execute(
            "SELECT translation FROM stardict WHERE LOWER(word) = LOWER(?)",
            (r["word"],),
        ).fetchone()
        if row and row["translation"]:
            new_meaning = row["translation"].strip()
            if new_meaning and new_meaning != r["meaning"]:
                words_db.execute(
                    "UPDATE words SET meaning = ? WHERE id = ?",
                    (new_meaning, r["id"]),
                )
                updated += 1
        else:
            not_found += 1

    words_db.commit()
    words_db.close()
    dict_db.close()
    print(f"总词数: {len(rows)}, 已更新释义: {updated}, 词典未找到: {not_found}")
