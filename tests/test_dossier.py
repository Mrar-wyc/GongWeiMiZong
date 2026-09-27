"""档案层单测：读取、收录、关联计数、检索、存读档、两端宽度一致性。

这一层是 v2 玩法的核心——玩家自己拼档号、自己从正文里推出下一个档号。
测试用手搭的最小剧本，不依赖正式内容，这样机制的问题不会被内容的噪音掩盖。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, ".")

from gongwei.game import GameEngine
from gongwei.game.command import parse
from gongwei.game.engine import DossierState, char_width, display_width
from gongwei.game.models import (
    Character,
    Content,
    Dossier,
    Effect,
    EndingRule,
    Item,
    Scene,
)
from gongwei.game.save import SaveStore
from gongwei.tui.terminal import visible_width


# --------------------------------------------------------------------------
# 最小剧本
# --------------------------------------------------------------------------

def _content() -> Content:
    """四份档案的小剧本：00-readme 开局就有，01→02→03 靠关联串起来。"""
    scenes = {
        "start": Scene(id="start", title="开卷", place="凤仪殿", time="子时三刻",
                       body="案发了。", kind="scene"),
        "ending_ok": Scene(id="ending_ok", title="结局 · 结案", place="", time="",
                           body="结了。", kind="ending"),
    }
    items = {
        "clue_a": Item(id="clue_a", name="线索甲", desc="甲", core=True),
        "clue_b": Item(id="clue_b", name="线索乙", desc="乙"),
    }
    chars = {"WDH": Character(id="WDH", name="王德海", role="太监总管", trust=45)}
    dossiers = {
        "00-readme": Dossier(
            id="00-readme", title="引子", act=1, time_code="00", place_code="RM",
            body="要打开一份档案，就把它的档号敲进来。比如 00-readme。",
            links=("01-FY-WDH",),
            effect=Effect(add_clues=("clue_a",)),
        ),
        "01-FY-WDH": Dossier(
            id="01-FY-WDH", title="凤仪殿 · 王德海的口供", act=1,
            time_code="01", place_code="FY", people=("WDH",),
            body="王德海说：戌时三刻，殿里只有贤妃一人。",
            links=("02-SY-1",),
        ),
        "02-SY-1": Dossier(
            id="02-SY-1", title="尚药局 · 药渣", act=2,
            time_code="02", place_code="SY",
            body="药渣里有一味不该有的东西。",
            links=("03-DL-HD",),
        ),
        "03-DL-HD": Dossier(
            id="03-DL-HD", title="大理寺 · 结案", act=3,
            time_code="03", place_code="DL",
            body="此案到此为止。",
            requires=lambda s: s.has("clue_a") and s.has("clue_b"),
        ),
        # 一份**没有任何关联指向它**的档案：只能靠玩家自己拼出档号，
        # 这正是 Type Help 式「推测」的用武之地。
        "04-XY-1": Dossier(
            id="04-XY-1", title="掖庭 · 无名档", act=3,
            time_code="04", place_code="XY",
            body="这一份不在任何人的册子上。",
        ),
    }
    return Content(
        items=items,
        characters=chars,
        scenes=scenes,
        topics={},
        endings=[EndingRule(id="ending_ok", title="结局 · 结案")],
        start_scene="start",
        verdict_scene="start",
        verdict_scenes=(),
        verdicts={},
        dossiers=dossiers,
        starter_dossiers=("00-readme",),
        act_titles={1: "第一幕 · 开卷", 2: "第二幕 · 查证", 3: "第三幕 · 结案"},
    )


def new_engine() -> GameEngine:
    engine = GameEngine(_content())
    engine.new_game()
    return engine


# --------------------------------------------------------------------------
# 收录与读取
# --------------------------------------------------------------------------


class CollectTest(unittest.TestCase):
    def test_starter_dossier_is_known_but_unread(self):
        engine = new_engine()
        self.assertTrue(engine.state.dossier_known("00-readme"))
        self.assertFalse(engine.state.dossier_read("00-readme"))

    def test_linked_dossier_is_not_known_before_it_is_reached(self):
        engine = new_engine()
        self.assertFalse(engine.state.dossier_known("01-FY-WDH"))

    def test_reading_collects_and_marks_read(self):
        engine = new_engine()
        upd = engine.read_dossier("00-readme")
        self.assertTrue(engine.state.dossier_read("00-readme"))
        self.assertIn("00-readme", upd.new_dossiers)

    def test_reading_applies_the_dossier_effect(self):
        engine = new_engine()
        upd = engine.read_dossier("00-readme")
        self.assertIn("线索甲", upd.new_clues)
        self.assertTrue(engine.state.has("clue_a"))

    def test_reading_a_dossier_reveals_its_links(self):
        """关联档会被登记进档目——但**只有**关联的那一份，不会连锁展开。"""
        engine = new_engine()
        engine.read_dossier("00-readme")
        self.assertTrue(engine.state.dossier_known("01-FY-WDH"))
        self.assertFalse(engine.state.dossier_known("02-SY-1"))

    def test_second_read_does_not_report_a_new_dossier(self):
        engine = new_engine()
        engine.read_dossier("00-readme")
        upd = engine.read_dossier("00-readme")
        self.assertEqual(upd.new_dossiers, [])
        self.assertTrue(any("重阅" in e.text for e in engine.state.log))

    def test_reading_increases_turn_and_sets_open_dossier(self):
        engine = new_engine()
        engine.read_dossier("00-readme")
        self.assertEqual(engine.state.turn, 1)
        self.assertEqual(engine.state.open_dossier, "00-readme")

    def test_close_dossier_clears_the_desk(self):
        engine = new_engine()
        engine.read_dossier("00-readme")
        engine.close_dossier()
        self.assertEqual(engine.state.open_dossier, "")

    def test_reading_an_unknown_id_raises_keyerror(self):
        engine = new_engine()
        with self.assertRaises(KeyError):
            engine.read_dossier("99-XX-YY")


class GuessTest(unittest.TestCase):
    """「推测得来的档案」：档目里没有它，但玩家自己把号拼出来了。

    注意：顺着关联走到的档（`01-FY-WDH` ← `00-readme`、`02-SY-1` ← `01-FY-WDH`）
    **不能**用来测这条——它们在读到前一份时就被收录进档目了，再读不算推测。
    要测推测得挑一份当前**无人揭示**的档，fixture 里是 `04-XY-1`。
    """

    def test_a_dossier_without_requirements_can_be_guessed(self):
        engine = new_engine()
        engine.read_dossier("04-XY-1")
        self.assertTrue(engine.state.dossier_read("04-XY-1"))
        self.assertTrue(engine.state.dossier_guessed("04-XY-1"))
        self.assertFalse(engine.state.dossier_known("04-XY-1"))

    def test_a_link_collected_dossier_is_not_marked_guessed(self):
        """被关联收进档目的档，即使还没读过，也不该被记成推测。"""
        engine = new_engine()
        engine.read_dossier("00-readme")                 # 收 01-FY-WDH
        engine.read_dossier("01-FY-WDH")
        self.assertTrue(engine.state.dossier_known("01-FY-WDH"))
        self.assertFalse(engine.state.dossier_guessed("01-FY-WDH"))

    def test_guessed_dossier_is_not_in_the_index(self):
        engine = new_engine()
        engine.read_dossier("04-XY-1")
        listed = [did for _, rows in engine.dossier_index() for did, _, _, _ in rows]
        self.assertNotIn("04-XY-1", listed)
        self.assertIn("00-readme", listed)

    def test_guessed_read_appends_a_note_to_the_body(self):
        engine = new_engine()
        engine.read_dossier("04-XY-1")
        body = "".join(e.text for e in engine.state.log if e.kind == "dossier")
        self.assertIn("自己把档号拼出来", body)

    def test_requires_gate_blocks_reading_until_satisfied(self):
        engine = new_engine()
        with self.assertRaises(PermissionError):
            engine.read_dossier("03-DL-HD")

    def test_requires_gate_opens_once_the_condition_holds(self):
        engine = new_engine()
        engine.read_dossier("00-readme")           # 得 clue_a
        engine.apply_effect(Effect(add_clues=("clue_b",)))
        self.assertTrue(engine.can_read_dossier("03-DL-HD"))
        engine.read_dossier("03-DL-HD")
        self.assertTrue(engine.state.dossier_read("03-DL-HD"))


# --------------------------------------------------------------------------
# 关联计数与档目
# --------------------------------------------------------------------------


class HintTest(unittest.TestCase):
    def test_hint_counts_only_uncollected_links(self):
        engine = new_engine()
        self.assertEqual(engine.dossier_hints("00-readme"), 1)
        engine.read_dossier("00-readme")
        self.assertEqual(engine.dossier_hints("00-readme"), 0)

    def test_hint_ignores_dangling_links(self):
        """悬空关联不该让计数崩掉——那是审计器该报的错，不是运行时的错。"""
        content = _content()
        content.dossiers["00-readme"] = Dossier(
            id="00-readme", title="引子", act=1, body="…",
            links=("01-FY-WDH", "99-NO-SUCH"),
        )
        engine = GameEngine(content)
        engine.new_game()
        self.assertEqual(engine.dossier_hints("00-readme"), 1)

    def test_index_groups_by_act_in_order(self):
        engine = new_engine()
        engine.read_dossier("00-readme")            # 收 01
        engine.read_dossier("01-FY-WDH")            # 收 02
        acts = [act for act, _ in engine.dossier_index()]
        self.assertEqual(acts, [1, 2])

    def test_index_rows_carry_title_hint_and_read_flag(self):
        engine = new_engine()
        engine.read_dossier("00-readme")
        rows = dict((did, (title, hint, read))
                    for _, group in engine.dossier_index() for did, title, hint, read in group)
        self.assertEqual(rows["00-readme"], ("引子", 0, True))
        self.assertEqual(rows["01-FY-WDH"], ("凤仪殿 · 王德海的口供", 1, False))


# --------------------------------------------------------------------------
# 检索
# --------------------------------------------------------------------------


class SearchTest(unittest.TestCase):
    def test_search_finds_text_in_a_read_dossier(self):
        engine = new_engine()
        engine.read_dossier("00-readme")
        hits = engine.search_dossiers("档号")
        self.assertEqual([did for did, _, _ in hits], ["00-readme"])

    def test_search_does_not_leak_unread_dossiers(self):
        """没读过的档案对玩家还不存在，搜出来就是剧透。"""
        engine = new_engine()
        engine.read_dossier("00-readme")            # 01 已收录但未读
        self.assertEqual(engine.search_dossiers("戌时三刻"), [])

    def test_search_returns_a_snippet_around_the_hit(self):
        engine = new_engine()
        engine.read_dossier("00-readme")
        _, _, snippet = engine.search_dossiers("档号")[0]
        self.assertIn("档号", snippet)

    def test_search_matches_titles_too(self):
        engine = new_engine()
        engine.read_dossier("00-readme")
        engine.read_dossier("01-FY-WDH")
        hits = engine.search_dossiers("口供")
        self.assertIn("01-FY-WDH", [did for did, _, _ in hits])

    def test_empty_search_returns_nothing(self):
        engine = new_engine()
        engine.read_dossier("00-readme")
        self.assertEqual(engine.search_dossiers("   "), [])

    def test_search_is_capped(self):
        engine = new_engine()
        engine.read_dossier("00-readme")
        self.assertLessEqual(len(engine.search_dossiers("的", limit=1)), 1)


# --------------------------------------------------------------------------
# 存档往返
# --------------------------------------------------------------------------


class DossierSaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "d.json")
        self.store = SaveStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_preserves_read_and_guessed(self):
        engine = new_engine()
        engine.read_dossier("00-readme")                 # 收录来的
        engine.read_dossier("04-XY-1")                   # 猜出来的
        self.store.save(engine, stamp="测试")
        back = GameEngine(_content())
        self.store.load(back)
        self.assertTrue(back.state.dossier_read("00-readme"))
        self.assertTrue(back.state.dossier_read("04-XY-1"))
        self.assertTrue(back.state.dossier_guessed("04-XY-1"))
        self.assertFalse(back.state.dossier_known("04-XY-1"))
        self.assertTrue(back.state.dossier_known("01-FY-WDH"))

    def test_round_trip_preserves_notes_and_titles(self):
        engine = new_engine()
        engine.state.notes.append("香炉里有红粉")
        engine.state.dossier_titles["00-readme"] = "我自己取的名字"
        engine.state.act_titles["1"] = "第一幕 · 我取的"
        self.store.save(engine, stamp="测试")
        back = GameEngine(_content())
        self.store.load(back)
        self.assertEqual(back.state.notes, ["香炉里有红粉"])
        self.assertEqual(back.state.title_of_dossier("00-readme"), "我自己取的名字")
        self.assertEqual(back.state.act_title_of(1), "第一幕 · 我取的")

    def test_round_trip_preserves_the_open_dossier(self):
        engine = new_engine()
        engine.read_dossier("00-readme")
        self.store.save(engine, stamp="测试")
        back = GameEngine(_content())
        self.store.load(back)
        self.assertEqual(back.state.open_dossier, "00-readme")

    def test_saved_state_is_json_serialisable(self):
        import json
        engine = new_engine()
        engine.read_dossier("04-XY-1")
        json.dumps(engine.save(), ensure_ascii=False)     # 不抛异常即通过


# --------------------------------------------------------------------------
# 两端宽度一致
# --------------------------------------------------------------------------


class WidthAgreementTest(unittest.TestCase):
    """引擎里的宽度计算必须和终端层给出同样的答案。

    两份实现是有意重复的（引擎不能依赖终端层），所以需要一条测试盯着它们
    别漂开——否则同一条文本在「引擎折行」与「终端排版」之间会错位。
    """

    SAMPLES = [
        "01-FY-WDH · 凤仪殿",
        "王德海说：戌时三刻。",
        "abc ABC 123",
        "，，。！？",
        "「引号」（）【】",
        "混合 mixed 文本 text 123",
        "",
    ]

    def test_char_width_matches_terminal(self):
        for sample in self.SAMPLES:
            for ch in sample:
                self.assertEqual(char_width(ch), visible_width(ch),
                                 f"字符 {ch!r} 的宽度两端不一致")

    def test_display_width_matches_terminal(self):
        for sample in self.SAMPLES:
            self.assertEqual(display_width(sample), visible_width(sample),
                             f"整串 {sample!r} 的宽度两端不一致")


# --------------------------------------------------------------------------
# 指令与档案机制的接口
# --------------------------------------------------------------------------


class CommandToEngineTest(unittest.TestCase):
    """解析器吐出的指令，喂给引擎要能跑通。"""

    def test_parse_then_read(self):
        engine = new_engine()
        cmd = parse("01-FY-WDH")
        self.assertEqual(cmd.kind, "read")
        engine.read_dossier(cmd.arg)
        self.assertTrue(engine.state.dossier_read("01-FY-WDH"))

    def test_full_width_typing_reaches_the_same_dossier(self):
        engine = new_engine()
        cmd = parse("阅 ０１－ＦＹ－ＷＤＨ")
        self.assertEqual(cmd.arg, "01-FY-WDH")
        engine.read_dossier(cmd.arg)
        self.assertTrue(engine.state.dossier_read("01-FY-WDH"))


if __name__ == "__main__":
    unittest.main()
