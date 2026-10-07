# -*- coding: utf-8 -*-
"""下载 ECDICT 的 ecdict.csv。

尝试多个镜像源，哪个能下用哪个。
"""
import os
import sys
import time
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(PROJECT_ROOT, "ecdict.csv")

# 候选下载源（按优先级）
URLS = [
    # GitHub 直连
    "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv",
    # ghproxy 加速
    "https://ghproxy.com/https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv",
    # gh-proxy 加速
    "https://gh-proxy.com/https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv",
    # 99988866 加速
    "https://gh.api.99988866.xyz/https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv",
    # moeyy 加速
    "https://github.moeyy.xyz/https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv",
]


def download(url, timeout=30):
    """下载文件，带进度显示。"""
    print(f"[尝试] {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            block_size = 64 * 1024  # 64KB
            last_print = time.time()

            with open(OUTPUT, "wb") as f:
                while True:
                    chunk = resp.read(block_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    # 每秒打印一次进度
                    now = time.time()
                    if now - last_print >= 1:
                        mb = downloaded / 1024 / 1024
                        if total:
                            pct = downloaded / total * 100
                            print(f"  已下载 {mb:.1f} MB ({pct:.1f}%)")
                        else:
                            print(f"  已下载 {mb:.1f} MB")
                        last_print = now

            mb = downloaded / 1024 / 1024
            print(f"[完成] 下载成功，共 {mb:.1f} MB")
            return True
    except Exception as e:
        print(f"[失败] {e}")
        return False


def main():
    # 如果已有部分下载的文件，先删掉
    if os.path.exists(OUTPUT):
        os.remove(OUTPUT)

    for url in URLS:
        if download(url):
            # 验证文件非空
            if os.path.getsize(OUTPUT) > 1024 * 1024:  # 至少 1MB
                print(f"[成功] 文件保存在 {OUTPUT}")
                return
            else:
                print("[警告] 文件太小，可能下载不完整，尝试下一个源")
                os.remove(OUTPUT)

    print("[失败] 所有下载源都失败了")
    sys.exit(1)


if __name__ == "__main__":
    main()
