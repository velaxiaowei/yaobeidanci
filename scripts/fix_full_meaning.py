"""修复 words.meaning 字段：之前只存了释义第一行，现在补全为完整释义。

从 ECDICT 词典重新查每个单词的完整 translation，更新到 words.meaning。
"""
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORDS_DB = os.path.join(BASE_DIR, "instance", "words.db")
ECDICT_DB = os.path.join(BASE_DIR, "instance", "ecdict.db")


def main():
    words_conn = sqlite3.connect(WORDS_DB)
    words_conn.row_factory = sqlite3.Row
    dict_conn = sqlite3.connect(ECDICT_DB)
    dict_conn.row_factory = sqlite3.Row

    words = words_conn.execute("SELECT id, word, meaning FROM words").fetchall()
    updated = 0
    skipped = 0

    for w in words:
        row = dict_conn.execute(
            "SELECT translation, definition FROM stardict WHERE word = ?",
            (w["word"],),
        ).fetchone()
        if row is None:
            skipped += 1
            continue
        full_meaning = (row["translation"] or row["definition"] or w["word"]).strip()
        if full_meaning and full_meaning != w["meaning"]:
            words_conn.execute(
                "UPDATE words SET meaning = ? WHERE id = ?",
                (full_meaning, w["id"]),
            )
            updated += 1

    words_conn.commit()
    print(f"完成：更新 {updated} 个单词的释义，跳过 {skipped} 个（词典未收录）")


if __name__ == "__main__":
    main()
