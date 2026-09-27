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
from gongwei.game.conditions import always, has_clue, trust_at_least
from gongwei.game.models import Choice, Content, Dossier, Effect, Scene

from .helpers import load_tool


class WebOptionTableTest(unittest.TestCase):
    """`tools/audit_web.py` 的选项表：可见行 + 最后一行隐藏清单。

    门禁改成「藏起来」之后，可见行恒 ``enabled=True`` / ``hint=""``，
    光比这几行证明不了「两端藏的是不是同一批」——`web/src/driver.js` 追加的最后
    一行 ``["hidden", 标签…]`` 才是那件事的证据。这里盯住它的形状与顺序。
    """

    def setUp(self) -> None:
        self.mod = load_tool("audit_web")

    def test_the_hidden_row_is_present_and_in_engine_order(self):
        engine = self.mod.GameEngine(self.mod.build_content(), gates=TOPIC_GATES)
        engine.new_game()
        table = self.mod.option_table(engine)
        self.assertTrue(table, "选项表不能是空的")
        self.assertEqual(table[-1][0], "hidden")
        self.assertEqual(table[-1][1:],
                         [o.label for o in engine.hidden_options()])
        self.assertTrue(table[-1][1:], "开局就有一批门禁挡着，隐藏清单不该是空的")
        for row in table[:-1]:
            self.assertEqual(row[2:], [True, ""], row)


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

    def test_the_opening_screen_has_a_well_per_branch(self):
        """案② 开场那一屏的岔路各有一口井，值房那道门才证明得了能开。

        值房「查值夜簿上的签押」是 ``missing_any_clue("night_roster2")`` 挡的：
        草草拐进值房时值夜簿还没到手，它本就该在桌上。深度优先在那一屏上只往下
        走第一条岔路（药库），这一刻就永远轮不到预算 —— 少了这口井，它会被错报成
        「从未解开过的门禁」。所以这里盯住井的**状态**（值房 + 值夜簿不在手上），
        而不是只盯它数出了什么。
        """
        seeds = self.mod.seed_states()
        fresh = [s for s in seeds
                 if s["scene"] == "night_room"
                 and "night_roster2" not in s["clues"]]
        self.assertTrue(fresh, "开场屏第二条岔路没有起点：值房那道门没人证明得了能开")
        # 两条新岔路各站着一个起点：值房与账房（药库那条是「案② 药局前厅」那口井）。
        scenes = {s["scene"] for s in seeds}
        self.assertLessEqual({"night_room", "drug_office"}, scenes)
        found = self.mod.search(200, reverse=False, seed=fresh[0])
        self.assertIn(("night_room", "查值夜簿上的签押"), found["open"])

    def test_the_hidden_gate_tally_is_not_a_dead_audit(self):
        """门禁数的是 `hidden_options()`，不能退化成恒空。

        旧口径按 ``not opt.enabled`` 数，而引擎现在**根本不产出**灰置选项 ——
        照旧写就会一行都数不到，体检却照样打印「[从未解开过的门禁] 无」。
        所以这里盯两遍：挡过的那批要数得到（``blocked`` 非空），而且同一格要在
        别的可达状态里亮过（开局那道 ``missing_dossier`` 门槛正是这样：先被挡，
        读全第一幕的档之后进 ``open``）。
        """
        found = self.mod.search(1500, reverse=False)
        self.assertTrue(found["blocked"], "被挡过的门禁一处都没数到：这份审计已经空转")
        start = self.mod.CONTENT.start_scene
        spot = next((s for s in found["blocked"]
                     if s[0] == start and s[1].startswith("移步侧殿")), None)
        self.assertIsNotNone(spot, sorted(found["blocked"]))
        self.assertIn(spot, found["open"], "开局那道门槛读全档案之后就该亮起来")

    def test_a_gate_that_never_opens_is_reported(self):
        """恒暗的门禁（谁也点不开）必须被报出来 —— 这份审计存在的理由。"""
        scenes = {
            "start": Scene(id="start", title="门厅", place="", time="", body="",
                           act=1, case=1,
                           choices=[Choice(label="推门", to="inner")]),
            "inner": Scene(id="inner", title="内室", place="", time="", body="",
                           act=1, case=1,
                           choices=[Choice(label="暗门", to="start",
                                           locked_if=always)]),
        }
        probe = Content(items={}, characters={}, scenes=scenes, topics={},
                        endings=[], start_scene="start", verdict_scene="start",
                        title="探针", subtitle="", prologue="", version="探针")
        self.addCleanup(setattr, self.mod, "CONTENT", self.mod.CONTENT)
        self.mod.CONTENT = probe
        found = self.mod.search(200, reverse=False)
        self.assertIn(("start", "推门"), found["open"])
        self.assertIn(("inner", "暗门"), found["blocked"])
        never = self.mod.never_unlocked(found["blocked"], found["open"], set())
        self.assertEqual(set(never), {("inner", "暗门")})

    def test_a_gate_opened_elsewhere_is_not_a_dead_gate(self):
        """同一个文本在别的场景亮过、或路线里真点过，都不算「从未解开」。"""
        blocked = {("s1", "移步"): 3, ("s2", "验尸"): 1}
        never = self.mod.never_unlocked(blocked, {("s1", "移步")}, set())
        self.assertNotIn(("s1", "移步"), never, "同格后来亮过，不该算死门")
        self.assertIn(("s2", "验尸"), never, "它谁也没亮过，必须留着")
        never = self.mod.never_unlocked(blocked, set(), {"验尸"})
        self.assertNotIn(("s2", "验尸"), never, "路线里真点过，不该算死门")
        self.assertEqual(set(self.mod.never_unlocked(blocked, set(), set())),
                         set(blocked))


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

    入口判据也跟着门禁的语义换了口径：不再是「选项全灰」而是**这一屏一个可见选项
    都没有**（`not engine.options()`）——被门禁挡住的选择不上桌，也就不算出口。
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

    def _hidden_door(self) -> object:
        """唯一的出口被门禁藏着：这一屏没有可见选项，也没有档可翻。"""
        scenes = {
            "trap": Scene(id="trap", title="死巷", place="", time="", body="",
                          act=1, case=1,
                          choices=[Choice(label="推门", to="trap",
                                          locked_if=always)]),
        }
        return Content(items={}, characters={}, scenes=scenes, topics={},
                       endings=[], start_scene="trap", verdict_scene="trap",
                       title="探针", subtitle="", prologue="", version="探针")

    def test_a_hidden_exit_is_not_an_exit(self):
        """门禁没开的选择不算出口：这格按「没有可见选项」判进硬死那一档。"""
        self.mod.CONTENT = self._hidden_door()
        hard, soft, stalled, _states = self.mod.dead_ends(200)
        self.assertEqual(len(hard), 1)
        self.assertIn("trap", hard[0])
        self.assertEqual(soft, [])
        self.assertEqual(stalled, [])

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
        """真剧本里每一处「没有可见选项」都靠翻档解得开。"""
        _hard, _soft, stalled, states = self.mod.dead_ends(30000)
        self.assertGreater(states, 100)
        self.assertEqual(stalled, [])


if __name__ == "__main__":
    unittest.main()
