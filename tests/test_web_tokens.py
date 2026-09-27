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


if __name__ == "__main__":
    unittest.main()
