// 发音功能：用有道词典 API 播放单词发音
// 接口：https://dict.youdao.com/dictvoice?audio=WORD&type=TYPE
//   type=1 英音，type=2 美音

(function() {
    "use strict";

    var cfg = window.USER_PRONOUNCE || { defaultAccent: "en", autoPronounce: 0 };

    // 有道发音接口：type 1=英音 2=美音
    function voiceUrl(word, accent) {
        var type = accent === "us" ? 2 : 1;
        return "https://dict.youdao.com/dictvoice?audio=" + encodeURIComponent(word) + "&type=" + type;
    }

    // 播放单词发音
    // accent: "en" | "us"，不传则用默认口音
    function pronounce(word, accent) {
        if (!word) return;
        accent = accent || cfg.defaultAccent;
        var audio = new Audio(voiceUrl(word, accent));
        // 播放失败时静默处理（网络问题等）
        audio.play().catch(function() {});
    }

    // 记录上一次播放的单词，用于单击切换口音
    var lastWord = null;
    var lastAccent = null;

    // 点击可发音元素时的处理
    function onPronounceClick(e) {
        var el = e.target.closest(".pronounceable");
        if (!el) return;
        e.preventDefault();

        var word = el.getAttribute("data-word");
        if (!word) return;

        var accent;
        if (word === lastWord) {
            // 同一个单词，再次点击 → 切换到另一种口音
            accent = lastAccent === "us" ? "en" : "us";
        } else {
            // 新单词 → 用默认口音
            accent = cfg.defaultAccent;
        }

        pronounce(word, accent);
        lastWord = word;
        lastAccent = accent;
    }

    // 给页面上所有 .pronounceable 元素绑定点击事件（事件委托）
    document.addEventListener("click", onPronounceClick);

    // 自动朗读：页面上有 data-autoplay="1" 的元素，加载后自动用默认口音播放
    function autoPronounce() {
        if (!cfg.autoPronounce) return;
        var el = document.querySelector("[data-autoplay='1']");
        if (el) {
            var word = el.getAttribute("data-word");
            if (word) {
                // 延迟一点，等页面渲染完
                setTimeout(function() {
                    pronounce(word, cfg.defaultAccent);
                    lastWord = word;
                    lastAccent = cfg.defaultAccent;
                }, 300);
            }
        }
    }

    // 页面加载完成后自动朗读
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", autoPronounce);
    } else {
        autoPronounce();
    }

    // 暴露到全局，方便页面内联 JS 调用
    window.pronounce = pronounce;
})();
