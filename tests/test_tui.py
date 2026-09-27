"""TUI 交互层单测：标题屏、按键导航、存档确认、帮助层、结局屏。

这里不碰真终端——只驱动 ``GameApp.handle()`` / ``render()``，
所以能在无 console 的环境里跑（CI、管道、重定向都行）。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, ".")

from gongwei.autoplay import ENDING_ROUTES, play
from gongwei.data import CONTENT, TOPIC_GATES
from gongwei.game import GameEngine
from gongwei.game.save import SaveStore
from gongwei.tui.app import (CARD_MARK, CONFIDE_MARK, C_CRIMSON, C_GOLD, C_SCENE,
                             TRUST_BAR_CELLS, TRUST_BAR_EMPTY, TRUST_BAR_FULL, GameApp,
                             _cn_number, _log_entry)
from gongwei.tui.terminal import fg, paint, strip_ansi, visible_width
from tests import helpers

#: 本屏断言有 84 处逐字比屏、还有几处直接比 ANSI（结局印章、名牌、知己符、卡头记号），
#: 所以先把「无色出口」的外部开关摘掉：NO_COLOR 是给玩家用的，CI 或某些终端
#: 工具默认设了它（值为 1），留着会让这些断言依据跑测试的机器不同而红。
os.environ.pop("NO_COLOR", None)


#: 真结局路线。与 tools/walk.py 的 TRUE_ENDING、tests/test_story.py 的同名常量
#: 一致——三处各留一份，是为了让测试文件之间不互相 import（测试之间的隐式
#: 依赖会让「单跑一个文件」的行为和「跑全套」不一样）。
TRUE_ENDING = helpers.preface([
    "前往 · 尚药局", "@0f", "@0f", "@0f",
    "回侧殿", "检查 · 正殿案上的安神茶盏",
    "传唤 · 御膳房", "@0f", "@0f", "@0f", "@0f", "@0f", "作揖告退",
    "前往 · 掖庭", "@0f", "@0f", "回侧殿",
    "传唤 · 太监总管", "@0f", "@0f", "@0f", "@0f", "@0f", "@0f", "作揖告退",
    "求见 · 中宫", "@0f", "@0f", "@0f", "@0f", "作揖告退",
    "求见 · 贵妃", "@0f", "@0f", "作揖告退",
    "求见 · 皇帝", "@0f", "@0f", "作揖告退",
    "回到正殿", "再验一次", "移步侧殿",
    "整理证物", "「凶手是 —— 太监总管",
])


class AppTestCase(unittest.TestCase):
    """每个用例一份独立的临时存档，绝不碰 %USERPROFILE%\\.gongwei。"""

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        os.unlink(self.path)
        self.engine = GameEngine(CONTENT, gates=TOPIC_GATES)
        self.engine.new_game()
        self.store = SaveStore(self.path)
        self.app = GameApp(CONTENT, self.engine, store=self.store)

    def tearDown(self):
        # 必须清掉：本类里有用例会真的写档，留着会污染同进程后续用例的
        # _title_entries()（标题屏会多出「续前案（读档）」，按固定次数的
        # DOWN 就会选错项——曾经因此在屏幕上看到帮助层与标题屏叠加的假乱码）。
        if os.path.exists(self.path):
            os.unlink(self.path)

    # -- 小工具 ----------------------------------------------------------
    def screen(self, width: int = 120, height: int = 34) -> str:
        return "\n".join(strip_ansi(line) for line in self.app.render(width, height).lines)

    def start(self) -> None:
        """从标题屏进入案件。"""
        self.app.handle("ENTER")
        self.assertFalse(self.app.show_title)


class TitleScreenTest(AppTestCase):
    def test_title_screen_is_shown_first(self):
        self.assertTrue(self.app.show_title)
        self.assertIn("宫闱迷踪", self.screen())

    def test_new_case_entries_without_a_save(self):
        self.assertEqual(self.app._title_entries(), ["新案开卷", "玩法说明", "离开"])

    def test_load_entry_appears_only_with_a_save(self):
        self.store.save(self.engine, stamp="测试")
        self.assertIn("续前案（读档）", self.app._title_entries())

    def test_number_key_starts_a_new_case(self):
        self.app.handle("1")
        self.assertFalse(self.app.show_title)
        self.assertEqual(self.engine.state.scene, CONTENT.start_scene)
        self.assertEqual(self.engine.state.turn, 0)

    def test_quit_entry_sets_quit(self):
        # 按标签定位而不是盲数 DOWN：菜单项数会随「有无存档」变化（3 或 4 项），
        # 固定次数在 3 项菜单上会绕回第一项。
        entries = self.app._title_entries()
        for _ in range(entries.index("离开")):
            self.app.handle("DOWN")
        self.app.handle("ENTER")
        self.assertTrue(self.app.quit)

    def test_help_from_title_screen(self):
        self.app.handle("DOWN")          # 玩法说明
        self.app.handle("ENTER")
        self.assertTrue(self.app.help_visible)
        scr = self.screen()
        # 帮助正文是浮层独有的；「玩法说明」是标题屏菜单项，开帮助后会被浮层盖掉。
        self.assertIn("《宫闱迷踪》玩法", scr)
        self.assertIn("按任意键返回", scr)
        # 浮层必须把底层文字彻底盖住：标题屏的序章/副标题不能串进帮助框。
        self.assertNotIn("景和十七年", scr)          # 序章首行
        self.assertNotIn("大理寺仵作", scr)          # 序章第三行
        self.assertNotIn("古风宫廷推理 · 终端探案", scr)   # 副标题
        self.app.handle("ESC")
        self.assertFalse(self.app.help_visible)

    def test_escape_quits_the_title_screen(self):
        self.app.handle("ESC")
        self.assertTrue(self.app.quit)

    def test_loading_from_the_title_screen(self):
        play(self.engine, helpers.OPENING)
        self.store.save(self.engine, stamp="半途")
        other = GameApp(CONTENT, GameEngine(CONTENT, gates=TOPIC_GATES), store=self.store)
        other.handle("DOWN")             # 续前案（读档）
        other.handle("ENTER")
        self.assertFalse(other.show_title)
        self.assertEqual(other.engine.state.scene, self.engine.state.scene)
        self.assertEqual(other.engine.state.clues, self.engine.state.clues)


class GameScreenTest(AppTestCase):
    def test_starting_shows_the_three_panels(self):
        self.start()
        screen = self.screen()
        self.assertIn("卷宗", screen)
        self.assertIn("记事簿", screen)
        self.assertIn("案卷", screen)

    def test_cursor_moves_and_wraps(self):
        self.start()
        total = len(self.app.options())
        self.assertEqual(self.app.cursor, 0)
        self.app.handle("DOWN")
        self.assertEqual(self.app.cursor, 1)
        self.app.handle("UP")
        self.assertEqual(self.app.cursor, 0)
        self.app.handle("UP")            # 回环到最后一个
        self.assertEqual(self.app.cursor, total - 1)

    def test_arrow_keys_walk_the_command_history_when_the_line_has_text(self):
        self.start()
        for ch in "档目":                 # 先敲一条真指令并提交
            self.app.handle(ch)
        self.app.handle("ENTER")
        self.assertIn("档目", self.app.editor.history)
        self.app.handle("银")             # 行里已经有字了
        self.assertEqual(self.app.editor.buffer, "银")
        self.app.handle("UP")             # 这一下该翻历史，不是挪光标
        self.assertEqual(self.app.editor.buffer, "档目")
        self.assertEqual(self.app.cursor, 0, "翻历史不该顺手挪动选项光标")
        self.app.handle("DOWN")           # 再按回来 = 回到还没提交的草稿
        self.assertEqual(self.app.editor.buffer, "银")

    def test_arrow_keys_still_move_the_cursor_on_an_empty_line(self):
        self.start()
        self.app.editor.clear()
        total = len(self.app.options())
        self.app.handle("UP")
        self.assertEqual(self.app.cursor, total - 1, "空行时 ↑ 仍然是选动作")
        self.app.handle("DOWN")
        self.assertEqual(self.app.cursor, 0)

    def test_number_key_picks_a_choice(self):
        self.start()
        self.app.handle("2")             # 空行按数字 = 直接选中第 2 项（询问王德海）
        self.assertIn("王德海供述的时间线",
                      [self.engine.state.clue_name(c) for c in self.engine.state.clues]
                      + [i for i in self.engine.state.clues])

    def test_enter_activates_the_highlighted_choice(self):
        self.start()
        before = self.engine.state.turn
        self.app.handle("ENTER")
        self.assertEqual(self.engine.state.turn, before + 1)
        self.assertEqual(self.app.cursor, 0, "做完一次选择光标要回到第一条")

    def test_first_choice_files_a_clue_and_toasts(self):
        self.start()
        self.app.handle("1")             # 俯身验尸
        self.assertTrue(self.app.toast)
        # clues 里存的是 id；显示名要经 clue_name() 查。
        self.assertIn("si_needle", self.engine.state.clues)
        self.assertEqual(self.engine.state.clue_name("si_needle"), "银针验毒结果")

    def test_help_overlay_opens_and_closes(self):
        self.start()
        self.app.handle("h")
        self.assertTrue(self.app.help_visible)
        self.app.handle("ENTER")
        self.assertFalse(self.app.help_visible)

    def test_scrolling_the_log(self):
        self.start()
        self.assertEqual(self.app.scroll, 0)
        self.app.handle("PGUP")
        self.assertEqual(self.app.scroll, 4)
        self.app.handle("PGDN")
        self.assertEqual(self.app.scroll, 0)
        self.app.handle("PGDN")
        self.assertEqual(self.app.scroll, 0, "卷宗到底后不该出现负数偏移")
        self.app.handle("HOME")
        self.assertGreater(self.app.scroll, 0)
        self.app.handle("END")
        self.assertEqual(self.app.scroll, 0)

    def test_narrow_panel_switch(self):
        self.start()
        self.assertEqual(self.app.panel, "log")
        self.app.handle("c")
        self.assertEqual(self.app.panel, "clues")
        self.app.handle("c")
        self.assertEqual(self.app.panel, "log")

    def test_narrow_clue_panel_actually_draws_the_clues(self):
        """窄屏按 C 之后，屏幕上真的要出现记事簿 —— 不只是内部状态变了。

        原先 `_draw_left()` 收下了 `narrow=True` 却根本没读 `self.panel`：
        按 C 只是把 `app.panel` 改了名，画面一动不动（记事簿在窄屏上等于不存在）。
        """
        self.start()
        play(self.engine, ["俯身验尸"])          # 攒两条线索，记事簿里才有东西
        wide = self.screen(80, 24)
        self.assertIn("卷宗", wide)

        self.app.handle("c")
        self.assertEqual("clues", self.app.panel)
        narrow = self.screen(80, 24)
        self.assertIn("记事簿", narrow)
        self.assertIn("人情", narrow)
        self.assertNotIn("╭─ 卷宗", narrow)          # 卷宗那块面板整块让走了
        self.assertIn("C 回卷宗", narrow)
        # 窄屏也得守住宽度：换面板不能把版面撑破
        for line in self.app.render(80, 24).lines:
            self.assertEqual(80, visible_width(line))

        self.app.handle("c")
        self.assertIn("卷宗", self.screen(80, 24))

    def test_disabled_choice_only_toasts(self):
        self.start()
        play(self.engine, helpers.preface(["传唤 · 太监总管"]))
        self.app.cursor = 0
        locked = [o for o in self.app.options() if not o.enabled]
        self.assertTrue(locked, "审讯里应当有被门禁锁住的话题")
        self.app.cursor = locked[0].index - 1
        before = self.engine.state.turn
        self.app.handle("ENTER")
        self.assertEqual(self.engine.state.turn, before, "锁住的选项不该推进回合")
        self.assertTrue(self.app.toast)

    def test_quit_asks_for_confirmation(self):
        self.start()
        self.app.handle("q")
        self.assertEqual(self.app.pending, "quit")
        self.app.handle("n")
        self.assertIsNone(self.app.pending)
        self.assertFalse(self.app.quit)
        self.app.handle("q")
        self.app.handle("y")
        self.assertTrue(self.app.quit)

    def test_restart_asks_for_confirmation(self):
        self.start()
        play(self.engine, helpers.OPENING)
        self.app.handle("r")
        self.assertEqual(self.app.pending, "new")
        self.app.handle("y")
        self.assertEqual(self.engine.state.turn, 0)
        self.assertEqual(self.engine.state.scene, CONTENT.start_scene)


class SaveKeyTest(AppTestCase):
    def test_s_saves_to_the_isolated_path(self):
        self.start()
        play(self.engine, helpers.OPENING)
        self.app.handle("s")
        self.assertTrue(self.store.exists())
        self.assertFalse(os.path.exists(SaveStore().path),
                         "测试不该写到真实存档路径")

    def test_save_then_load_restores_progress(self):
        self.start()
        play(self.engine, helpers.OPENING)
        self.app.handle("s")
        saved = self.engine.state.to_save()
        # 存档之后再走一步（空行按 1 = 选中「传唤 · 太监总管」），进度必须和档里不一样
        self.app.handle("1")
        self.assertNotEqual(self.engine.state.to_save(), saved)
        self.app.handle("l")
        self.assertEqual(self.app.pending, "load")
        self.app.handle("y")
        # 读档后回到存档那一刻的状态（而不是「和存档前不同」）。
        self.assertEqual(self.engine.state.to_save(), saved)

    def test_load_without_a_save_only_toasts(self):
        self.start()
        self.app.handle("l")
        self.assertIsNone(self.app.pending)
        self.assertTrue(self.app.toast)
        self.assertIn("没有存档", self.app.toast.text)


class EndingScreenTest(AppTestCase):
    def test_accusing_lands_on_an_ending_screen(self):
        self.start()
        play(self.engine, helpers.gate_preface(["移步侧殿", "整理证物", "「凶手是 —— 陛下"]))
        self.app._apply_update(None)
        self.assertTrue(self.engine.state.ending)
        screen = self.screen(100, 30)
        self.assertIn("结局", screen)

    def test_ending_screen_still_answers_quit(self):
        self.start()
        play(self.engine, helpers.gate_preface(["移步侧殿", "整理证物", "「凶手是 —— 陛下"]))
        self.app.handle("q")
        self.assertEqual(self.app.pending, "quit")

    def test_enter_on_an_ending_returns_to_the_title(self):
        self.start()
        play(self.engine, helpers.gate_preface(["移步侧殿", "整理证物", "「凶手是 —— 陛下"]))
        self.app.handle("ENTER")
        self.assertTrue(self.app.show_title)


class RenderSafetyTest(AppTestCase):
    """渲染层不该在任何状态、任何尺寸下抛异常或写坏列。"""

    SIZES = ((120, 34), (96, 30), (80, 24), (62, 18))

    def test_renders_at_every_size_without_error(self):
        for width, height in self.SIZES:
            self.app.show_title = True
            self.app.render(width, height)
            self.start()
            self.app.render(width, height)

    def test_every_line_is_exactly_terminal_width(self):
        self.start()
        play(self.engine, helpers.preface(["传唤 · 太监总管"]))
        for width, height in self.SIZES:
            lines = self.app.render(width, height).lines
            self.assertEqual(len(lines), height)
            for line in lines:
                self.assertEqual(visible_width(line), width)

    def test_help_overlay_fits_every_size(self):
        self.start()
        self.app.help_visible = True
        for width, height in self.SIZES:
            lines = self.app.render(width, height).lines
            self.assertEqual(len(lines), height)
            for line in lines:
                self.assertEqual(visible_width(line), width)

    def test_confirm_dialog_fits_every_size(self):
        self.start()
        self.app.pending = "quit"
        for width, height in self.SIZES:
            lines = self.app.render(width, height).lines
            self.assertEqual(len(lines), height)

    def test_toast_does_not_break_the_layout(self):
        self.start()
        self.app.notify("这是一条很长的提示，用来确认它不会把版面撑破。", "error")
        lines = self.app.render(80, 24).lines
        for line in lines:
            self.assertEqual(visible_width(line), 80)


class ScreenInventorySnapshotTest(AppTestCase):
    """把**每一种**屏幕状态都照一遍相，逐个尺寸验宽度。

    别的渲染测试只覆盖「启动」和「通关」两个状态；真正的排版事故大多出在
    少见的那几屏：帮助浮层、确认框、toast、窄屏切到记事簿、八个结局屏
    （结局正文长短差很多）、以及停在判决过渡场景的那一瞬。

    每屏都验三件事：
    1. 行数 == 高度、每行可视宽度 == 宽度（宽字符算两格）；
    2. 同一状态连渲两次逐字相同（没有隐藏的随机/时间依赖）；
    3. 在 120×34 上该出现的关键字样真的出现（防止「不崩但是空白」）。
    """

    SIZES = ((120, 34), (100, 30), (96, 24), (80, 24), (62, 18))

    def _fresh(self, played=None):
        """造一个全新的 app；``played`` 是先在引擎上走完的步骤。

        每个屏幕都必须**独立**构造：早期版本里各 maker 共用并改写同一个
        `self.app`，于是「标题屏有存档」把存档写下了，后面的「标题屏+帮助」
        菜单里就多出「续前案（读档）」，按两次 DOWN 直接读档进了游戏，
        于是断言找不到帮助浮层的字样。屏幕之间不能有这种暗耦合。
        """
        engine = GameEngine(CONTENT, gates=TOPIC_GATES)
        engine.new_game()
        app = GameApp(CONTENT, engine, store=SaveStore(self.path))
        if played:
            play(engine, played)
            app.show_title = False
        return app

    # -- 各屏的构造器：返回 (屏幕名, app, 必须出现的字样) ----------------
    def _title(self):
        return "标题屏", self._fresh(), ["宫闱迷踪", "新案开卷"]

    def _title_with_save(self):
        app = self._fresh(["俯身验尸"])
        self.assertTrue(self.store.save(app.engine, stamp="测试"))
        return "标题屏（有存档）", self._fresh(), ["续前案（读档）"]

    def _title_help(self):
        app = self._fresh()
        # 按标签定位，不盲数 DOWN：有存档时菜单会多一项。
        entries = app._title_entries()
        for _ in range(entries.index("玩法说明")):
            app.handle("DOWN")
        app.handle("ENTER")
        return "标题屏 + 帮助浮层", app, ["《宫闱迷踪》玩法", "按任意键返回"]

    def _game_opening(self):
        app = self._fresh()
        app.handle("ENTER")              # 新案开卷
        return "开局卷宗", app, ["卷宗", "记事簿", "案卷", "俯身验尸"]

    def _game_after_choices(self):
        return "走过序章后的卷宗", self._fresh(helpers.OPENING), ["人情"]

    def _game_scrolled(self):
        app = self._fresh(helpers.OPENING)
        app.handle("HOME")
        return "卷宗翻到卷首", app, []

    def _clues_panel(self):
        app = self._fresh(helpers.OPENING)
        app.handle("c")
        return "窄屏记事簿面板", app, []

    def _help_overlay(self):
        app = self._fresh(helpers.OPENING)
        app.handle("h")
        return "游戏中 + 帮助浮层", app, ["《宫闱迷踪》玩法", "按任意键返回"]

    def _confirm_quit(self):
        app = self._fresh()
        app.handle("ENTER")              # 先离开标题屏，否则 q 是「退出标题屏」
        app.handle("q")
        return "退出确认框", app, ["确认"]

    def _confirm_restart(self):
        app = self._fresh()
        app.handle("ENTER")
        app.handle("r")
        return "重来确认框", app, ["确认"]

    def _toast(self):
        app = self._fresh()
        app.handle("ENTER")
        app.handle("1")                  # 俯身验尸 → 线索 toast
        return "线索 toast", app, []

    def _toast_locked(self):
        app = self._fresh(helpers.preface(["传唤 · 太监总管"]))
        locked = [o for o in app.options() if not o.enabled]
        self.assertTrue(locked, "审讯里本该有被门禁锁住的话题")
        app.cursor = locked[0].index - 1
        app.handle("ENTER")
        return "门禁 toast", app, []

    def _interrogation(self):
        app = self._fresh(helpers.preface(["传唤 · 太监总管"]))
        return "审讯场景", app, ["王德海"]

    def _at_verdict(self):
        """停在判决过渡场景：无选项、kind=scene，是最少见的一屏。"""
        app = self._fresh(TRUE_ENDING[:-1])
        app.engine.accuse("WDH")
        self.assertTrue(app.engine.at_verdict())
        return "判决过渡场景", app, []

    def _endings(self):
        # 路线表取自 ``gongwei.autoplay.ENDING_ROUTES``：与 ``test_story`` 的
        # 「二十条路线 → 二十个结局」用的是同一份，不在这里另抄一遍。
        declared = {e.id for e in CONTENT.endings}
        assert set(ENDING_ROUTES) == declared, (set(ENDING_ROUTES) ^ declared)
        out = []
        for eid, steps in ENDING_ROUTES.items():
            app = self._fresh(steps)
            assert app.engine.state.ending == eid, (eid, app.engine.state.ending)
            out.append((f"结局屏 {eid}", app, [CONTENT.scenes[eid].title]))
        return out

    def _screens(self):
        makers = [
            self._title, self._title_with_save, self._title_help,
            self._game_opening, self._game_after_choices, self._game_scrolled,
            self._clues_panel, self._help_overlay, self._confirm_quit,
            self._confirm_restart, self._toast, self._toast_locked,
            self._interrogation, self._at_verdict,
        ]
        for maker in makers:
            yield maker()
        for screen in self._endings():
            yield screen

    def test_every_screen_has_exact_dimensions_at_every_size(self):
        checked = 0
        for name, app, _marks in self._screens():
            for width, height in self.SIZES:
                lines = app.render(width, height).lines
                self.assertEqual(len(lines), height,
                                 f"「{name}」在 {width}x{height} 的行数不是 {height}")
                for index, line in enumerate(lines):
                    got = visible_width(line)
                    self.assertEqual(
                        got, width,
                        f"「{name}」在 {width}x{height} 第 {index} 行宽度 {got}≠{width}：{line!r}")
                checked += 1
        self.assertGreater(checked, 90, "屏幕×尺寸的组合太少，覆盖不够")

    def test_every_screen_renders_deterministically(self):
        for name, app, _marks in self._screens():
            for width, height in ((120, 34), (62, 18)):
                self.assertEqual(app.render(width, height).lines,
                                 app.render(width, height).lines,
                                 f"「{name}」在 {width}x{height} 两次渲染不一致")

    def test_full_size_screens_show_their_key_content(self):
        """宽度对了不等于画对了：大尺寸下关键字样必须真的在。"""
        for name, app, marks in self._screens():
            screen = "".join(strip_ansi(x) for x in app.render(120, 34).lines)
            for mark in marks:
                self.assertIn(mark, screen, f"「{name}」屏幕上找不到「{mark}」")

    def test_overlays_cover_what_is_underneath_them(self):
        """浮层必须抹底：底下的标题屏文字不能串进帮助框或确认框。"""
        leaks = ("景和十七年", "大理寺仵作", "古风宫廷推理 · 终端探案")

        help_app = self._title_help()[1]
        screen = "".join(strip_ansi(x) for x in help_app.render(120, 34).lines)
        for leak in leaks:
            self.assertNotIn(leak, screen, f"标题屏的「{leak}」透进了帮助浮层")

        confirm_app = self._confirm_quit()[1]
        screen = "".join(strip_ansi(x) for x in confirm_app.render(120, 34).lines)
        for leak in leaks:
            self.assertNotIn(leak, screen, f"标题屏的「{leak}」透进了确认框")


class ReadingPaneTest(AppTestCase):
    """宽屏阅读区：敲档号看档案、敲档目看目录、打错要有回话。

    这一组是补的**回归闸**。原先 `app.py` 里有两个 `_draw_left()`，旧的那个
    悄悄顶掉了带阅档功能的新版：敲档号之后引擎里 `open_dossier` 明明换了、
    `read_mode` 也成了 `dossier`，屏幕上却还是卷轴日志。引擎全对、屏幕全错，
    而当时的测试只看「行数与宽度对不对」，于是一片全绿。
    所以这里断言的是**屏幕上真的出现了档案正文**，不是内部状态。
    """

    def _type(self, text: str) -> None:
        """逐字敲进命令行（模拟真人按键，不走内部快捷方法）。"""
        for ch in text:
            self.app.handle(ch)

    def _pane_title(self, width: int = 120, height: int = 34) -> str:
        """取出左栏标题行里的名字，例如「╭─ ◆ 档案 ────╮」→「档案」。

        卡头那个朱砂 ◆（`CARD_MARK`）是记号、不是名字的一部分，这里照剥。
        """
        first = strip_ansi(self.screen(width, height).split("\n")[1])
        head = first.split("╭", 1)[1] if "╭" in first else first
        return head.strip("─ ").split("─")[0].strip().removeprefix(CARD_MARK).strip()

    def test_every_pane_header_carries_the_crimson_mark(self):
        """卡头符号：卷宗／记事簿／人情／案卷四块面板，标题前都是一个朱砂 ◆。"""
        self.start()
        raw = "\n".join(self.app.render(120, 34).lines)
        plain = strip_ansi(raw)
        for title in ("卷宗", "记事簿", "人情", "案卷"):
            self.assertIn(f"╭─ {CARD_MARK} {title} ", plain, f"{title} 的卡头记号没了")
        self.assertIn(fg(C_CRIMSON) + f" {CARD_MARK} ", raw, "记号该是朱砂色的")

        self._type("01-FY-XFE")
        self.app.handle("ENTER")
        self.assertIn(f"╭─ {CARD_MARK} 档案 ",
                      strip_ansi("\n".join(self.app.render(120, 34).lines)))

    def test_typing_a_dossier_id_shows_its_body_on_screen(self):
        self.start()
        self.assertEqual("卷宗", self._pane_title())

        self._type("01-FY-XFE")               # 开局就收录的两份之一
        self.app.handle("ENTER")

        self.assertEqual("dossier", self.app.read_mode)
        self.assertEqual("01-FY-XFE", self.engine.state.open_dossier)
        self.assertEqual("档案", self._pane_title())
        screen = self.screen()
        self.assertIn("尸格 · 贤妃苏氏", screen)      # 标题行
        self.assertIn("苏氏，年二十有七", screen)      # 正文
        self.assertIn("01-FY-XFE-2", screen)         # 顺链可查的那几份

    def test_the_dossier_starts_at_the_top_and_scrolls_downward(self):
        """档案是文档，不是聊天记录：打开要**从标题读起**，PgDn 往下走。"""
        self.start()
        self._type("01-FY-XFE")
        self.app.handle("ENTER")

        # 大窗口：整份档案都放得下
        wide = self.screen(120, 34)
        self.assertIn("01-FY-XFE · 尸格 · 贤妃苏氏", wide)     # 第一行就在屏幕上
        self.assertEqual(0, self.app.scroll)
        self.app.handle("PGUP")
        self.assertEqual(0, self.app.scroll, "已经在顶上，PgUp 不该乱跑")

        # 小窗口：放不下，PgDn 才看得出来往下走了
        small_top = self.screen(100, 20)
        self.app.handle("PGDN")
        self.assertEqual(4, self.app.scroll)
        self.assertNotEqual(small_top, self.screen(100, 20), "PgDn 之后画面得真的动")
        self.app.handle("HOME")
        self.assertEqual(0, self.app.scroll)
        self.assertEqual(small_top, self.screen(100, 20), "HOME 回到文档开头")
        self.app.handle("END")
        self.assertGreater(self.app.scroll, 0)
        self.assertNotEqual(small_top, self.screen(100, 20), "END 跳到文档末尾")
        self.app.handle("HOME")
        self.assertEqual(small_top, self.screen(100, 20))

        # 卷宗仍是老语义：PgUp 往更旧的日志走
        self.app.handle("ESC")
        self.assertEqual("log", self.app.read_mode)
        self.app.handle("PGUP")
        self.assertGreater(self.app.scroll, 0)

    def test_wrapped_body_lines_align_under_the_first_line(self):
        """折行不再每行顶一个「▤」：只有段首带记号，段内其余行缩进对齐。"""
        self.start()
        self._type("01-FY-XFE")
        self.app.handle("ENTER")

        rows = [strip_ansi(x) for x in self.app._reading_rows(76)]
        view = self.engine.dossier_view("01-FY-XFE", 74)
        # dossier_view 已经折过行；空行分段，所以记号数 = 段数
        blocks = sum(1 for i, line in enumerate(view)
                     if line and (i == 0 or not view[i - 1]))
        self.assertEqual(blocks, sum(1 for r in rows if "▤" in r),
                         "记号数应等于段数（每段一个 ▤，折行不重复）")

        painted = [r for r in rows if r.strip()]
        self.assertLess(len([r for r in rows if "▤" in r]), len(painted),
                        "每一行都顶着记号 —— 折行又被当成新段落了")
        indented = [r for r in rows if r.startswith("  ") and "▤" not in r]
        self.assertTrue(indented, "没有一行是缩进的续行，折行缩进大概没生效")
        for r in indented:
            self.assertTrue(r[2:].strip(), f"缩进行是空的：{r!r}")

    def test_index_command_lists_the_dossier_tree(self):
        self.start()
        self._type("档目")
        self.app.handle("ENTER")

        self.assertEqual("index", self.app.read_mode)
        self.assertEqual("档目", self._pane_title())
        screen = self.screen()
        self.assertIn("第一幕 · 贤妃薨", screen)
        self.assertIn("01-DL-SMB", screen)

    def test_search_command_lists_hits(self):
        self.start()
        self._type("01-FY-XFE")
        self.app.handle("ENTER")              # 先读一份，检索才有米下锅
        self._type("搜 苏氏")
        self.app.handle("ENTER")

        self.assertEqual("search", self.app.read_mode)
        self.assertEqual("检索", self._pane_title())
        self.assertIn("在已收集的档案里查「苏氏」", self.screen())

    def test_escape_closes_the_dossier_and_the_pane_goes_back_to_the_log(self):
        self.start()
        self._type("01-FY-XFE")
        self.app.handle("ENTER")
        self.assertEqual("档案", self._pane_title())

        self.app.handle("ESC")
        self.assertEqual("log", self.app.read_mode)
        self.assertEqual("卷宗", self._pane_title())
        self.assertEqual("", self.engine.state.open_dossier)

    def test_a_typo_gets_an_answer_instead_of_silence(self):
        self.start()
        self._type("01-FY-XXA")
        self.app.handle("ENTER")

        self.assertEqual("log", self.app.read_mode)      # 没进阅档
        screen = self.screen()
        self.assertIn("01-FY-XXA", screen)               # 报错里带上了敲的号
        # 近似档号应当被提示出来：01-FY-XFE
        self.assertIn("01-FY-XFE", screen)

    def test_every_reading_mode_keeps_the_layout_intact(self):
        """四种阅读模式 × 五种尺寸：不越界、不崩、标题跟着模式走。"""
        for command, mode, title in (("01-FY-XFE", "dossier", "档案"),
                                     ("档目", "index", "档目")):
            for width, height in ((120, 34), (100, 30), (96, 24), (80, 24), (62, 18)):
                app = self._fresh_app()
                app.handle("ENTER")                      # 进案件
                for ch in command:
                    app.handle(ch)
                app.handle("ENTER")
                self.assertEqual(mode, app.read_mode, f"{command} @ {width}x{height}")
                lines = app.render(width, height).lines
                self.assertEqual(height, len(lines))
                for line in lines:
                    self.assertEqual(width, visible_width(line),
                                     f"{command} @ {width}x{height} 越界：{strip_ansi(line)!r}")
                if width >= 96:
                    self.assertIn(title, strip_ansi("\n".join(lines)))
                if hasattr(app, "shutdown"):
                    app.shutdown()

    def _fresh_app(self):
        """另一份干净的 app（同一个存档路径，但引擎是新的）。"""
        engine = GameEngine(CONTENT, gates=TOPIC_GATES)
        engine.new_game()
        return GameApp(CONTENT, engine, store=self.store)


class DisplayedDataTest(AppTestCase):
    """三件「数据早就有了、界面从没画过」的东西。

    说话人名牌、结案评语印章、可深谈标记都只读数据：名字、评语、案号、门槛
    全部取自 ``CONTENT``，写死一个都会让这些断言失去意义。
    """

    SIZES = ((120, 34), (96, 30), (80, 24), (62, 18))

    # -- 取屏幕 ---------------------------------------------------------
    def raw(self, width: int = 120, height: int = 34) -> str:
        """连 ANSI 一起取屏幕——名牌与标记的颜色只有原始行里才有。"""
        return "\n".join(self.app.render(width, height).lines)

    def plain(self, width: int = 120, height: int = 34) -> str:
        return strip_ansi(self.raw(width, height))

    def say(self, name: str, words: str, bracketed: bool = True) -> None:
        head = f"「{name}」：" if bracketed else f"{name}："
        self.engine.state.log.append(_log_entry("scene", head + words))

    def _npc(self):
        """一个会说话的配角（信任 > 0，不是玩家本人）。"""
        return next(c for c in CONTENT.characters.values() if c.trust > 0)

    def _ranked_ending(self):
        return next(e for e in CONTENT.endings if e.rank)

    def _play_ending(self, rule) -> None:
        self.start()
        play(self.engine, ENDING_ROUTES[rule.id])
        self.app._apply_update(None)
        self.assertEqual(rule.id, self.engine.state.ending)

    # -- 1. 说话人名牌 ---------------------------------------------------
    def test_a_dialogue_line_gets_a_nameplate(self):
        ch = self._npc()
        self.start()
        self.say(ch.name, "他说的话。")

        raw = self.raw()
        self.assertIn(paint(f"{ch.name}：", C_GOLD, bold=True), raw)   # 名字上金
        self.assertIn(paint("他说的话。", C_SCENE), raw)               # 台词转正白
        self.assertIn(f"{ch.name}：他说的话。", self.plain())

    def test_the_bracketless_name_form_is_a_speaker_too(self):
        ch = self._npc()
        self.start()
        self.say(ch.name, "不带括号也认。", bracketed=False)
        self.assertIn(paint(f"{ch.name}：", C_GOLD, bold=True), self.raw())

    def test_a_bracket_that_is_not_a_character_stays_narration(self):
        self.start()
        self.engine.state.log.append(_log_entry("scene", "「要静心抄经」：这不是谁在说话。"))

        self.assertNotIn(paint("要静心抄经：", C_GOLD, bold=True), self.raw())
        self.assertIn("「要静心抄经」：这不是谁在说话。", self.plain())

    # -- 2. 结案评语印章 -------------------------------------------------
    def test_the_ending_screen_shows_the_rank_seal(self):
        rule = self._ranked_ending()
        self._play_ending(rule)
        label = f"【{rule.rank}】案{_cn_number(rule.case)}"

        lines = [strip_ansi(line) for line in self.app.render(120, 34).lines]
        self.assertTrue(any(label in line for line in lines), f"结案屏上没有评语印章：{label}")
        seal_row = next(i for i, line in enumerate(lines) if label in line)
        self.assertLessEqual(seal_row, 5, "印章该贴在卷宗上沿、正文之前")
        raw = "\n".join(self.app.render(120, 34).lines)
        self.assertIn(fg(C_GOLD) + "\x1b[1m" + f"【{rule.rank}】", raw, "印章该是金色加粗的")

    def test_the_seal_rank_and_case_come_from_the_data(self):
        seen = set()
        for rule in CONTENT.endings:
            if not rule.rank or rule.case in seen:
                continue
            seen.add(rule.case)
            with self.subTest(ending=rule.id):
                engine = GameEngine(CONTENT, gates=TOPIC_GATES)
                engine.new_game()
                play(engine, ENDING_ROUTES[rule.id])
                app = GameApp(CONTENT, engine, store=self.store)
                app.show_title = False
                text = strip_ansi("\n".join(app.render(120, 34).lines))
                self.assertIn(f"【{rule.rank}】案{_cn_number(rule.case)}", text)

    def test_no_ending_and_no_rule_means_no_seal(self):
        self.start()
        self.assertIsNone(self.app._rank_seal())             # 还没结案
        rule = self._ranked_ending()
        self.engine.state.ending = "no-such-ending"          # 查不到的结局号
        self.assertIsNone(self.app._rank_seal())
        self.assertNotIn(f"【{rule.rank}】案{_cn_number(rule.case)}", self.plain())

    # -- 3. 可深谈标记 ---------------------------------------------------
    def _mark_ansi(self) -> str:
        """金色加粗的那颗点。

        Canvas 落字时会省掉紧跟换色之后的 RESET，所以这里只比对前缀——
        它同样能证明这颗点不是普通正文，而是上了色、加粗的标记。
        """
        return fg(C_GOLD) + "\x1b[1m" + CONFIDE_MARK

    def _marked_rows(self) -> list:
        return [strip_ansi(line) for line in self.app.render(120, 34).lines
                if CONFIDE_MARK in strip_ansi(line)]

    def test_the_confide_mark_lights_up_exactly_at_the_threshold(self):
        cast = [c for c in CONTENT.characters.values()
                if self.engine.state.case in getattr(c, "case", (1,))]
        ready = next(c for c in cast if c.confide_at != 999)
        mark = self._mark_ansi()
        full_bar = TRUST_BAR_FULL * TRUST_BAR_CELLS

        self.start()
        self.assertEqual(0, self.raw().count(mark), "开局谁也不该是可深谈")
        self.engine.state.trust[ready.id] = ready.confide_at - 1
        self.assertEqual(0, self.raw().count(mark), "差一分就不该亮")
        self.assertNotIn(full_bar, self.plain(), "差一分，七格就不该走满")
        self.engine.state.trust[ready.id] = ready.confide_at

        self.assertEqual(1, self.raw().count(mark), "到线必须亮，而且只亮这一颗")
        marked = self._marked_rows()
        self.assertEqual(1, len(marked), "只该有一个人是可深谈")
        self.assertIn(ready.name, marked[0], "亮起来的该是他自己那一行")
        self.assertIn(CONFIDE_MARK, marked[0])
        self.assertIn(full_bar, self.plain(), "到线那七格该走满")
        self.assertIn(fg(C_GOLD) + "\x1b[1m" + full_bar, self.raw(), "走满的七格该是描金的")

    def test_a_never_confide_character_never_lights_up(self):
        never = next(c for c in CONTENT.characters.values() if c.confide_at == 999)
        self.start()
        self.engine.state.trust[never.id] = 100

        self.assertFalse(self.app._confide_ready(never, 100), "999 是「永不可深谈」")
        rows = [strip_ansi(line) for line in self.app.render(120, 34).lines]
        self.assertTrue([r for r in rows if never.name in r
                         and TRUST_BAR_EMPTY * TRUST_BAR_CELLS in r],
                        f"{never.name} 信任满了也该照常列在人情栏里，条子则永远空着")
        self.assertEqual(0, self.raw().count(self._mark_ansi()))
        self.assertEqual([], self._marked_rows())

    # -- 4. 四个尺寸的宽度不变量 -----------------------------------------
    def test_dialogue_lines_keep_every_line_exactly_terminal_width(self):
        ch = self._npc()
        engine = GameEngine(CONTENT, gates=TOPIC_GATES)
        engine.new_game()
        engine.state.log.append(_log_entry("scene", f"「{ch.name}」：四个尺寸都要看得见。"))
        app = GameApp(CONTENT, engine, store=self.store)
        app.show_title = False

        self._assert_widths(app, "对话", expects=(paint(f"{ch.name}：", C_GOLD, bold=True),))

    def test_the_ending_screen_keeps_every_line_exactly_terminal_width(self):
        rule = self._ranked_ending()
        ch = self._npc()
        engine = GameEngine(CONTENT, gates=TOPIC_GATES)
        engine.new_game()
        play(engine, ENDING_ROUTES[rule.id])
        # 结案之后卷宗里再落一句对话：一个屏幕上同时有印章和名牌的极端情况
        engine.state.log.append(_log_entry("scene", f"「{ch.name}」：结案之后还得说一句。"))
        app = GameApp(CONTENT, engine, store=self.store)
        app.show_title = False

        self._assert_widths(app, "结案",
                            expects=(f"【{rule.rank}】", paint(f"{ch.name}：", C_GOLD, bold=True)))

    def _assert_widths(self, app, tag: str, expects=()) -> None:
        for width, height in self.SIZES:
            lines = app.render(width, height).lines
            self.assertEqual(height, len(lines), f"{tag} @ {width}x{height} 行数不对")
            for line in lines:
                self.assertEqual(width, visible_width(line),
                                 f"{tag} @ {width}x{height} 越界：{strip_ansi(line)!r}")
            text = "\n".join(lines)
            for want in expects:
                self.assertIn(want, text, f"{tag} @ {width}x{height} 缺内容")
        if hasattr(app, "shutdown"):
            app.shutdown()


class DossierSpeakerPlateTest(AppTestCase):
    """档案正文里的说话人名牌（``_reading_rows`` 的 dossier 分支）。

    ``DisplayedDataTest`` 那一组钉的是**卷宗日志**那条路（``_log_lines``）。档案
    正文走的是另一条分支，必须单独钉：哪天有人把它改回「整段一个颜色」，日志里的
    名牌照样全绿，档案里却不再有人名 —— 那正是「引擎全对、屏幕全错」的老坑。
    """

    #: 与 DisplayedDataTest 共用同一组尺寸，免得两份清单各自漂移。
    SIZES = DisplayedDataTest.SIZES

    #: Canvas 落字时会省掉紧跟换色之后的 RESET，所以只比对转义前缀。
    PLATE = fg(C_GOLD) + "\x1b[1m"

    # -- 取样：档号与名字一个都不写死，全从剧本里现找 ---------------------
    def _names(self) -> list:
        """人物表里的名字（长的排前面，和界面那套一致，免得短名抢长名的开头）。"""
        return sorted({ch.name for ch in CONTENT.characters.values()}, key=len, reverse=True)

    def _speaker_lines(self) -> list:
        """剧本里以「真名：」开头的正文行（含缩进写的那种）—— 名牌该亮的就是这些。"""
        names = self._names()
        return [(did, line)
                for did, dossier in CONTENT.dossiers.items()
                for line in (dossier.body or "").split("\n")
                if any(line.strip().startswith(f"{name}：") for name in names)]

    def _early_colon_narration(self, did: str) -> list:
        """这份档案里「冒号落在前 12 字内、前缀却不是人名」的旁白（反面样本）。"""
        names = self._names()
        found = []
        for line in (CONTENT.dossiers[did].body or "").split("\n"):
            text = line.strip()
            at = text.find("：")
            if not text or at < 0 or at > 12:
                continue
            if not any(text.startswith(f"{name}：") for name in names):
                found.append(text)
        return found

    def _plates(self, raw: str) -> list:
        """原始文本里所有「金色加粗」的片段（截到 RESET 或行尾为止）。"""
        found, at = [], raw.find(self.PLATE)
        while at >= 0:
            found.append(raw[at + len(self.PLATE):].split("\x1b", 1)[0])
            at = raw.find(self.PLATE, at + 1)
        return found

    # -- 小工具 ----------------------------------------------------------
    def _read(self, did: str) -> list:
        """敲档号读一份档案（先让引擎认识它），返回阅读区的原始行。"""
        self.engine.collect_dossier(did)
        # 前面挂个「阅」字：命令行空着时「1-9」是选项快捷键（``_handle_game`` 里那一支），
        # 直接敲 10-DL-SMB 会把首位的 1 吃掉、只剩 0-DL-SMB。「阅 <档号>」是玩家真会用的路。
        for ch in f"阅{did}":
            self.app.handle(ch)
        self.app.handle("ENTER")
        self.assertEqual("dossier", self.app.read_mode, f"{did} 没读开")
        self.assertEqual(did, self.engine.state.open_dossier)
        return self.app._reading_rows(76)

    def _assert_plates_are_names(self, rows: list, tag: str) -> list:
        """阅读区里每一处金色加粗，都必须正好是「人物表里的真名 + 全角冒号」。"""
        plates = self._plates("\n".join(rows))
        for plate in plates:
            self.assertTrue(plate.endswith("："),
                            f"{tag}：金色加粗的不是「名字：」：{plate!r}")
            # 缩进写的供词，名牌里带着段首空白——名字要 strip 之后才对得上人物表。
            self.assertIn(plate[:-1].strip(), self._names(),
                          f"{tag}：名牌上的「{plate[:-1]}」不在人物表里")
        return plates

    # -- 1. 正面：行首人名上金加粗，其余照旧 -----------------------------
    def test_a_dossier_body_speaker_line_gets_a_gold_nameplate(self):
        samples = self._speaker_lines()
        self.assertTrue(samples, "剧本里一份带说话人的档案都没有，这条用例就白写了")
        self.start()
        for did, line in samples:
            with self.subTest(dossier=did, line=line):
                text = line.strip()
                lead = line[: len(line) - len(text)]
                name = text.split("：", 1)[0]
                rest = text[len(name) + 1:]
                rows = self._read(did)
                row = next(r for r in rows if strip_ansi(r).endswith(line))
                # 段落记号（▤ / 两格缩进）原样留着，名牌那一截上金加粗，其余照旧；
                # 源数据自带的段首空白也算名牌的一部分，屏幕上还是那些空格。
                mark = "▤ " if strip_ansi(row).startswith("▤ ") else "  "
                self.assertEqual(paint(mark, C_GOLD)
                                 + paint(lead + f"{name}：", C_GOLD, bold=True)
                                 + paint(rest, C_GOLD),
                                 row, "「金名加粗 + 其余照旧」没做全")
                self._assert_plates_are_names(rows, did)

    def test_the_nameplate_actually_reaches_the_screen(self):
        did, line = self._speaker_lines()[0]
        plate = line[: line.index("：") + 1]     # 名牌 = 这一行「名字：」那一截（含缩进）
        self.start()
        self._read(did)

        raw = "\n".join(self.app.render(120, 34).lines)
        self.assertIn(self.PLATE + plate, raw, "屏幕上没有金色加粗的名牌")
        self.assertIn(line, strip_ansi(raw), "正文一个字都不该被改动")

    # -- 2. 反面：全篇旁白，一处都不许沾金 -------------------------------
    def test_no_narration_in_the_whole_corpus_gets_a_nameplate(self):
        """名牌只认人物表里的名字，不认「第一个冒号」。

        反面样本是「结案文书上写的是：……」那一类旁白：冒号落得很早，前缀却不是
        人名。这里把 91 份档案全读一遍，逐份比对「亮起来的金名」与「剧本里写着
        的说话人行（缩进的也算）」是否**完全相同** —— 多了是误伤，少了是漏画。
        """
        want = {}
        for did, line in self._speaker_lines():
            want.setdefault(did, []).append(line.strip().split("：", 1)[0])

        self.start()
        checked = 0
        for did in CONTENT.dossiers:
            negatives = self._early_colon_narration(did)
            checked += len(negatives)
            rows = self._read(did)
            plain = strip_ansi("\n".join(rows))
            plates = self._assert_plates_are_names(rows, did)
            with self.subTest(dossier=did):
                self.assertEqual(sorted(want.get(did, [])),
                                 sorted(p[:-1].strip() for p in plates),
                                 "金名的处数与剧本里的说话人行对不上")
                for text in negatives:
                    head = text[: text.find("：") + 1]
                    self.assertNotIn(self.PLATE + head, "\n".join(rows),
                                     f"旁白「{head}」被当成了说话人")
                    self.assertIn("".join(text.split()), "".join(plain.split()),
                                  "旁白要一字不少地照旧显示")
        self.assertGreater(checked, 0, "全篇一个反面样本都没有，这条用例失去了靶子")

    # -- 3. 四个尺寸：宽度不变量 + 金名该在的地方还在 --------------------
    def test_the_dossier_pane_keeps_every_line_exactly_terminal_width(self):
        """档案正文这条路扫四个尺寸：一格不越界，金名该露面时真露面。

        62x18 上正文行进不了屏（选项区把阅读区挤到只剩档头与元信息两行），所以这
        里按「屏幕上真出现金名」计数、要求至少露面一次，宽度不变量则四个尺寸一个
        不落 —— 那才是 ``ReadingPaneTest`` 钉住的对齐契约。
        """
        did, line = self._speaker_lines()[0]
        plate = line[: line.index("：") + 1]
        self.start()
        self._read(did)

        seen = 0
        for width, height in self.SIZES:
            lines = self.app.render(width, height).lines
            self.assertEqual(height, len(lines), f"档案 @ {width}x{height} 行数不对")
            for one in lines:
                self.assertEqual(width, visible_width(one),
                                 f"档案 @ {width}x{height} 越界：{strip_ansi(one)!r}")
            raw = "\n".join(lines)
            if self.PLATE + plate in raw:
                seen += 1
                self.assertIn(line, strip_ansi(raw), f"金名那行的正文被改动了 @ {width}x{height}")
        self.assertGreater(seen, 0, "四个尺寸都没把金名摆上屏幕，这个扫描等于没扫")


if __name__ == "__main__":
    unittest.main(verbosity=2)
