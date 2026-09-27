"""终端排版层单测：CJK 双宽、ANSI 透明、换行禁则、画布定位、分栏。

这些是本项目最容易「看着对、实际错位」的地方，所以全部用断言钉死。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, ".")

from gongwei.tui import terminal as T

#: 这一层要逐字比 ANSI（见 AnsiTest），所以把「无色出口」的外部开关先摘掉：
#: NO_COLOR 是给玩家用的，CI 或某些终端工具默认设了它（值为 1），留着会让
#: 比色的断言依据跑测试的机器不同而红。想验无色行为请显式调 T.set_color(False)。
os.environ.pop("NO_COLOR", None)


class CharWidthTest(unittest.TestCase):
    def test_ascii_is_one(self):
        self.assertEqual(T.display_width("abc"), 3)
        self.assertEqual(T.char_width("a"), 1)

    def test_cjk_is_two(self):
        self.assertEqual(T.display_width("宫闱迷踪"), 8)
        self.assertEqual(T.char_width("宫"), 2)

    def test_mixed(self):
        # 3 个汉字 = 6 列，再加 " ok" = 3 列
        self.assertEqual(T.display_width("沈墨白 ok"), 9)

    def test_empty(self):
        self.assertEqual(T.display_width(""), 0)


class AnsiTest(unittest.TestCase):
    def test_strip_removes_sgr(self):
        self.assertEqual(T.strip_ansi("\x1b[31m红\x1b[0m"), "红")

    def test_visible_width_ignores_sgr(self):
        self.assertEqual(T.visible_width("\x1b[31m红\x1b[0m"), 2)
        self.assertEqual(T.visible_width("\x1b[1;36m宫闱\x1b[0m"), 4)

    def test_fg_helper_round_trip(self):
        # fg() 只给 ANSI 起手码（可见宽度为 0），paint() 才是「上色后的文字」
        self.assertEqual(T.visible_width(T.fg("red")), 0)
        self.assertIn("\x1b[", T.fg("red"))
        painted = T.paint("宫", "red")
        self.assertEqual(T.visible_width(painted), 2)
        self.assertIn("\x1b[", painted)


class TruncateTest(unittest.TestCase):
    def test_no_truncation_when_fits(self):
        self.assertEqual(T.truncate("沈墨白", 10), "沈墨白")

    def test_truncates_on_display_width_not_len(self):
        # 6 个汉字 = 12 列，限宽 8 → 最多 3 个汉字 + 省略号
        out = T.truncate("沈墨白验尸录", 8)
        self.assertLessEqual(T.display_width(out), 8)
        self.assertTrue(out.endswith("…"))

    def test_never_splits_wide_char(self):
        out = T.truncate("宫闱", 3)
        self.assertLessEqual(T.display_width(out), 3)
        self.assertTrue(out.startswith("宫"))

    def test_ansi_survives(self):
        out = T.truncate(T.fg("沈墨白验尸录", "red"), 8)
        self.assertLessEqual(T.visible_width(out), 8)


class WrapTest(unittest.TestCase):
    def test_every_line_fits(self):
        text = "你把记事簿摊在膝上，一条一条对着现场看，看到茶那条时忽然想起一件事。"
        for line in T.wrap_text(text, 12):
            self.assertLessEqual(T.display_width(line), 12, line)

    def test_explicit_newlines_kept(self):
        lines = T.wrap_text("第一行\n第二行", 20)
        self.assertEqual(lines, ["第一行", "第二行"])

    def test_leading_punctuation_not_orphaned(self):
        """禁则：行首不收标点。"""
        lines = T.wrap_text("甲乙丙丁戊己庚辛，壬癸", 8)
        for line in lines:
            self.assertNotIn(line[:1], "、。，．：；！？）」』】》〉·%…")

    def test_trailing_open_bracket_pushed_down(self):
        """禁则：行尾不留前引号/前括号。"""
        for line in T.wrap_text("甲乙丙丁「戊己庚辛」", 6):
            self.assertNotIn(line[-1:] if line else "", "（「『【《〈")

    def test_long_token_is_broken_not_overflowed(self):
        for line in T.wrap_text("x" * 40, 7):
            self.assertLessEqual(T.display_width(line), 7)

    def test_a_latin_word_before_a_line_start_punctuation(self):
        """拉丁词被整体塞进行尾时，禁则回挪不能假设「上一格是单个汉字」。

        案② 的日志里就是这种句子（「…抄了 01-FY-XFE，后面…」）：整词进了
        行末，下一格又是行首禁则的逗号。按单字符算宽度会
        `TypeError: ord() expected a character, but string of length N found`；
        而照搬整个词挪下来又会让那一行超出宽度。两种都不行，所以这里扫一遍。
        """
        for text in ("第一行末尾有个词 01-FY-XFE，后面接着写。",
                     "甲01-FY-XFE，乙",
                     "「甲子」，01-FY-XFE「乙」"):
            for width in range(6, 30):
                for line in T.wrap_text(text, width):
                    self.assertLessEqual(T.display_width(line), width,
                                         (text, width, line))

    def test_empty_text(self):
        self.assertEqual(T.wrap_text("", 10), [""])


class PadTest(unittest.TestCase):
    def test_pad_counts_display_width(self):
        self.assertEqual(T.display_width(T.pad("宫", 10)), 10)
        self.assertEqual(T.display_width(T.pad("abc", 10)), 10)

    def test_right_align(self):
        out = T.pad("宫", 6, align="right")
        self.assertEqual(T.display_width(out), 6)
        self.assertTrue(out.endswith("宫"))

    def test_center(self):
        out = T.pad("宫闱", 10, align="center")
        self.assertEqual(T.display_width(out), 10)


class CanvasTest(unittest.TestCase):
    def test_every_rendered_line_is_exact_width(self):
        cv = T.Canvas(20, 3)
        cv.put(0, 0, "宫闱迷踪")
        cv.put(2, 1, T.fg("沈墨白", "cyan"))
        lines = cv.render()
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertEqual(T.visible_width(line), 20, repr(line))

    def test_inline_style_does_not_shift_columns(self):
        """回归：内联 ANSI 曾被按字符占位，导致整屏右移。

        判据一（显示列）：``put(0,0,"宫闱")`` 后紧跟的 ``put(5,0,"A")`` 必须落在
        显示列 5 上 —— 字符下标是 3，因为两个汉字各占两列。
        判据二（不写半个汉字）：``put(3,0,"B")`` 落在「闱」的右半格，必须被丢掉。
        """
        cv = T.Canvas(12, 1)
        cv.put(0, 0, "\x1b[36m宫闱\x1b[0m")
        cv.put(5, 0, "A")
        cv.put(3, 0, "B")
        text = T.strip_ansi(cv.render()[0])
        self.assertNotIn("B", text)
        self.assertEqual(text.index("A"), 3)
        self.assertEqual(T.display_width(text[:text.index("A")]), 5)
        self.assertEqual(T.visible_width(cv.render()[0]), 12)

    def test_box_borders_align(self):
        cv = T.Canvas(24, 5)
        cv.box(0, 0, 24, 5, title="卷宗")
        lines = cv.render()
        for line in lines:
            self.assertEqual(T.visible_width(line), 24)
        self.assertTrue(T.strip_ansi(lines[0]).startswith("╭"))
        self.assertIn("卷宗", T.strip_ansi(lines[0]))
        self.assertTrue(T.strip_ansi(lines[-1]).startswith("╰"))

    def test_box_mark_sits_in_front_of_the_title(self):
        """卡头记号：`mark` 占标题前面一格，标题跟着右移，行宽仍然恰好 24。"""
        cv = T.Canvas(24, 5)
        cv.box(0, 0, 24, 5, title="卷宗", mark="◆", mark_color="red")
        line = cv.render()[0]
        self.assertEqual(T.visible_width(line), 24)
        self.assertIn("╭─ ◆ 卷宗 ", T.strip_ansi(line))
        self.assertIn(T.fg("red") + " ◆ ", line, "记号该单独上色")

    def test_box_mark_alone_when_the_panel_is_too_narrow(self):
        """窄得放不下标题时只留记号，不许挤出框外。"""
        cv = T.Canvas(8, 3)
        cv.box(0, 0, 8, 3, title="卷宗", mark="◆")
        line = cv.render()[0]
        self.assertEqual(T.visible_width(line), 8)
        self.assertIn("◆", T.strip_ansi(line))

    def test_put_never_overflows_canvas(self):
        cv = T.Canvas(6, 1)
        cv.put(4, 0, "沈墨白验尸录")
        self.assertEqual(T.visible_width(cv.render()[0]), 6)

    def test_put_out_of_bounds_is_ignored(self):
        cv = T.Canvas(4, 1)
        cv.put(0, 5, "越界")
        cv.put(9, 0, "越界")
        self.assertEqual(T.visible_width(cv.render()[0]), 4)

    def test_fill_rect_is_bounded(self):
        cv = T.Canvas(8, 4)
        cv.fill_rect(2, 1, 99, 99, ch="·")
        lines = cv.render()
        self.assertEqual(T.visible_width(lines[0]), 8)
        self.assertIn("·", lines[1])


class SplitColumnsTest(unittest.TestCase):
    def test_widths_sum_with_gaps(self):
        cols = T.split_columns(100, [2, 1, 1], gap=1)
        self.assertEqual(sum(cols) + 1 * (len(cols) - 1), 100)

    def test_single_column_gets_everything(self):
        self.assertEqual(T.split_columns(80, [1]), [80])

    def test_minimum_width_respected(self):
        for width in T.split_columns(30, [3, 1, 1], gap=1):
            self.assertGreaterEqual(width, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
