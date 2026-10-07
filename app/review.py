# -*- coding: utf-8 -*-
"""复习模块（蓝图）—— 分组多轮复习流程。

一组词的完整流程：
1. 判断轮（judge）：siege 式卡片，选 认识/模糊/忘记了
   → 每个词选完后进 onset 页看完整释义
   → 忘记了的词排到判断轮末尾重判
2. 四选一轮（multichoice）：模糊的词出 4 个中文释义，选错一直到选对
3. 回想轮（recall）：四选一对了的词，只显示中文遮住英文，判断能否想起
4. 结束页：这组词已经复习完啦 → 选择「拼写全部」/「拼写错词」/「退出」

左上角进度 = 已认识数 / 这组总数
"""

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, g, session as flask_session, jsonify
)
from datetime import datetime, timedelta
import random
import json

from .auth import login_required
from .db import get_db
from .dictionary import lookup, lookup_local, get_dict_db

bp = Blueprint("review", __name__)


# ==================== 辅助函数 ====================

def parse_translation(translation):
    """把 ECDICT 的 translation 按词性分行。

    ECDICT 里换行可能是真正的 \\n，也可能是字面量 \\n（反斜杠+n），
    这里统一替换成真正的换行符再分割。不标记高频（不确定哪个是高频义）。
    """
    if not translation:
        return []
    # 把字面量 \n 替换成真正的换行符
    translation = translation.replace("\\n", "\n")
    result = []
    for line in translation.split("\n"):
        line = line.strip()
        if not line:
            continue
        if ". " in line:
            pos, meanings = line.split(". ", 1)
            pos = pos + "."
            meaning_list = [m.strip() for m in meanings.split(",") if m.strip()]
        else:
            pos = ""
            meaning_list = [line]
        if meaning_list:
            result.append({"pos": pos, "meanings": meaning_list})
    return result


def sm2(ef, rep, interval, quality):
    """SM-2 算法：根据评分更新一个词的复习状态。"""
    delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    new_ef = ef + delta
    if new_ef < 1.3:
        new_ef = 1.3
    if quality >= 3:
        new_rep = rep + 1
        if new_rep == 1:
            new_interval = 1
        elif new_rep == 2:
            new_interval = 6
        else:
            new_interval = max(1, round(interval * new_ef))
    else:
        new_rep = 0
        new_interval = 1
    return new_ef, new_rep, new_interval


def update_review_quality(review_id, quality):
    """用 SM-2 更新一条复习记录的状态。"""
    db = get_db()
    review = db.execute(
        "SELECT ef, rep, interval FROM reviews WHERE id = ? AND user_id = ?",
        (review_id, g.user["id"]),
    ).fetchone()
    if review:
        new_ef, new_rep, new_interval = sm2(
            review["ef"], review["rep"], review["interval"], quality
        )
        next_review = datetime.utcnow() + timedelta(days=new_interval)
        db.execute(
            "UPDATE reviews SET ef = ?, rep = ?, interval = ?, "
            "last_review = ?, next_review = ? WHERE id = ?",
            (new_ef, new_rep, new_interval,
             datetime.utcnow(), next_review, review_id),
        )
        db.commit()


def extract_first_pos(translation):
    """从 ECDICT 的 translation 提取第一个词性标签，如 'n.' 'vt.' 'a.'。

    ECDICT 的 translation 格式示例：'n. 史诗, 叙事诗\\na. 史诗的, 叙事诗的'
    第一行以 'n. ' 开头，所以提取出 'n.'。
    """
    if not translation:
        return ""
    line = translation.split("\n")[0].strip()
    if ". " in line:
        return line.split(". ", 1)[0] + "."
    return ""


def get_distractors(item, exclude_word, count=3):
    """生成四选一干扰项：优先从 ECDICT 找词性相同的词（更像易混词）。

    策略：
    1. 取正确答案的第一个词性标签（如 'n.'）
    2. 从 ECDICT 里找 translation 以相同词性开头的词，随机取若干
    3. 如果不够，从用户词库随机补
    """
    dict_db = get_dict_db()
    distractors = []

    # 1. 从正确释义提取词性
    dict_info = lookup_local(item["word"])
    correct_translation = dict_info.get("translation", "") if dict_info else item["meaning"]
    pos = extract_first_pos(correct_translation)

    # 2. 从 ECDICT 找同性词（LIKE 'n.%'）
    if pos:
        like_pattern = pos + "%"
        rows = dict_db.execute(
            "SELECT translation FROM stardict "
            "WHERE translation LIKE ? AND length(translation) > 0 AND word != ? "
            "ORDER BY RANDOM() LIMIT ?",
            (like_pattern, exclude_word, count * 5),
        ).fetchall()
        for r in rows:
            t = r["translation"].strip()
            if t and t not in distractors:
                distractors.append(t)
            if len(distractors) >= count:
                break

    # 3. 不够的话从用户词库随机补
    if len(distractors) < count:
        db = get_db()
        rows = db.execute(
            "SELECT meaning FROM words WHERE user_id = ? AND word != ? "
            "ORDER BY RANDOM() LIMIT ?",
            (g.user["id"], exclude_word, count),
        ).fetchall()
        for r in rows:
            if r["meaning"] and r["meaning"] not in distractors:
                distractors.append(r["meaning"])
            if len(distractors) >= count:
                break

    return distractors[:count]


def init_review_group():
    """从待复习词里取 daily_count 个，初始化 session 里的复习组状态。"""
    db = get_db()
    now = datetime.utcnow()
    daily_count = g.settings["daily_count"] if g.settings else 20

    rows = db.execute(
        "SELECT r.id AS review_id, w.id AS word_id, w.word, w.meaning "
        "FROM reviews r JOIN words w ON r.word_id = w.id "
        "WHERE r.user_id = ? AND r.next_review <= ? "
        "ORDER BY r.next_review ASC LIMIT ?",
        (g.user["id"], now, daily_count),
    ).fetchall()

    if not rows:
        return None

    # 队列：每个元素存 review_id, word, meaning
    queue = [{"review_id": r["review_id"], "word": r["word"], "meaning": r["meaning"]}
             for r in rows]

    flask_session["review_group"] = {
        "total": len(queue),
        "known": [],        # 认识的词
        "vague": [],        # 模糊的词
        "queue": queue,     # 判断轮剩余队列
        "forgotten": [],    # 忘记了的词，排到末尾重判
        "phase": "judge",   # judge | multichoice | recall | done
        "mc_queue": [],     # 四选一队列
        "recall_queue": [], # 回想队列
        "wrong_words": [],  # 回想轮不认识的词（供拼写错词用）
    }
    flask_session.modified = True
    return True


def current_group():
    """获取当前复习组状态。"""
    return flask_session.get("review_group")


def clear_group():
    """清除复习组状态。"""
    flask_session.pop("review_group", None)
    flask_session.pop("reviewed_count", None)


# ==================== 复习入口页 ====================

@bp.route("/")
@login_required
def index():
    db = get_db()
    now = datetime.now()
    due_count = db.execute(
        "SELECT COUNT(*) FROM reviews WHERE user_id = ? AND next_review <= ?",
        (g.user["id"], now),
    ).fetchone()[0]
    total_count = db.execute(
        "SELECT COUNT(*) FROM words WHERE user_id = ?", (g.user["id"],)
    ).fetchone()[0]
    mastered_count = db.execute(
        "SELECT COUNT(*) FROM reviews WHERE user_id = ? AND rep >= 5",
        (g.user["id"],)
    ).fetchone()[0]
    return render_template(
        "review/index.html",
        due_count=due_count,
        total_count=total_count,
        mastered_count=mastered_count,
    )


# ==================== 判断轮（siege 式卡片）====================

@bp.route("/session", methods=("GET", "POST"))
@login_required
def session():
    """判断轮：一张一张过卡片，选 认识/模糊/忘记了。"""
    group = current_group()

    # 如果没有进行中的组，初始化一组
    if group is None:
        if not init_review_group():
            return render_template("review/done.html")
        group = current_group()
        return redirect(url_for("review.session"))

    # ---------- POST：用户选了评分 ----------
    if request.method == "POST":
        action = request.form.get("action")
        review_id = request.form.get("review_id", type=int)
        word = request.form.get("word", "")
        meaning = request.form.get("meaning", "")

        item = {"review_id": review_id, "word": word, "meaning": meaning}

        if action == "known":
            group["known"].append(item)
        elif action == "vague":
            group["vague"].append(item)
        elif action == "forgotten":
            # 忘记了 → 排到判断轮末尾重判
            group["forgotten"].append(item)

        flask_session["review_group"] = group
        flask_session.modified = True

        # 跳到 onset 页看完整释义
        return redirect(url_for("review.reveal", review_id=review_id))

    # ---------- GET：取下一个词 ----------
    # 如果主队列空了，把 forgotten 的词加进来重判
    if not group["queue"] and group["forgotten"]:
        group["queue"] = group["forgotten"]
        group["forgotten"] = []
        flask_session["review_group"] = group
        flask_session.modified = True

    if not group["queue"]:
        # 判断轮结束 → 进入四选一轮
        group["phase"] = "multichoice"
        group["mc_queue"] = group["vague"][:]
        flask_session["review_group"] = group
        flask_session.modified = True
        return redirect(url_for("review.multichoice"))

    item = group["queue"].pop(0)
    flask_session["review_group"] = group
    flask_session.modified = True

    # 查词典拿音标
    dict_info = lookup_local(item["word"])
    phonetic = dict_info.get("phonetic", "") if dict_info else ""

    # 当前进度 = 已处理数 + 1（已处理 = 认识 + 模糊 + 忘记了）
    processed = len(group["known"]) + len(group["vague"]) + len(group["forgotten"])
    current_idx = processed + 1

    return render_template(
        "review/judge_card.html",
        item=item,
        phonetic=phonetic,
        current_idx=current_idx,
        total=group["total"],
    )


# ==================== onset 页（显示完整释义）====================

@bp.route("/reveal/<int:review_id>")
@login_required
def reveal(review_id):
    """选完评分后显示完整释义（onset 页），有「下一词」和「记错了」按钮。"""
    group = current_group()
    if group is None:
        return redirect(url_for("review.session"))

    # 找到这个词
    item = None
    for lst in [group["known"], group["vague"], group["forgotten"]]:
        for it in lst:
            if it["review_id"] == review_id:
                item = it
                break
        if item:
            break

    if item is None:
        return redirect(url_for("review.session"))

    # 判断这个词被标记成了什么（用于记错了时调整）
    marked_as = None
    if item in group["known"]:
        marked_as = "known"
    elif item in group["vague"]:
        marked_as = "vague"
    else:
        marked_as = "forgotten"

    # 查词典拿完整信息
    dict_info = lookup_local(item["word"])
    parsed_meanings = parse_translation(dict_info.get("translation", "")) if dict_info else []
    if not parsed_meanings:
        parsed_meanings = [{"pos": "", "meanings": [item["meaning"]]}]

    # 常用搭配（从 ECDICT 的 definition 提取或留空）
    phonetic = dict_info.get("phonetic", "") if dict_info else ""
    examples = dict_info.get("examples", [])[:2] if dict_info else []

    processed = len(group["known"]) + len(group["vague"]) + len(group["forgotten"])

    return render_template(
        "review/reveal.html",
        item=item,
        marked_as=marked_as,
        phonetic=phonetic,
        parsed_meanings=parsed_meanings,
        examples=examples,
        current_idx=processed,
        total=group["total"],
    )


@bp.route("/reveal/<int:review_id>/next", methods=["POST"])
@login_required
def reveal_next(review_id):
    """onset 页点「下一词」→ 继续判断轮。"""
    return redirect(url_for("review.session"))


@bp.route("/reveal/<int:review_id>/wrong", methods=["POST"])
@login_required
def reveal_wrong(review_id):
    """onset 页点「记错了」→ 把这个词改成忘记了，排到末尾重判。"""
    group = current_group()
    if group is None:
        return redirect(url_for("review.session"))

    # 从 known/vague 里移除，加到 forgotten
    target = None
    for lst in [group["known"], group["vague"]]:
        for i, it in enumerate(lst):
            if it["review_id"] == review_id:
                target = lst.pop(i)
                break
        if target:
            break

    if target:
        group["forgotten"].append(target)
        flask_session["review_group"] = group
        flask_session.modified = True

    return redirect(url_for("review.session"))


# ==================== 四选一轮 ====================

@bp.route("/multichoice", methods=("GET", "POST"))
@login_required
def multichoice():
    """四选一轮：给模糊的词出 4 个中文释义，选错一直到选对。"""
    group = current_group()
    if group is None:
        return redirect(url_for("review.session"))

    if group["phase"] != "multichoice":
        return redirect(url_for("review.session"))

    # ---------- POST：用户选了一个释义 ----------
    if request.method == "POST":
        selected = request.form.get("meaning", "")
        review_id = request.form.get("review_id", type=int)
        correct_meaning = request.form.get("correct_meaning", "")

        if selected == correct_meaning:
            # 选对了 → 进入回想队列
            for it in group["vague"]:
                if it["review_id"] == review_id:
                    group["recall_queue"].append(it)
                    break
            flask_session["review_group"] = group
            flask_session.modified = True
            return redirect(url_for("review.multichoice"))
        else:
            # 选错了 → 重新出这道题（换干扰项）
            return redirect(url_for("review.multichoice", retry=1))

    # ---------- GET：取下一个模糊词 ----------
    if not group["mc_queue"]:
        # 四选一轮结束 → 进入回想轮
        group["phase"] = "recall"
        flask_session["review_group"] = group
        flask_session.modified = True
        return redirect(url_for("review.recall"))

    item = group["mc_queue"].pop(0)
    flask_session["review_group"] = group
    flask_session.modified = True

    # 生成 4 个选项：1 正确 + 3 干扰
    correct_meaning = item["meaning"]
    distractors = get_distractors(item, item["word"], count=3)
    options = [correct_meaning] + distractors
    random.shuffle(options)

    # 当前进度：四选一轮的第几个
    total_vague = len(group["vague"])
    remaining = len(group["mc_queue"]) + 1  # +1 因为当前这个已经 pop 出来了
    current_idx = total_vague - remaining + 1

    # 查完整词典释义，供"看答案"和答完后显示
    dict_info = lookup_local(item["word"])
    parsed_meanings = parse_translation(dict_info.get("translation", "")) if dict_info else []
    if not parsed_meanings:
        parsed_meanings = [{"pos": "", "meanings": [item["meaning"]]}]
    phonetic = dict_info.get("phonetic", "") if dict_info else ""
    examples = dict_info.get("examples", [])[:2] if dict_info else []

    return render_template(
        "review/multichoice.html",
        item=item,
        options=options,
        correct_meaning=correct_meaning,
        current_idx=current_idx,
        total=total_vague,
        phonetic=phonetic,
        parsed_meanings=parsed_meanings,
        examples=examples,
    )


# ==================== 回想轮 ====================

@bp.route("/recall", methods=("GET", "POST"))
@login_required
def recall():
    """回想轮：只显示中文释义，遮住英文，判断能否想起单词。

    点完按钮后不直接下一词，而是跳到完整释义页（recall_reveal），
    让用户看清单词再决定继续。
    """
    group = current_group()
    if group is None:
        return redirect(url_for("review.session"))

    if group["phase"] != "recall":
        return redirect(url_for("review.session"))

    # ---------- POST：用户判断了 ----------
    if request.method == "POST":
        action = request.form.get("action")
        review_id = request.form.get("review_id", type=int)

        # 找到刚答的这个词：先从 pending 找（GET 时暂存的），再从历史找
        answered_item = group.get("recall_pending")
        if answered_item is None or answered_item.get("review_id") != review_id:
            # 可能是从释义页返回后重新答的，从历史里找
            for it in group.get("recall_history", []):
                if it["review_id"] == review_id:
                    answered_item = it
                    break

        if answered_item:
            if action == "know":
                update_review_quality(review_id, 4)
            else:
                # 没回想起来 → quality=2，记为错词
                update_review_quality(review_id, 2)
                if answered_item not in group.get("wrong_words", []):
                    group.setdefault("wrong_words", []).append(answered_item)

            # 记入历史，供"返回上一词"用
            group.setdefault("recall_history", []).append(answered_item)
            # 当前要展示完整释义的词
            group["recall_current"] = answered_item
            # 清除 pending
            group.pop("recall_pending", None)

        flask_session["review_group"] = group
        flask_session.modified = True
        # 跳到完整释义页（不直接下一词）
        return redirect(url_for("review.recall_reveal"))

    # ---------- GET：取下一个回想词 ----------
    if not group["recall_queue"]:
        # 回想轮结束 → 处理认识的词的 SM-2，然后结束页
        for it in group["known"]:
            update_review_quality(it["review_id"], 5)
        for it in group["forgotten"]:
            update_review_quality(it["review_id"], 0)

        group["phase"] = "done"
        flask_session["review_group"] = group
        flask_session.modified = True
        return redirect(url_for("review.round_done"))

    item = group["recall_queue"].pop(0)
    # 暂存当前词，POST 时能找到
    group["recall_pending"] = item
    flask_session["review_group"] = group
    flask_session.modified = True

    parsed_meanings = parse_translation(item["meaning"])

    # 当前进度：回想轮的第几个
    total_recall = len(group["vague"])
    remaining = len(group["recall_queue"]) + 1
    current_idx = total_recall - remaining + 1

    return render_template(
        "review/recall.html",
        item=item,
        parsed_meanings=parsed_meanings,
        current_idx=current_idx,
        total=total_recall,
    )


# ==================== 回想轮：完整释义页 ====================

@bp.route("/recall-reveal")
@login_required
def recall_reveal():
    """回想轮的完整释义页：点完按钮后展示英文单词、音标、释义、例句。

    顶部有「返回上一词」按钮，底部有「下一词」按钮。
    点「不认识」的用户可以在这里慢慢看，不用着急跳走。
    """
    group = current_group()
    if group is None:
        return redirect(url_for("review.session"))

    item = group.get("recall_current")
    if item is None:
        return redirect(url_for("review.recall"))

    # 查完整词典数据
    dict_info = lookup_local(item["word"])
    parsed_meanings = parse_translation(item["meaning"])
    phonetic = dict_info.get("phonetic", "") if dict_info else ""
    examples = dict_info.get("examples", [])[:2] if dict_info else []
    collins_def = dict_info.get("collins_definition", "") if dict_info else ""

    # 是否还有上一词可返回
    history = group.get("recall_history", [])
    has_prev = len(history) >= 2  # history[-1] 是当前词，history[-2] 才是上一个

    # 是否还有下一词
    has_next = len(group["recall_queue"]) > 0

    # 当前进度
    total_recall = len(group["vague"])
    current_idx = len(history)  # 已经答了几个

    return render_template(
        "review/recall_reveal.html",
        item=item,
        parsed_meanings=parsed_meanings,
        phonetic=phonetic,
        examples=examples,
        collins_def=collins_def,
        has_prev=has_prev,
        has_next=has_next,
        current_idx=current_idx,
        total=total_recall,
    )


@bp.route("/recall-reveal/next", methods=["POST"])
@login_required
def recall_reveal_next():
    """完整释义页点「下一词」→ 继续回想轮。"""
    group = current_group()
    if group is None:
        return redirect(url_for("review.session"))

    if not group["recall_queue"]:
        # 回想轮结束
        for it in group["known"]:
            update_review_quality(it["review_id"], 5)
        for it in group["forgotten"]:
            update_review_quality(it["review_id"], 0)
        group["phase"] = "done"
        flask_session["review_group"] = group
        flask_session.modified = True
        return redirect(url_for("review.round_done"))

    return redirect(url_for("review.recall"))


@bp.route("/recall-reveal/back", methods=["POST"])
@login_required
def recall_reveal_back():
    """完整释义页点「返回上一词」→ 回到上一个词的释义页。"""
    group = current_group()
    if group is None:
        return redirect(url_for("review.session"))

    history = group.get("recall_history", [])
    if len(history) >= 2:
        # 当前词回到队列头部（等下还能再答）
        current = history.pop()
        group["recall_queue"].insert(0, current)
        # 上一个词成为当前展示词
        group["recall_current"] = history[-1]
        # 把错词记录里的当前词去掉（因为要重答）
        group["wrong_words"] = [w for w in group.get("wrong_words", [])
                                if w["review_id"] != current["review_id"]]

    flask_session["review_group"] = group
    flask_session.modified = True
    return redirect(url_for("review.recall_reveal"))


# ==================== 本轮复习完成页 ====================

@bp.route("/round-done")
@login_required
def round_done():
    """这组词复习完啦，选择拼写全部 / 拼写错词 / 退出。"""
    group = current_group()
    if group is None:
        return redirect(url_for("review.index"))

    known_count = len(group["known"])
    vague_count = len(group["vague"])
    wrong_count = len(group.get("wrong_words", []))

    return render_template(
        "review/round_done.html",
        known_count=known_count,
        vague_count=vague_count,
        wrong_count=wrong_count,
        total=group["total"],
    )


@bp.route("/finish", methods=["POST"])
@login_required
def finish():
    """退出复习，清除状态。"""
    clear_group()
    return redirect(url_for("review.index"))


# ==================== 拼写轮 ====================

@bp.route("/spelling", methods=("GET", "POST"))
@login_required
def spelling():
    """拼写轮：看中文写英文（一次一题，错题重做）。

    GET 参数 mode=all 拼写全部认识的词；mode=wrong 只拼写错词。
    """
    group = current_group()

    if request.method == "POST":
        clear_group()
        return redirect(url_for("review.index"))

    # 如果没有进行中的组，就从词库随机抽（兼容旧入口）
    if group is None:
        db = get_db()
        words = db.execute(
            "SELECT id, word, meaning FROM words WHERE user_id = ? ORDER BY RANDOM() LIMIT 10",
            (g.user["id"],),
        ).fetchall()
        if not words:
            flash("生词本里还没有单词，先去加点词吧")
            return redirect(url_for("review.index"))
        words_list = [{"word": w["word"], "meaning": w["meaning"]} for w in words]
    else:
        mode = request.args.get("mode", "all")
        if mode == "wrong":
            words_list = [{"word": w["word"], "meaning": w["meaning"]}
                          for w in group.get("wrong_words", [])]
            if not words_list:
                flash("没有错词需要拼写")
                return redirect(url_for("review.round_done"))
        else:
            # 拼写全部：认识的词 + 模糊的词（模糊词已通过四选一和回想轮）
            # 这样所有复习过的词都能拼写，不会出现 0 题
            words_list = [{"word": w["word"], "meaning": w["meaning"]}
                          for w in group.get("known", []) + group.get("vague", [])]
            if not words_list:
                flash("没有可拼写的单词")
                return redirect(url_for("review.round_done"))

    # 给每个词补上音标（提示按钮用）
    for w in words_list:
        dict_info = lookup_local(w["word"])
        w["phonetic"] = dict_info.get("phonetic", "") if dict_info else ""

    words_json = json.dumps(words_list, ensure_ascii=False)
    return render_template("review/spelling.html", words_json=words_json)
