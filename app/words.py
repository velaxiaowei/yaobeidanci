# -*- coding: utf-8 -*-
"""生词本模块（蓝图）。

负责：
    1. 搜索单词释义（调用 ECDICT 本地词典）
    2. 一键加入生词本 / 取消加入
    3. 查看自己的生词列表
    4. 删除生词

核心流程（模仿"不背单词"）：
    搜索框输入单词 → 查到释义 → 点"加入生词本"按钮 → 写入 words 表
    已加入的单词按钮显示"已加入 √"，再点一次取消加入。
"""

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
)

from .auth import login_required  # 登录拦截装饰器
from .db import get_db            # 用户数据库（words 表）
from .dictionary import lookup    # 词典查询（ECDICT）
from .llm import chat             # 大模型对话（DeepSeek）

bp = Blueprint("words", __name__)


# ==================== 生词本列表页 ====================

@bp.route("/")
@login_required
def index():
    """显示当前用户的全部生词。"""
    db = get_db()
    # 查当前登录用户（g.user['id']）的所有生词，按加入时间倒序（最新的在前）
    words = db.execute(
        "SELECT * FROM words WHERE user_id = ? ORDER BY created_at DESC",
        (g.user["id"],),
    ).fetchall()

    return render_template("words/index.html", words=words)


# ==================== 搜索单词 ====================

@bp.route("/search")
@login_required
def search():
    """搜索单词释义。

    两种用法：
      1. 直接访问 /words/search        → 只显示搜索框
      2. 访问 /words/search?q=abandon  → 显示搜索框 + abandon 的释义
    """
    q = request.args.get("q", "").strip()   # 从 URL 取搜索词
    result = None                            # 查词结果
    in_wordbook = False                      # 这个词是否已在当前用户的生词本里

    word_row = None  # words表里的记录（含id），后面查例句和笔记要用
    examples = []    # 该词已保存的例句
    notes = []       # 该词的笔记

    if q:
        # 去 ECDICT 词典库里查
        result = lookup(q)

        if result is None:
            flash(f"词典里没找到 '{q}'，检查一下拼写？")
        else:
            # 查到了，再查一下当前用户有没有把这个词加入生词本
            db = get_db()
            word_row = db.execute(
                "SELECT id FROM words WHERE user_id = ? AND LOWER(word) = LOWER(?)",
                (g.user["id"], q),
            ).fetchone()
            in_wordbook = word_row is not None  # 有记录 = 已加入

            # 如果已加入生词本，查出该词的例句和笔记，显示在页面上
            if in_wordbook:
                examples = db.execute(
                    "SELECT * FROM examples WHERE user_id = ? AND word_id = ? ORDER BY created_at DESC",
                    (g.user["id"], word_row["id"]),
                ).fetchall()
                notes = db.execute(
                    "SELECT * FROM notes WHERE user_id = ? AND word_id = ? ORDER BY created_at DESC",
                    (g.user["id"], word_row["id"]),
                ).fetchall()

    return render_template(
        "words/search.html",
        q=q,
        result=result,
        in_wordbook=in_wordbook,
        word_id=word_row["id"] if word_row else None,
        examples=examples,
        notes=notes,
    )


# ==================== 加入生词本 ====================

@bp.route("/add", methods=("POST",))
@login_required
def add():
    """把一个单词加入生词本。

    接收 POST 表单，字段 word（英文单词）。
    中文释义从 ECDICT 词典里自动取，不用用户手填。

    设计：
      - 如果词典里查不到这个词 → 拒绝加入（防止加一些乱七八糟的词）
      - 如果已经在生词本里 → 提示"已存在"，不重复加（数据库 UNIQUE 约束也会兜底）
      - 正常 → 写入 words 表，关联当前用户
    """
    word = request.form.get("word", "").strip()

    if not word:
        flash("请输入要加入的单词")
        return redirect(url_for("words.search"))

    # 1. 先去词典查这个词的释义
    dict_result = lookup(word)
    if dict_result is None:
        flash(f"词典里找不到 '{word}'，无法加入生词本")
        return redirect(url_for("words.search", q=word))

    # 2. 取中文释义（translation 字段）。如果为空，用英文释义兜底
    #    存完整释义（多个词性分行），显示时由 parse_translation 解析
    meaning = (dict_result["translation"] or dict_result["definition"] or word).strip()

    # 3. 写入数据库
    db = get_db()
    try:
        # 3.1 先插入 words 表（拿到自增 id）
        cursor = db.execute(
            "INSERT INTO words (user_id, word, meaning) VALUES (?, ?, ?)",
            (g.user["id"], dict_result["word"], meaning),
        )
        new_word_id = cursor.lastrowid  # 刚插入的那条词的 id

        # 3.2 同时插入 reviews 表一条初始复习记录
        #     ef=2.5, rep=0, interval=0, next_review=now（默认值都是 SM-2 算法的初始状态）
        #     这样新加的词立刻进入"待复习"队列
        db.execute(
            "INSERT INTO reviews (user_id, word_id) VALUES (?, ?)",
            (g.user["id"], new_word_id),
        )
        db.commit()
        flash(f"已加入生词本：{dict_result['word']}")
    except db.IntegrityError:
        # UNIQUE(user_id, word) 约束触发 → 说明已经加过了
        flash(f"'{dict_result['word']}' 已经在你的生词本里了")

    # 加完回到搜索页，还能看到这个词的释义和按钮状态
    return redirect(url_for("words.search", q=word))


# ==================== 从生词本删除 ====================

@bp.route("/remove/<word>", methods=("POST",))
@login_required
def remove(word):
    """把一个单词从生词本移除。

    注意：只能删自己的词，所以 WHERE 条件里带 user_id。
    """
    db = get_db()
    db.execute(
        "DELETE FROM words WHERE user_id = ? AND LOWER(word) = LOWER(?)",
        (g.user["id"], word),
    )
    db.commit()
    flash(f"已从生词本移除：{word}")

    # 从哪来回哪去：如果带了 next 参数就回 next，否则回搜索页
    next_url = request.args.get("next") or url_for("words.search", q=word)
    return redirect(next_url)


# ==================== 删除生词（从列表页）====================

@bp.route("/delete/<int:word_id>", methods=("POST",))
@login_required
def delete(word_id):
    """从生词列表页删除某个生词（按 id 删）。"""
    db = get_db()
    # 先确认这条词确实属于当前用户（防止别人通过改 id 删你的词）
    word = db.execute(
        "SELECT word FROM words WHERE id = ? AND user_id = ?",
        (word_id, g.user["id"]),
    ).fetchone()

    if word is None:
        flash("找不到这个词，或它不属于你")
    else:
        db.execute("DELETE FROM words WHERE id = ?", (word_id,))
        db.commit()
        flash(f"已删除：{word['word']}")

    return redirect(url_for("words.index"))


# ==================== 保存例句 ====================

@bp.route("/save-example", methods=("POST",))
@login_required
def save_example():
    """把选中的文本保存为例句。

    接收 POST JSON：{"word_id": 123, "sentence": "选中的文本", "source": "ai"}
    source: dictionary（词典例句）/ ai（AI生成）/ manual（手动）
    """
    data = request.get_json(silent=True) or {}
    word_id = data.get("word_id")
    sentence = (data.get("sentence") or "").strip()
    source = data.get("source", "manual")

    if not word_id or not sentence:
        return jsonify({"ok": False, "msg": "缺少 word_id 或 sentence"}), 400

    db = get_db()
    # 确认这个词属于当前用户
    word = db.execute(
        "SELECT id FROM words WHERE id = ? AND user_id = ?",
        (word_id, g.user["id"]),
    ).fetchone()
    if word is None:
        return jsonify({"ok": False, "msg": "该词不在你的生词本里"}), 403

    try:
        db.execute(
            "INSERT INTO examples (user_id, word_id, sentence, source) VALUES (?, ?, ?, ?)",
            (g.user["id"], word_id, sentence, source),
        )
        db.commit()
        return jsonify({"ok": True, "msg": "已保存到例句库"})
    except db.IntegrityError:
        return jsonify({"ok": False, "msg": "这条例句已经保存过了"})


# ==================== 删除例句 ====================

@bp.route("/delete-example/<int:example_id>", methods=("POST",))
@login_required
def delete_example(example_id):
    db = get_db()
    db.execute(
        "DELETE FROM examples WHERE id = ? AND user_id = ?",
        (example_id, g.user["id"]),
    )
    db.commit()
    return redirect(request.referrer or url_for("words.examples"))


# ==================== 保存笔记 ====================

@bp.route("/save-note", methods=("POST",))
@login_required
def save_note():
    """给某个词添加一条笔记。

    接收 POST JSON：{"word_id": 123, "content": "笔记内容"}
    """
    data = request.get_json(silent=True) or {}
    word_id = data.get("word_id")
    content = (data.get("content") or "").strip()

    if not word_id or not content:
        return jsonify({"ok": False, "msg": "缺少 word_id 或 content"}), 400

    db = get_db()
    word = db.execute(
        "SELECT id FROM words WHERE id = ? AND user_id = ?",
        (word_id, g.user["id"]),
    ).fetchone()
    if word is None:
        return jsonify({"ok": False, "msg": "该词不在你的生词本里"}), 403

    db.execute(
        "INSERT INTO notes (user_id, word_id, content) VALUES (?, ?, ?)",
        (g.user["id"], word_id, content),
    )
    db.commit()
    return jsonify({"ok": True, "msg": "笔记已保存"})


# ==================== 删除笔记 ====================

@bp.route("/delete-note/<int:note_id>", methods=("POST",))
@login_required
def delete_note(note_id):
    db = get_db()
    db.execute(
        "DELETE FROM notes WHERE id = ? AND user_id = ?",
        (note_id, g.user["id"]),
    )
    db.commit()
    return redirect(request.referrer or url_for("words.index"))


# ==================== 例句库（素材库）====================

@bp.route("/examples")
@login_required
def examples():
    """浏览当前用户保存的所有例句（按词分组或全部列出）。"""
    db = get_db()
    # JOIN words 表，拿到例句对应的单词
    rows = db.execute(
        "SELECT e.*, w.word FROM examples e "
        "JOIN words w ON e.word_id = w.id "
        "WHERE e.user_id = ? ORDER BY e.created_at DESC",
        (g.user["id"],),
    ).fetchall()
    return render_template("words/examples.html", examples=rows)


# ==================== 笔记库 ====================

@bp.route("/notes")
@login_required
def notes():
    """浏览当前用户保存的所有笔记（JOIN words 表显示来源单词）。

    样式仿例句库：每条笔记显示来源单词（点击可跳到查词页）、笔记内容、删除按钮。
    """
    db = get_db()
    # JOIN words 表，拿到笔记对应的单词（如果词被删了，外键约束会级联删除笔记，
    # 所以这里用 INNER JOIN 没问题；如果想保留孤儿笔记可换成 LEFT JOIN）
    rows = db.execute(
        "SELECT n.*, w.word FROM notes n "
        "JOIN words w ON n.word_id = w.id "
        "WHERE n.user_id = ? ORDER BY n.created_at DESC",
        (g.user["id"],),
    ).fetchall()
    return render_template("words/notes.html", notes=rows)


# ==================== 智能问答（大模型）====================

@bp.route("/ask", methods=("POST",))
@login_required
def ask():
    """向大模型提问关于某个单词的问题。

    接收 POST JSON：{"word": "abandon", "question": "这个词能用来表白吗"}
    返回 JSON：{"answer": "大模型的回答..."}

    设计：
      - 前端用 fetch 发请求，不刷新页面
      - 后端把当前单词的释义作为上下文传给大模型，回答更准
      - 大模型 API 失败时返回错误提示，不影响页面
    """
    data = request.get_json(silent=True) or {}
    word = (data.get("word") or "").strip()
    question = (data.get("question") or "").strip()

    if not word or not question:
        return jsonify({"answer": "请输入单词和问题。"}), 400

    # 查一下这个词的释义，作为上下文传给大模型
    word_info = lookup(word)

    # 调大模型
    answer = chat(word, word_info, question)

    return jsonify({"answer": answer})


# ==================== 占位路由（验证用，可删）====================

@bp.route("/hello")
@login_required
def hello():
    return "生词本模块座位已就位：加词 / 删词 / 划词查词 / 导出 将来写在这里。"
