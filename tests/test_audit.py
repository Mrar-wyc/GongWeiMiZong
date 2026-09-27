"""审计工具自己的测试：这些「闸门」也得能被抓住说谎。

一个扫描器最容易出的毛病不是报错，而是**静默失效**：条件从
`trust_of("X") >= N` 改成 `trust_at_least("X", N)` 之后，靠正则扫源码的
旧版本就再也扫不到任何门槛，却照样打印「审计通过」。
所以这里既验「真剧本能过」，也验「塞一个坏条件进去它真的会红」。
"""

from __future__ import annotations

import contextlib
import io
import unittest

from gongwei.data.story import TOPIC_GATES
from gongwei.game.conditions import has_clue, trust_at_least
from gongwei.game.models import Choice, Content, Dossier, Effect, Scene

from .helpers import load_tool


class GateAuditTest(unittest.TestCase):
    """`tools/audit_gates.py`：引用与信任门槛。"""

    def setUp(self) -> None:
        self.mod = load_tool("audit_gates")
        #: 探针门禁注册进的是**同一个** dict（audit_gates 也是从这里取的）
        self.addCleanup(lambda: TOPIC_GATES.pop("__probe__", None))

    def _run_main(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self.mod.main()
        return code, buf.getvalue()

    def test_the_real_story_passes(self):
        code, out = self._run_main()
        self.assertEqual(code, 0, out)

    def test_the_real_trust_gates_are_actually_found(self):
        """别让扫描器又变成空转：案① 与案② 的信任门槛都得被点出来。"""
        found = {where for where, _who, _need in self.mod.gate_requirements()}
        self.assertIn("话题门禁 xse_fear", found)
        self.assertIn("话题门禁 hxw_fear", found)

    def test_a_typo_in_a_condition_is_caught(self):
        TOPIC_GATES["__probe__"] = (has_clue("no_such_clue_zzz"), "探针")
        problems = self.mod.unknown_ids_in_conditions()
        self.assertTrue(any("no_such_clue_zzz" in p for p in problems), problems)

    def test_an_unreachable_trust_gate_is_caught(self):
        TOPIC_GATES["__probe__"] = (trust_at_least("HXW", 999), "探针")
        code, out = self._run_main()
        self.assertEqual(code, 1, out)
        self.assertIn("上限", out)


class StoryAuditTest(unittest.TestCase):
    """`tools/audit_story.py`：可达性体检。"""

    def setUp(self) -> None:
        self.mod = load_tool("audit_story")

    def test_route_sweep_really_walks_the_routes(self):
        """撒网之外那一条「有人真的这么玩过」的证据，不能是空的。

        案② 加进来之后预算被摊薄，撒网一度把 ``ending_pressured`` /
        ``ending2_pressed`` 这两条**证据薄**的结局漏报成死结局；路线这一遍
        正是为此存在的。所以这里盯两件事：二十条路线一条都不能断，
        而且它们要真的走出一批东西来。
        """
        from gongwei.autoplay import ENDING_ROUTES

        found, broken = self.mod.route_sweep()
        self.assertEqual(broken, [])
        self.assertEqual(found["endings"], set(ENDING_ROUTES))
        self.assertGreater(len(found["scenes"]), 10)
        self.assertGreater(len(found["dossiers"]), 30)

    def test_pack_keeps_the_case_number(self):
        """``pack()`` 丢掉 ``case`` 是个会撒谎的体检。

        它一丢，``from_save()`` 恢复出来的状态就永远停在第一案：
        ``can_read_dossier()`` 会把第六幕以后所有档都挡掉（``dossier_case > case``），
        ``pick_ending()`` 也只在案① 的规则里挑。历史结论「场景 61/63、档案 87/91」
        就是这么来的 —— 不是剧本死了，是尺子坏了。
        """
        content = self.mod.CONTENT
        engine = self.mod.GameEngine(content, gates=TOPIC_GATES)
        engine.new_game()
        engine.state.case = 3
        engine.state.chapter = 11
        raw = self.mod.pack(engine.state)
        self.assertEqual(raw["case"], 3)
        self.assertEqual(raw["chapter"], 11)
        back = type(engine.state).from_save(raw, content)
        self.assertEqual(back.case, 3)
        self.assertEqual(back.chapter, 11)

    def test_the_sweep_can_reach_the_last_case(self):
        """深井：只从开局撒网时，案③ 卷尾那四份总录与「指认陆文昭」轮不到预算。"""
        seeds = self.mod.seed_states()
        self.assertGreaterEqual(len(seeds), 3)
        found = self.mod.search(4000, reverse=False, seed=seeds[-1])
        self.assertIn("verdict3_LWS", found["scenes"])


class LogicAuditTest(unittest.TestCase):
    """`tools/audit_logic.py` 第 1 节：往后推进的后门扫描器。"""

    def setUp(self) -> None:
        self.mod = load_tool("audit_logic")
        self.real = self.mod.CONTENT
        self.addCleanup(lambda: setattr(self.mod, "CONTENT", self.real))

    def _content(self, hub_act: int, side_act: int) -> object:
        """起点 → 侧屋 → 回起点。侧屋那一幕的幕号比起点大，靠幕号判就是后门。"""
        scenes = {
            "hub": Scene(id="hub", title="侧殿", place="", time="", body="",
                         act=hub_act, case=3,
                         choices=[Choice(label="去侧屋", to="side")]),
            "side": Scene(id="side", title="侧屋", place="", time="", body="",
                          act=side_act, case=3,
                          choices=[Choice(label="回侧殿", to="hub")]),
        }
        return Content(items={}, characters={}, scenes=scenes, topics={},
                       endings=[], start_scene="hub", verdict_scene="hub",
                       title="探针", subtitle="", prologue="", version="探针")

    def test_the_real_story_has_no_ungated_shortcut(self):
        self.assertEqual(self.mod.unlocked_progression(), [])

    def test_a_one_way_shortcut_is_still_caught(self):
        """带收益、无门禁、指向图上更晚才到得了的地方 —— 必须报出来。"""
        c = self._content(hub_act=1, side_act=5)
        c.scenes["hub"].choices[0].effect = Effect(scene="side", score=3)
        self.mod.CONTENT = c
        self.assertTrue(self.mod.unlocked_progression())

    def test_a_trip_back_home_is_not_a_shortcut(self):
        """回程不算后门：侧屋那一幕的幕号更大，可它本来就是玩家来的路。"""
        self.mod.CONTENT = self._content(hub_act=3, side_act=2)
        self.assertEqual(self.mod.unlocked_progression(), [])


class DeadEndAuditTest(unittest.TestCase):
    """`tools/audit_logic.py` 第 5 节：软卡出口的三档判定。

    这一节原先只分「有没有档可读」两档，于是开局那份 27 份档一摆，
    「软卡」这行字就恒存在、也就没人看。现在多分一档：**翻开任何一份档
    都不改变任何东西**的软卡才是问题（玩家被钉在原地翻页）。
    """

    def setUp(self) -> None:
        self.mod = load_tool("audit_logic")
        self.real = self.mod.CONTENT
        self.addCleanup(lambda: setattr(self.mod, "CONTENT", self.real))

    def _trap(self, effect: Effect) -> object:
        """一条死巷：没有选项，手上只有一份档可翻。"""
        scenes = {
            "trap": Scene(id="trap", title="死巷", place="", time="", body="",
                          act=1, case=1, choices=[]),
        }
        dossiers = {
            "01-DL-XXX": Dossier(id="01-DL-XXX", title="探针档", act=1,
                                 body="", effect=effect),
        }
        return Content(items={}, characters={}, scenes=scenes, topics={},
                       endings=[], start_scene="trap", verdict_scene="trap",
                       title="探针", subtitle="", prologue="", version="探针",
                       dossiers=dossiers)

    def test_a_flip_that_changes_nothing_is_a_problem(self):
        self.mod.CONTENT = self._trap(Effect())
        _hard, soft, stalled, _states = self.mod.dead_ends(200)
        self.assertEqual(soft, [])
        self.assertEqual(len(stalled), 1)
        self.assertIn("trap", stalled[0])
        self.assertIn("翻", stalled[0])

    def test_a_flip_that_opens_something_is_just_pacing(self):
        self.mod.CONTENT = self._trap(Effect(add_clues=("probe_clue",)))
        _hard, soft, stalled, _states = self.mod.dead_ends(200)
        self.assertEqual(stalled, [])
        self.assertEqual(len(soft), 1)
        self.assertIn("trap", soft[0])

    def test_the_real_story_has_no_flip_inert_dead_end(self):
        """真剧本里每一处「选项全灰」都靠翻档解得开。"""
        _hard, _soft, stalled, states = self.mod.dead_ends(30000)
        self.assertGreater(states, 100)
        self.assertEqual(stalled, [])


if __name__ == "__main__":
    unittest.main()
