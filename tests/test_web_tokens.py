# -*- coding: utf-8 -*-
"""网页样式的几条硬规矩（不跑浏览器，只解析 CSS）。

UI 改版最容易犯的错不是「不好看」，而是这五件事：

1. 把描金当正文色。`--gold-dark`（#A68A3D）在宣纸上只有 2.71:1，当正文根本读不清，
   所以正文一律走 `--gold-ink`（#7A6224 → 4.76:1）。这里直接把每一处 `color:` 的
   对比度算出来，低于 AA 4.5:1 就红。
2. 又给阅读区/选项区加 max-height 内滚。旧版 62vh + 34vh 两层内滚叠在页面滚动上，
   正文被拦腰截断。这里盯住这两块面板不许出现 max-height / overflow。
3. 引外部字体或图片。单文件必须能离线打开，CSS 里不许有 url() 与 @import。
4. `var(--typo)` 名字写错：整条声明静默失效，颜色变回继承值。这里核对「用到的变量
   都在某处定义过」。
5. 键盘焦点与「减少动效」被忘掉。全站要有 `:focus-visible`，
   `body[data-motion="off"]` 与 `prefers-reduced-motion` 都要有对应规则。
"""

import io
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STYLE = os.path.join(ROOT, "web", "src", "style.css")
STATIC = os.path.join(ROOT, "web", "src", "static.css")

VAR_USE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)")
VAR_DEF = re.compile(r"(--[A-Za-z0-9_-]+)\s*:")            # 只看名字
VAR_VALUE = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;}]+)")  # 名字 + 值
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
COLOR_DECL = re.compile(r"(?<![-\w])color\s*:\s*([^;}]+)", re.I)
FONT_DECL = re.compile(r"font-size\s*:\s*([^;}]+)", re.I)
HEX = re.compile(r"#([0-9a-fA-F]{6})\b")
RGBA = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)")

# 正文色至少要 4.5:1（WCAG AA），主墨色按 AAA 要求 7:1
AA = 4.5
AAA = 7.0

# 原型 v1.1 那一层皮：新令牌、标题楷体、新配色、新动效
BG_DECL = re.compile(r"(?<![-\w])background\s*:\s*([^;}]+)", re.I)
ANIM_DECL = re.compile(r"(?<![-\w])animation\s*:\s*([^;}]+)", re.I)
KEYFRAMES = re.compile(r"@keyframes\s+([A-Za-z][\w-]*)")
COLOR_TOKEN = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)|#([0-9a-fA-F]{6})\b|(rgba?\([^)]*\))")
MOTION_MEDIA = re.compile(r"@media[^{]*prefers-reduced-motion[^{]*\{")


def text_after_block(text, start):
    """从 start（`{` 之后）取出配平的那一整块内容 —— 用来读 @media 里面的规则。"""
    depth, i = 1, start
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[start:i - 1]


def read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def strip_comments(text):
    """注释里会提到旧值（比如「曾经的 62vh 内滚」），查违规前先把注释去掉。"""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _channel(value):
    value = value / 255.0
    if value <= 0.03928:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = rgb
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg, bg):
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def parse_hex(text):
    m = HEX.search(text)
    if not m:
        return None
    raw = m.group(1)
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def over(fg, alpha, bg):
    """把半透明的前景压在不透明的底色上，得到实际看到的颜色。"""
    return tuple(int(round(alpha * fg[i] + (1 - alpha) * bg[i])) for i in range(3))


class WebStyleContractTest(unittest.TestCase):
    def setUp(self):
        self.style = read(STYLE)
        self.static = read(STATIC)
        self.css = self.style + "\n" + self.static
        self.tokens = dict(VAR_VALUE.findall(self.style))

    def _paper(self):
        paper = parse_hex(self.tokens["--paper"])
        self.assertIsNotNone(paper, "--paper 应当是十六进制颜色")
        return paper

    def _resolve(self, value):
        """把 `var(--x)` 或字面量颜色解析成 rgb，解析不了就返回 None。"""
        value = value.strip()
        m = re.match(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,[^)]*)?\)", value)
        if m:
            return parse_hex(self.tokens.get(m.group(1), ""))
        rgb = parse_hex(value)
        if rgb:
            return rgb
        m = RGBA.search(value)
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return None

    def test_every_variable_is_defined_somewhere(self):
        used = set(VAR_USE.findall(self.css))
        defined = set(VAR_DEF.findall(self.css))
        missing = sorted(used - defined)
        self.assertEqual([], missing, "这些变量只被用到、没被定义过：%s" % missing)

    def test_every_font_size_token_is_used(self):
        tokens = sorted(name for name in VAR_DEF.findall(self.style) if name.startswith("--fs-"))
        self.assertEqual(7, len(tokens), "字号阶梯应当正好七档，现在是 %s" % tokens)
        for name in tokens:
            self.assertIn("var(%s)" % name, self.css, "%s 定义了却没人用" % name)

    def test_no_text_is_smaller_than_the_smallest_step(self):
        paper = self._paper()
        for selector, body in RULE.findall(self.style):
            for value in FONT_DECL.findall(body):
                value = value.strip()
                if "var(" in value or "px" in value:
                    continue
                rem = re.match(r"^([0-9.]+)rem$", value)
                self.assertIsNotNone(rem, "字号请走令牌：%s { font-size: %s }" % (selector.strip(), value))
                size = float(rem.group(1))
                self.assertGreaterEqual(size, 0.78, "%s 的字号 %s 小到读不清了" % (selector.strip(), value))
                self.assertLessEqual(size, 2.4, "%s 的字号 %s 大得不像正文" % (selector.strip(), value))
        self.assertIsNotNone(paper)

    def test_all_text_clears_wcag_aa(self):
        paper = self._paper()
        checks = {"--ink": AAA, "--ink-light": AA, "--gold-ink": AA, "--crimson": AA,
                  "--crimson-dark": AA, "--jade-dark": AA}
        for name, want in checks.items():
            rgb = parse_hex(self.tokens[name])
            self.assertIsNotNone(rgb, "%s 应当是十六进制颜色" % name)
            got = contrast(rgb, paper)
            self.assertGreaterEqual(round(got, 2), want,
                                    "%s 在宣纸上是 %.2f:1，低于 %.1f:1" % (name, got, want))
        paper_light = parse_hex(self.tokens["--paper-light"])
        self.assertGreaterEqual(round(contrast(parse_hex(self.tokens["--gold-ink"]), paper_light), 2), AA,
                                "--gold-ink 在纸亮色上不到 4.5:1")

    def test_gold_and_jade_only_draw_lines(self):
        # 描金与青玉是画线用的：一旦出现在 color 里，正文就看不清了
        banned = ("--gold", "--gold-dark", "--jade")
        for selector, body in RULE.findall(self.style):
            for value in COLOR_DECL.findall(body):
                for name in banned:
                    self.assertNotIn("var(%s)" % name, value,
                                     "%s 用 %s 画了字：它是给线条用的" % (selector.strip(), name))

    def test_every_literal_text_colour_clears_aa(self):
        paper = self._paper()
        for selector, body in RULE.findall(self.style):
            for value in COLOR_DECL.findall(body):
                value = value.strip()
                if "var(" in value:
                    continue
                rgb = self._resolve(value)
                self.assertIsNotNone(rgb, "认不出这个颜色：%s { color: %s }" % (selector.strip(), value))
                m = RGBA.search(value)
                alpha = float(m.group(4)) if (m and m.group(4)) else 1.0
                shown = over(rgb, alpha, paper)
                got = contrast(shown, paper)
                self.assertGreaterEqual(round(got, 2), AA,
                                        "%s 的字色 %s 在纸上只有 %.2f:1" % (selector.strip(), value, got))

    def test_reading_and_options_do_not_scroll_inside(self):
        seen = 0
        for selector, body in RULE.findall(self.style):
            flat = " ".join(selector.split())
            if ".reading .panel-body" not in flat and ".options .panel-body" not in flat:
                continue
            seen += 1
            self.assertNotIn("max-height", body, "%s 又加内滚了：正文会被截断" % flat)
            self.assertNotIn("overflow", body, "%s 又加 overflow 了" % flat)
        self.assertGreaterEqual(seen, 2, "没找到阅读区/选项区那两条规则，选择器可能被改名了")
        for old in ("52vh", "62vh", "34vh", "44vh"):
            self.assertNotIn(old, strip_comments(self.style), "旧版的内滚高度 %s 又回来了" % old)

    def test_keyboard_and_motion_are_handled(self):
        self.assertRegex(self.style, r":focus-visible\s*\{[^}]*outline",
                         "全站要有一圈键盘焦点：`outline` 的 :focus-visible")
        self.assertIn('body[data-motion="off"]', self.style, "设定里关掉动效时要有对应规则")
        self.assertIn("prefers-reduced-motion", self.style, "要尊重系统的「减少动效」")

    def test_no_external_resources_in_css(self):
        for path, text in ((STYLE, self.style), (STATIC, self.static)):
            self.assertNotIn("@import", text, os.path.basename(path))
            self.assertNotRegex(text, r"url\(\s*['\"]?(?:https?:)?//",
                                "%s 引了外部资源" % os.path.basename(path))


    # ---- 原型 v1.1 那一层皮（新令牌 / 标题楷体 / 新配色 / 新动效）----

    V11_TOKENS = ("--display", "--panel", "--panel-solid", "--radius-lg", "--shadow-card",
                  "--chip-bg", "--highlight", "--seal-a", "--seal-b")
    # 楷体栈只许排标题；这几条是它现在的全部用主
    TITLE_SELECTORS = (".seal-badge", ".choice-num", ".splash-title", ".splash .seal-stamp",
                       ".metric-num", ".rail-num")
    # 正文口径的选择器：`--display` 一旦落到它们身上就是排版事故
    PROSE_TOKENS = (".panel-body", ".log-entry", ".dlg", ".kv-line", ".said-line",
                    ".choice-label", ".doc-body", "pre")
    # 新配色的字：逐个照 CSS 里真写的 fg/bg 算对比度（半透明先压到纸上/面板上）
    PALETTE_SELECTORS = (
        ".glass-panel", ".rail-card", ".hud-chip",
        ".trust-row", ".trust-name", ".trust-num",
        ".choice-card", ".choice-num", ".choice-label",
        ".kv", ".kv-line", ".log-clue",
        ".panel-head", ".log-bar", ".log-bar .count", ".btn.log-toggle",
        ".icon-btn, .btn.icon-btn", ".tab", ".credit", ".lock-chip",
        ".splash-hint", ".splash-quote", ".splash-num",
        ".seal-badge", ".splash .seal-stamp",
    )
    # 字面字号的老账：除这四处（外加 html,body 的 16px）以外不许再出现字面量
    LITERAL_FONT_SIZES = {(".brand", "1.34rem"), (".brand", "1.16rem"),
                          (".command .prompt", "1.05rem"),
                          (".ending-seal .seal-title", "1.04rem")}

    def _flat(self, text):
        return " ".join(text.split())

    def _rules(self):
        """去掉注释后的 (选择器, 声明块) —— 注释里提到旧写法，不能进判定。"""
        return [(self._flat(selector), body)
                for selector, body in RULE.findall(strip_comments(self.style))]

    def _colours_on(self, value, ground):
        """一段颜色值（var / hex / rgba / 渐变）压到 ground 上，返回它可能出现的每一种颜色。"""
        out = []
        for name, hexed, rgba in COLOR_TOKEN.findall(value):
            if name:
                out.extend(self._colours_on(self.tokens.get(name, ""), ground))
                continue
            if hexed:
                out.append((int(hexed[0:2], 16), int(hexed[2:4], 16), int(hexed[4:6], 16)))
                continue
            m = RGBA.search(rgba)
            rgb = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            alpha = float(m.group(4)) if m.group(4) else 1.0
            out.append(over(rgb, alpha, ground))
        return out

    def _grounds(self):
        """字底下可能铺的两层底：宣纸，以及压在上面的玻璃面板。"""
        paper = self._paper()
        return [paper] + (self._colours_on("var(--panel)", paper) or [])

    def test_v11_tokens_are_defined_and_used(self):
        style = strip_comments(self.style)
        outside = style[style.index("}", style.index(":root")):]
        for name in self.V11_TOKENS:
            self.assertIn(name, self.tokens, "%s 没有定义" % name)
            self.assertIn("var(%s)" % name, outside, "%s 定义了却没有任何规则引用" % name)
        defined = set(VAR_DEF.findall(self.style))
        orphans = sorted(name for name in defined if "var(%s)" % name not in self.css)
        self.assertEqual([], orphans, "这些令牌定义了却没人引用：%s" % orphans)

    def test_display_face_only_draws_titles(self):
        found = []
        for selector, body in self._rules():
            if "var(--display)" not in body:
                continue
            found.append(selector)
            for token in self.PROSE_TOKENS:
                self.assertIsNone(re.search(re.escape(token) + r"(?![\w-])", selector),
                                  "%s 拿标题楷体排了正文" % selector)
            self.assertIn(selector, self.TITLE_SELECTORS,
                          "%s 用了 --display：楷体栈只许排标题" % selector)
        self.assertGreaterEqual(len(found), 4,
                                "--display 只落在 %d 条规则上，标题字是不是被撤掉了" % len(found))

    def test_the_new_palette_clears_wcag_aa(self):
        for wanted in self.PALETTE_SELECTORS:
            bodies = [body for selector, body in self._rules() if selector == wanted]
            self.assertTrue(bodies, "没找到规则：%s" % wanted)
            fg_values = [value.strip() for body in bodies for value in COLOR_DECL.findall(body)]
            bg_values = [value.strip() for body in bodies for value in BG_DECL.findall(body)]
            fg_value = fg_values[-1] if fg_values else "var(--ink)"
            bg_value = bg_values[-1] if bg_values else None
            worst = None
            for base in self._grounds():
                grounds = [base]
                if bg_value and not bg_value.lower().startswith("none"):
                    grounds = self._colours_on(bg_value, base) or [base]
                for ground in grounds:
                    for fg in self._colours_on(fg_value, ground):
                        got = contrast(fg, ground)
                        if worst is None or got < worst[0]:
                            worst = (got, fg, ground)
            self.assertIsNotNone(worst, "%s 的字色没解析出来" % wanted)
            got, fg, ground = worst
            self.assertGreaterEqual(round(got, 2), AA,
                                    "%s 的字色 %s 压在 %s 上只有 %.2f:1" % (wanted, fg, ground, got))

    def test_literal_font_sizes_stay_on_the_ladder(self):
        found = set()
        for selector, body in RULE.findall(self.style):
            for value in FONT_DECL.findall(body):
                value = value.strip()
                if "var(" in value or "px" in value:
                    continue
                found.add((self._flat(selector), value))
        self.assertEqual(self.LITERAL_FONT_SIZES, found,
                         "又冒出没走令牌的字号：%s" % sorted(found - self.LITERAL_FONT_SIZES))

    def test_new_motion_is_switched_off_in_both_places(self):
        style = strip_comments(self.style)
        keyframes = set(KEYFRAMES.findall(style))
        self.assertIn("fall", keyframes, "落花的关键帧 `fall` 不见了")
        self.assertIn("stampIn", keyframes, "印章的关键帧 `stampIn` 不见了")
        off = set()
        for selector, body in RULE.findall(style):
            if "data-motion" not in selector:
                continue
            for part in selector.split(","):
                part = self._flat(part).split('"]', 1)[-1].strip()
                if part:
                    off.add(part)
        reduced = set()
        for media in MOTION_MEDIA.finditer(style):
            for selector, body in RULE.findall(text_after_block(style, media.end())):
                for part in selector.split(","):
                    reduced.add(self._flat(part))
        self.assertTrue(off, '没有 body[data-motion="off"] 的关断规则')
        self.assertTrue(reduced, "没有 prefers-reduced-motion 的关断规则")
        animated = []
        for selector, body in RULE.findall(style):
            for value in ANIM_DECL.findall(body):
                names = [name for name in sorted(keyframes)
                         if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(name), value)]
                if not names:
                    continue
                for part in selector.split(","):
                    animated.append((self._flat(part), names[0]))
        self.assertGreaterEqual(len(animated), 4, "只找到 %d 处动效" % len(animated))
        for selector, name in animated:
            self.assertIn(selector, off,
                          '%s 的 `%s` 没在 body[data-motion="off"] 里关掉' % (selector, name))
            self.assertIn(selector, reduced,
                          "%s 的 `%s` 没在 prefers-reduced-motion 里关掉" % (selector, name))
        for name in ("fall", "stampIn"):
            self.assertTrue([sel for sel, key in animated if key == name],
                            "`%s` 没有用主：新动效是不是被删了" % name)

    def test_rail_cards_do_not_own_a_scrollbar(self):
        seen = 0
        for selector, body in self._rules():
            if not re.search(r"\.rail-card(?![\w-])", selector):
                continue
            seen += 1
            self.assertNotIn("max-height", body, "%s 给仪表卡加了内滚" % selector)
            self.assertIsNone(re.search(r"overflow(?:-[xy])?\s*:\s*(?:auto|scroll)", body),
                              "%s 让仪表卡自己滚起来了：整页只留一条滚动条" % selector)
        self.assertGreaterEqual(seen, 1, "没找到 .rail-card 的规则")


if __name__ == "__main__":
    unittest.main()
