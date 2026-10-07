"""给 users 表加 phone 字段（手机号），用于短信验证码找回密码。"""
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "instance", "words.db")


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        print("已添加 phone 字段")
    except sqlite3.OperationalError:
        print("phone 字段已存在，跳过")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
