"""剧本完整性、真结局通关路线与渲染快照。

这一层是「这部游戏真的玩得通吗」的守门人：
- 剧本里每一处场景/话题/物品/结局的互相引用都必须能解析；
- 49 步的真结局路线必须稳定走到「铁证如山」；
- 几个主要岔路的结局必须各自可达（同一个 bug 曾经让所有指认都判成「查不出来」）；
- 四栏/三栏/窄屏多种终端尺寸下的每一行都必须严格等于终端宽度。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, ".")

from gongwei.autoplay import CASE3_ROUTE, ENDING_ROUTES, play
from gongwei.autoplay import TRUE_ENDING as _TRUE_ENDING
from gongwei.data import CONTENT, TOPIC_GATES
from gongwei.game import GameEngine
from gongwei.game.save import SaveStore
from gongwei.tui.app import GameApp, render_screen
from gongwei.tui.terminal import visible_width

from tests import helpers


#: 真结局路线：与 ``tools/walk.py``、``tools/audit_web.py`` 取的是
#: ``gongwei.autoplay`` 里那**同一份**定义，不在这里另抄。
TRUE_ENDING = list(_TRUE_ENDING)


def new_engine() -> GameEngine:
    engine = GameEngine(CONTENT, gates=TOPIC_GATES)
    engine.new_game()
    return engine


class ContentIntegrityTest(unittest.TestCase):
    """剧本自身的引用完整性——写错一个 id 就会在玩到那一步时才炸。"""

    def test_start_and_verdict_scenes_exist(self):
        self.assertIn(CONTENT.start_scene, CONTENT.scenes)
        self.assertIn(CONTENT.verdict_scene, CONTENT.scenes)
        self.assertIn(CONTENT.interrogate_hall, CONTENT.scenes)

    def test_every_scene_reference_resolves(self):
        for scene in CONTENT.scenes.values():
            for choice in scene.choices:
                target = choice.effect.scene or choice.to
                if target:
                    self.assertIn(target, CONTENT.scenes,
                                  f"{scene.id} 的选项「{choice.label}」指向不存在的场景 {target}")

    def test_every_choice_effect_names_real_ids(self):
        for scene in CONTENT.scenes.values():
            for choice in scene.choices:
                for cid in choice.effect.add_clues:
                    self.assertIn(cid, CONTENT.items,
                                  f"{scene.id}「{choice.label}」加了不存在的线索 {cid}")
                for iid in choice.effect.add_items:
                    self.assertIn(iid, CONTENT.items,
                                  f"{scene.id}「{choice.label}」加了不存在的物证 {iid}")
                for cid, _delta in choice.effect.trust:
                    self.assertIn(cid, CONTENT.characters,
                                  f"{scene.id}「{choice.label}」改了不存在的角色 {cid}")

    def test_every_topic_points_at_a_real_character_and_clue(self):
        for topic in CONTENT.topics.values():
            self.assertIn(topic.owner, CONTENT.characters)
            for cid in topic.effect.add_clues:
                self.assertIn(cid, CONTENT.items)

    def test_topic_labels_are_globally_unique(self):
        """话题标签不许重名：玩家问过的话题是按「::标签」记进 ``seen_choices`` 的。

        两个人物只要用了同一句话（案① 的小顺子与案② 的贺小五都写过
        「你在怕谁」），后一个人的那一问就会被当成「已经问过了」而收起来——
        不是报错，是那句台词永远不出现。这类 bug 只有在玩到那里时才看得见。
        """
        seen = {}
        for topic in CONTENT.topics.values():
            if topic.label in seen:
                self.fail(f"话题标签重复：「{topic.label}」"
                          f"（{seen[topic.label]} 与 {topic.id}）")
            seen[topic.label] = topic.id

    def test_every_verdict_scene_is_reachable_by_a_suspect(self):
        # 「场景存在」不算数：每一张判决屏都要真的有人指认得进去，
        # 否则它就是一段谁也看不到的死文案（这条测试曾只断言存在）。
        targets = set()
        suspects = set()
        for scene in CONTENT.scenes.values():
            for choice in scene.choices:
                if not choice.suspect:
                    continue
                suspects.add(choice.suspect)
                targets.add(choice.effect.scene or choice.to)
        for scene in CONTENT.verdict_scenes:
            self.assertIn(scene, CONTENT.scenes)
            self.assertIn(scene, targets,
                          f"判决屏 {scene} 没有任何一条指认选项通向它")
        for suspect, row in CONTENT.verdicts.items():
            self.assertIn(suspect, suspects,
                          f"verdicts 里的 {suspect} 没有任何指认选项")
            self.assertIn(row[0], CONTENT.verdict_scenes)

    def test_the_two_ways_to_a_verdict_screen_agree(self):
        # 「谁指认 → 进哪张判决屏」有两条实现：`Content.verdicts` 字典与
        # `Choice.suspect + effect.scene`。字典指向的那张屏必须真的有人指认得进去
        # （冯保、萧衍在两案各有一张屏，所以这里是「在其中」而不是「只有它」）。
        by_suspect: dict = {}
        for scene in CONTENT.scenes.values():
            for choice in scene.choices:
                if choice.suspect:
                    by_suspect.setdefault(choice.suspect, set()).add(
                        choice.effect.scene or choice.to)
        for suspect, row in CONTENT.verdicts.items():
            self.assertIn(suspect, by_suspect,
                          f"verdicts 里的 {suspect} 没有任何指认选项")
            self.assertIn(row[0], by_suspect[suspect],
                          f"verdicts 把 {suspect} 指向 {row[0]}，"
                          f"但指认 {suspect} 的选项只通向 {sorted(by_suspect[suspect])}")

    def test_core_total_matches_the_item_table(self):
        core = [i for i in CONTENT.items.values() if i.core]
        self.assertEqual(CONTENT.core_total(), len(core))
        self.assertGreater(CONTENT.core_total(), 0)

    def test_every_ending_has_a_scene_and_a_unique_id(self):
        ids = [e.id for e in CONTENT.endings]
        self.assertEqual(len(ids), len(set(ids)))
        for ending in CONTENT.endings:
            self.assertIn(ending.id, CONTENT.scenes,
                          f"结局 {ending.id} 没有对应的场景正文")

    def test_every_ending_rule_is_a_callable(self):
        for ending in CONTENT.endings:
            self.assertTrue(callable(ending.rule), f"结局 {ending.id} 缺判定规则")


class TrueEndingTest(unittest.TestCase):
    """49 步真结局路线——一旦哪条线索或门禁被改坏，这里立刻变红。"""

    @classmethod
    def setUpClass(cls):
        cls.engine = new_engine()
        play(cls.engine, TRUE_ENDING)

    def test_lands_on_restitution(self):
        self.assertEqual(self.engine.state.ending, "ending_restitution")

    #: 案① 的核心线索条数。案② 的那 22 条不在这条路线上——这趟差事不去尚药局；
    #: 两案合起来拿满 43 条由 ``EverythingRouteTest`` 负责。
    CASE1_CORE = 21

    def test_collects_every_core_clue_of_the_first_case(self):
        self.assertEqual(self.engine.state.core_count(), self.CASE1_CORE)

    def test_records_the_real_culprit(self):
        self.assertEqual(self.engine.state.accused, "WDH")
        self.assertIn("wdh_confessed", self.engine.state.flags)

    def test_scores_well(self):
        self.assertGreaterEqual(self.engine.state.score, 90)

    def test_ending_scene_is_current(self):
        self.assertEqual(self.engine.state.scene, "ending_restitution")


class BranchingEndingTest(unittest.TestCase):
    """正殿指认是四条互斥的岔路，每条都要落到自己的结局上。"""

    def play_to(self, *steps):
        engine = new_engine()
        play(engine, helpers.preface(["整理证物"] + list(steps)))
        return engine

    def test_accusing_wang_with_decisive_evidence_alone(self):
        """只拿到「只有凶手知晓之事」就指认 → 尘埃落定（够不上铁证如山）。"""
        engine = new_engine()
        state = engine.state
        state.accused = "WDH"
        state.flags.add("accused")
        state.clues += ["si_needle", "black_blood", "window_scratch",
                        "tea_almond", "censer_red", "pillow_letter", "killer_knowledge"]
        self.assertEqual(engine.finalize(), "ending_standard")

    def test_accusing_wang_right_after_the_gate(self):
        """过门槛后立刻指认王德海：核心够多，但缺「只有凶手知晓之事」→ 按下。

        三种指认王德海的路子现在是一条台阶：缺决定性证据 → 按下；
        有它 → 尘埃落定；再加动机、玉扳指、口供 → 铁证如山。
        """
        engine = new_engine()
        play(engine, helpers.gate_preface(["移步侧殿", "整理证物", "「凶手是 —— 太监总管"]))
        self.assertGreaterEqual(engine.state.core_count(), 6)
        self.assertNotIn("killer_knowledge", engine.state.clues)
        self.assertEqual(engine.state.ending, "ending_pressured")

    def test_accusing_the_emperor(self):
        engine = self.play_to("「凶手是 —— 陛下")
        self.assertEqual(engine.state.ending, "ending_treason")

    def test_accusing_the_consort(self):
        engine = self.play_to("「凶手是 —— 贵妃")
        self.assertEqual(engine.state.ending, "ending_false")

    def test_giving_up(self):
        engine = self.play_to("「此案 —— 暂无确证")
        self.assertEqual(engine.state.ending, "ending_bystander")

    def test_resigning(self):
        engine = self.play_to("「臣 —— 验得出来")
        self.assertEqual(engine.state.ending, "ending_quiet")

    def test_endings_are_all_distinct_strings(self):
        """同样证据下，四个指认/放弃分支必须落在四个互不相同的结局上。"""
        seen = set()
        for label in ("「凶手是 —— 陛下", "「凶手是 —— 贵妃",
                      "「此案 —— 暂无确证", "「臣 —— 验得出来"):
            engine = self.play_to(label)
            self.assertNotIn(engine.state.ending, seen,
                             f"「{label}」与前面的岔路撞了同一个结局")
            seen.add(engine.state.ending)
        self.assertEqual(len(seen), 4)


class RenderSnapshotTest(unittest.TestCase):
    """渲染快照：尺寸严格、不崩、结局屏照得出。"""

    SIZES = ((120, 34), (96, 30), (80, 24), (62, 18))

    def _isolated_app(self, engine) -> GameApp:
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        os.unlink(path)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return GameApp(CONTENT, engine, store=SaveStore(path))

    def test_every_size_produces_exact_width(self):
        for width, height in self.SIZES:
            engine = new_engine()
            app = self._isolated_app(engine)
            lines = app.render(width, height).lines
            self.assertEqual(len(lines), height, f"{width}x{height} 行数不对")
            for index, line in enumerate(lines):
                self.assertEqual(
                    visible_width(line), width,
                    f"{width}x{height} 第 {index} 行可视宽度 {visible_width(line)} 不符：{line!r}")

    def test_every_size_survives_the_whole_true_ending_route(self):
        """终点屏（长结局正文）也必须严格贴合宽度。"""
        for width, height in self.SIZES:
            engine = new_engine()
            play(engine, TRUE_ENDING)
            app = self._isolated_app(engine)
            lines = app.render(width, height).lines
            self.assertEqual(len(lines), height)
            for line in lines:
                self.assertEqual(visible_width(line), width)

    def test_title_screen_snapshot_is_stable(self):
        engine = new_engine()
        app = self._isolated_app(engine)
        first = app.render(100, 30).lines
        second = app.render(100, 30).lines
        self.assertEqual(first, second, "同一状态下两次渲染必须逐字相同")

    def test_title_screen_shows_the_title(self):
        engine = new_engine()
        app = self._isolated_app(engine)
        screen = "".join(app.render(100, 30).lines)
        self.assertIn("宫闱迷踪", screen)
        self.assertIn("新案开卷", screen)

    def test_starting_the_case_leaves_the_title_screen(self):
        engine = new_engine()
        app = self._isolated_app(engine)
        app.handle("ENTER")
        self.assertFalse(app.show_title)
        screen = "".join(app.render(120, 34).lines)
        self.assertIn("卷宗", screen)
        self.assertIn("案卷", screen)

    def test_render_screen_helper_matches_app_render(self):
        engine = new_engine()
        app = self._isolated_app(engine)
        self.assertEqual(render_screen(CONTENT, engine, 90, 26, app=app),
                         app.render(90, 26).lines)


class SaveResumeFidelityTest(unittest.TestCase):
    """存读档保真：读回来的档必须和「从没存过档」的那一局完全一致。

    `SaveTest` 只验字段往返，这里验的是**行为**：在路线中途存档、读进一个
    全新的引擎、接着走完，终局的 state 必须与一口气走完的同一条路线逐字段
    相同。差一个 flag、一个 seen_choices、一个 trust，后面某道门禁就会
    悄悄开或关——这类 bug 单看存档文件是看不出来的。

    已知边界：`to_save()` 只保留最后 160 条日志，所以 `log` 的比较也只在
    这个窗口内成立；本测试用的是 49 步路线，尾窗不会因为读档而错位。
    """

    def _save_isolated(self):
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        os.unlink(path)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return SaveStore(path)

    def test_resuming_midroute_matches_an_uninterrupted_run(self):
        reference = new_engine()
        play(reference, TRUE_ENDING)

        halfway = len(TRUE_ENDING) // 2
        engine = new_engine()
        play(engine, TRUE_ENDING[:halfway])

        store = self._save_isolated()
        self.assertTrue(store.save(engine), "中途存档失败")

        resumed = GameEngine(CONTENT, gates=TOPIC_GATES)
        resumed.new_game()
        ok, why = store.load(resumed)
        self.assertTrue(ok, f"读档失败：{why}")
        play(resumed, TRUE_ENDING[halfway:])

        self.assertEqual(resumed.state.to_save(), reference.state.to_save(),
                         "读档接着走完的终局与一口气走完的不一致")

    def test_resuming_is_visible_in_the_very_next_options(self):
        """读档后立刻能看见的选项必须与存档那一刻完全一样（含门禁提示）。"""
        halfway = len(TRUE_ENDING) // 2
        engine = new_engine()
        play(engine, TRUE_ENDING[:halfway])
        want = [(o.label, o.enabled, o.hint) for o in engine.options()]

        store = self._save_isolated()
        self.assertTrue(store.save(engine))

        resumed = GameEngine(CONTENT, gates=TOPIC_GATES)
        resumed.new_game()
        self.assertTrue(store.load(resumed)[0])
        got = [(o.label, o.enabled, o.hint) for o in resumed.options()]
        self.assertEqual(got, want, "读档后的选项表与存档那一刻不一致")

    def test_saving_at_the_verdict_then_resuming_still_settles_the_ending(self):
        """停在判决过渡场景时存档，读回来必须自己补上结局。

        `accuse()` 只把人带到 `verdict_WDH` 这类过渡场景（无选项、kind=scene），
        正常游玩时 `autoplay.play` / 界面的 handle 会立刻 `finalize()` 把它结算掉。
        存档恰好卡在这一瞬间时，读档必须补上结算——这条分支只在这里被覆盖。
        """
        engine = new_engine()
        play(engine, TRUE_ENDING[:-1])          # 差最后一步指认
        engine.accuse("WDH")
        self.assertTrue(engine.at_verdict(), f"本该停在判决过渡场景，实为 {engine.state.scene}")
        self.assertEqual(engine.state.ending, "", "过渡场景不该已经带结局")

        store = self._save_isolated()
        self.assertTrue(store.save(engine))

        resumed = GameEngine(CONTENT, gates=TOPIC_GATES)
        resumed.new_game()
        ok, why = store.load(resumed)
        self.assertTrue(ok, f"读档失败：{why}")
        self.assertEqual(resumed.state.ending, "ending_restitution",
                         "停在判决处存档，读回来没有补上结局")
        self.assertFalse(resumed.at_verdict(), "结算之后不该还停在过渡场景")

    def test_resuming_does_not_replay_the_scene_body(self):
        """读档不该把已经念过的场景正文再念一遍。"""
        engine = new_engine()
        play(engine, ["俯身验尸"])
        before = sum(1 for e in engine.state.log if e.kind == "scene")

        store = self._save_isolated()
        self.assertTrue(store.save(engine))

        resumed = GameEngine(CONTENT, gates=TOPIC_GATES)
        resumed.new_game()
        self.assertTrue(store.load(resumed)[0])
        self.assertEqual(sum(1 for e in resumed.state.log if e.kind == "scene"),
                         before, "读档后场景正文被重复记入日志")

    def test_every_prefix_of_the_true_ending_route_round_trips(self):
        """路线上**任意一步**存档读档，都必须无损——不是只有中点。"""
        store = self._save_isolated()
        for cut in range(1, len(TRUE_ENDING)):
            engine = new_engine()
            play(engine, TRUE_ENDING[:cut])
            self.assertTrue(store.save(engine), f"第 {cut} 步存档失败")

            resumed = GameEngine(CONTENT, gates=TOPIC_GATES)
            resumed.new_game()
            ok, why = store.load(resumed)
            self.assertTrue(ok, f"第 {cut} 步读档失败：{why}")
            self.assertEqual(
                resumed.state.to_save(), engine.state.to_save(),
                f"在第 {cut} 步存档读档后状态不一致")
            self.assertEqual(
                [(o.label, o.enabled, o.hint) for o in resumed.options()],
                [(o.label, o.enabled, o.hint) for o in engine.options()],
                f"在第 {cut} 步读档后选项表不一致")


class EveryEndingReachableTest(unittest.TestCase):
    """三案十九个结局**全部**要能从真实操作走出来。

    单独看每个结局的规则很容易以为都没问题；真正会漏的是「某条路被中间
    的门禁悄悄堵死」。这里把每条路都走一遍，并且要求十九个结局一个不落。

    案① 的八条都在第一案里收场；案② 的五条要先借案① 的门槛进尚药局——
    所以它们的前缀取自 ``CASE2_SHORT_HEAD``（案① 查到手 + 进案② 的最小走法）；
    案③ 的六条再从案② 的结案厅进门，前缀是 ``CASE3_HEAD``。
    """

    def test_every_topic_can_actually_be_asked(self):
        """四十四条话题都要有一条真实路线问得出来。

        门禁「够得着」不等于「问得到」：贵妃那条「今夜还有谁在凤仪殿」要
        好感 ≥ 25 而安胎药那一问会 −5，先问安胎药就再也问不出来了——
        剧本一直没报错，是可达性体检（``tools/audit_story.py``）先报的
        「话题 20/20 → 32/33」。所以这里钉死一条真的问遍全部话题的路线。

        案③ 进来之后这条路线要多走两案（``CASE3_ROUTE``）：案③ 的四场问询
        是**最后一个案子的最后一批话题**，只有三案连打才问得全。
        """
        engine = new_engine()
        engine, _ = play(engine, CASE3_ROUTE)
        asked = set(engine.state.topics_asked)
        self.assertEqual(asked, set(CONTENT.topics),
                         f"这条路线没问出来的话题：{set(CONTENT.topics) - asked}")

    def test_every_ending_is_reachable_by_real_play(self):
        """十九条真实操作路线 → 十九个结局，一一对应。

        路线表本身在 ``gongwei/autoplay.py`` 的 ``ENDING_ROUTES`` 里
        （终端快照与可达性体检取的是同一份），这里只负责「走一遍、对一遍」。

        用字典而不是列表，是为了在断言失败时直接看出「哪条路走到了哪」，
        而不是只报一句「不相等」。正确的 id 取自 `CONTENT.endings`。
        """
        routes = ENDING_ROUTES
        declared = {e.id for e in CONTENT.endings}
        self.assertEqual(set(routes), declared,
                         f"测试没覆盖到的结局：{declared - set(routes)}；"
                         f"测试里写错的 id：{set(routes) - declared}")

        wrong = {}
        for expected, steps in routes.items():
            got = play(new_engine(), steps)[0].state.ending
            if got != expected:
                wrong[expected] = got
        self.assertEqual(wrong, {},
                         "这些路线没有走到预期结局（键=预期，值=实际）："
                         + "，".join(f"{k}→{v}" for k, v in wrong.items()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
