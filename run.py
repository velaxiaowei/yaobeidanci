# -*- coding: utf-8 -*-
"""启动脚本：启动 Flask 服务器并自动打开浏览器。

用法：双击 run.bat 或在终端运行 python run.py
"""
import os
import sys
import webbrowser
import threading
import time


def open_browser():
    """等服务器启动后自动打开浏览器。"""
    time.sleep(2)  # 等 Flask 起来
    webbrowser.open("http://127.0.0.1:5000")


def main():
    # 确保在项目根目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    # 把项目根目录加到 Python 路径
    sys.path.insert(0, base_dir)

    # 自动打开浏览器（后台线程，不阻塞）
    threading.Thread(target=open_browser, daemon=True).start()

    # 启动 Flask
    print("=" * 50)
    print("  要背单词 - 服务器启动中...")
    print("  网址：http://127.0.0.1:5000")
    print("  按 Ctrl+C 停止")
    print("=" * 50)

    from app import create_app

    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)


if __name__ == "__main__":
    main()
