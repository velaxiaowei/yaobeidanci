# 我的背单词

基于 Flask + SQLite + ECDICT 的背单词 Web 应用，灵感来自"不背单词"。

## 功能

- **用户认证**：注册、登录、登出
- **找回密码**：手机号绑定 + 短信验证码重置密码
- **查词**：基于 ECDICT 离线词典，支持英文释义、中文翻译、音标
- **生词本**：查词后一键加入生词本，支持例句和笔记
- **SM-2 复习**：科学记忆曲线，判断轮 → 四选一 → 回想轮 → 释义页
- **拼写巩固**：看中文拼英文，错题重做
- **发音**：有道词典 API，英音/美音切换，自动朗读
- **AI 问答**：基于 DeepSeek API，不懂就问

## 技术栈

- Python 3.10+ / Flask
- SQLite（ECDICT 词典 + 用户数据）
- Jinja2 模板
- 原生 HTML/CSS/JS（无前端框架）

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/你的用户名/背单词.git
cd 背单词
```

### 2. 创建虚拟环境

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key（必填，用于 AI 问答）
```

### 5. 下载数据库

ECDICT 词典数据库需要单独下载：

```bash
python scripts/download_ecdict.py
```

### 6. 初始化数据库

```bash
python scripts/import_ecdict.py
flask --app app init-db
```

### 7. 运行

```bash
# 方式1：双击 run.bat（Windows）
# 方式2：命令行
python run.py
# 或
flask --app app run --host 0.0.0.0 --port 5000
```

打开浏览器访问 http://127.0.0.1:5000

## 数据来源

- [ECDICT](https://github.com/skywind3000/ECDICT) - 英汉词典数据库
- [有道词典 API](https://dict.youdao.com) - 单词发音
- [DeepSeek API](https://platform.deepseek.com/) - AI 问答

## 许可

MIT
