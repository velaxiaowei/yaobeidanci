-- ============================================================
-- 数据库建表配方（SQL 语句）。
-- 执行本脚本会把所有需要的表一次性建好。
-- 目前 P0 有两张表：
--   users  ：用户表（账号模块）
--   words  ：生词本表（生词本模块）
-- 复习进度的表，等做到复习模块时再往下加。
-- ============================================================

-- 如果表已经存在就先删掉，避免重复执行时报"表已存在"。
-- 注意：DROP 会清空该表所有数据！开发期没事，正式使用前要去掉这句。
-- 删除顺序：先删"引用别人的表"（notes/examples → words），再删"被引用的表"，
--           避免外键约束挡路。
DROP TABLE IF EXISTS notes;
DROP TABLE IF EXISTS examples;
DROP TABLE IF EXISTS words;
DROP TABLE IF EXISTS users;

-- ==================== 用户表 ====================
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,  -- 用户编号，自增主键
    username      TEXT    NOT NULL UNIQUE,            -- 用户名，必填且不能重复
    password_hash TEXT    NOT NULL,                   -- 密码的哈希指纹（不存明文）
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- 注册时间，默认当前时刻
);

-- ==================== 生词本表 ====================
-- 一行 = "某个用户把某个英文单词加入了生词本"。
-- user_id 关联 users.id，决定这条词"属于谁"——这是多用户数据隔离的关键：
--   查 testuser 的生词就 WHERE user_id = 1，别人看不到也改不了。
CREATE TABLE words (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,   -- 生词编号，自增主键
    user_id    INTEGER NOT NULL,                     -- 拥有者用户编号（外键 → users.id）
    word       TEXT    NOT NULL,                     -- 英文单词，例如 abandon
    meaning    TEXT    NOT NULL,                     -- 中文释义，例如 放弃
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- 加入生词本的时间

    -- 唯一约束：同一个用户不能把同一个单词加两次。
    -- 这条约束是后面"加入/取消生词本"按钮切换状态的底层保障——
    -- 后端不靠"先查一下有没有"判断，而是直接靠数据库拒绝重复插入。
    UNIQUE (user_id, word),

    -- 外键约束：user_id 必须真实存在于 users 表的 id 列。
    -- 防止出现"指向不存在用户"的脏数据。
    -- ON DELETE CASCADE：如果将来某个用户被删了，他的所有生词自动跟着删掉。
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- ==================== 例句表 ====================
-- 一行 = "某个用户为某个生词保存了一条例句"。
-- 例句来源：dictionary（词典自带）、ai（大模型生成）、manual（用户手动输入）。
-- 以后可以在"例句库"页面集中浏览，作为写作/口语素材。
CREATE TABLE examples (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,                     -- 拥有者
    word_id    INTEGER NOT NULL,                     -- 关联的生词（外键 → words.id）
    sentence   TEXT    NOT NULL,                     -- 例句内容
    source     TEXT    NOT NULL DEFAULT 'manual',    -- 来源：dictionary / ai / manual
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 一个用户对同一个词不能保存完全相同的例句（去重）
    UNIQUE (user_id, word_id, sentence),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE
);

-- ==================== 笔记表 ====================
-- 一行 = "某个用户为某个生词写的一条笔记"。
-- 一个词可以有多条笔记，每条有创建时间。
-- 笔记是用户的自由输入：易混词辨析、联想、记忆技巧等。
CREATE TABLE notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,                     -- 拥有者
    word_id    INTEGER NOT NULL,                     -- 关联的生词（外键 → words.id）
    content    TEXT    NOT NULL,                     -- 笔记内容
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE
);

-- ==================== 复习进度表 ====================
-- 一行 = "某个用户对某个生词的复习进度"。
-- 一个词只有一条复习记录（UNIQUE 保证），加进生词本时同时插入一行初始记录。
-- SM-2 算法的状态全部存在这张表里：
--   ef         简易度 Easiness Factor，初始 2.5，范围 [1.3, 2.5+]，
--              反映"这个词对你来说有多好记"。越难记 ef 越低，下次复习间隔越短。
--   rep        连续答对次数（评分 >= 3 算答对）。答错一次就归 0。
--   interval   下次复习的间隔天数。SM-2 公式：
--              rep==1 → 1 天；rep==2 → 6 天；rep>=3 → round(interval × ef)
--   last_review 上次复习时间
--   next_review 下次该复习的时间。每次复习后 = 今天 + interval 天。
--              查"今日待复习"就是 WHERE next_review <= 当前日期。
CREATE TABLE reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,                       -- 拥有者
    word_id      INTEGER NOT NULL UNIQUE,                -- 关联的生词（一个词一条复习记录）
    ef           REAL    NOT NULL DEFAULT 2.5,           -- 简易度，初始 2.5
    rep          INTEGER NOT NULL DEFAULT 0,              -- 连续答对次数，初始 0
    interval     INTEGER NOT NULL DEFAULT 0,              -- 下次复习间隔天数，初始 0
    last_review  TIMESTAMP,                              -- 上次复习时间（NULL = 还没复习过）
    next_review  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- 下次复习时间，默认现在（=立即待复习）
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE
);
