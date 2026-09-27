"""引擎与存档单测：选项可见性/门禁、指认、结局判定、存读档往返。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, ".")

from gongwei.autoplay import WalkError, play, resolve
from gongwei.data import CONTENT, TOPIC_GATES
from gongwei.game import GameEngine
from gongwei.game.save import SAVE_VERSION, SaveStore, default_save_path

from tests import helpers



def new_engine() -> GameEngine:
    engine = GameEngine(CONTENT, gates=TOPIC_GATES)
    engine.new_game()
    return engine


def walk(steps):
    engine = new_engine()
    return play(engine, steps)


def label_of(engine: GameEngine, prefix: str):
    hits = [o for o in engine.options() if o.label.startswith(prefix)]
    if len(hits) != 1:
        raise AssertionError(f"{prefix} 匹配 {len(hits)} 项")
    return hits[0]


class OpeningTest(unittest.TestCase):
    def test_starts_at_crime_scene(self):
        engine = new_engine()
        self.assertEqual(engine.state.scene, CONTENT.start_scene)
        self.assertEqual(engine.state.scene, "crime_scene")

    def test_opening_body_is_logged_once(self):
        engine = new_engine()
        bodies = [e for e in engine.state.log if e.kind == "scene"]
        self.assertEqual(len(bodies), 1)

    def test_opening_keeps_the_gated_option_out_of_sight(self):
        """开局五项目光所及，第六项「移步侧殿」被第一幕门槛挡在桌下——看不见，也不灰着。

        门槛是 `missing_dossier(FIRST_ACT_SUMMARY)`——没读全勘验格目就走不掉，
        所以这一项**本来**就不该出现在玩家眼前；原因仍写在 `hidden_options()` 里，
        只给审计与排障看。
        """
        engine = new_engine()
        opts = engine.options()
        self.assertEqual(len(opts), 5, [o.label for o in opts])
        self.assertTrue(all(o.enabled for o in opts), "摆出来的选项不该有灰的")
        hidden = engine.hidden_options()
        gated = [o for o in hidden if o.label.startswith("移步侧殿")]
        self.assertEqual(len(gated), 1, [o.label for o in hidden])
        self.assertTrue(gated[0].hint, "门禁要给开发者留下可读的原因")
        self.assertFalse([o for o in opts if o.label.startswith("移步侧殿")])

    def test_first_choice_grants_core_clues(self):
        engine = new_engine()
        upd = label_of(engine, "俯身验尸").action()
        self.assertIn("银针验毒结果", upd.new_clues)
        self.assertIn("口角黑血", upd.new_clues)
        self.assertEqual(engine.state.core_count(), 2)

    def test_asking_wang_for_a_timeline_shakes_him(self):
        engine = new_engine()
        before = engine.state.trust_of("WDH")
        label_of(engine, "询问王德海").action()
        self.assertLess(engine.state.trust_of("WDH"), before)

    def test_in_place_action_disappears_once_its_clue_is_taken(self):
        """回归：原地动作曾把 to/effect.scene 都指向本场景，选项永不消失。"""
        engine = new_engine()
        label_of(engine, "俯身验尸").action()
        left = [o for o in engine.options() if o.label.startswith("俯身验尸")]
        self.assertEqual(left, [])

    def test_turn_advances_per_choice(self):
        engine = new_engine()
        label_of(engine, "俯身验尸").action()
        self.assertEqual(engine.state.turn, 1)
        label_of(engine, "细查门窗").action()
        self.assertEqual(engine.state.turn, 2)


class GateTest(unittest.TestCase):
    def test_unknown_topic_prefix_raises(self):
        engine = new_engine()
        with self.assertRaises(WalkError):
            resolve(engine, "这个选项不存在")

    def test_gated_topic_never_shows_up(self):
        """门禁没开的话题不摆在桌上——不灰着，也不带提示。

        回归：被门禁锁住的话题曾被 `seen_choices` 直接吃掉，玩家看不到提示；
        现在的口径是「没开就不显示」，原因只写进 `hidden_options()`。
        """
        engine = new_engine()
        play(engine, helpers.preface(["传唤 · 太监总管"]))
        visible = {o.label for o in engine.options()}
        hidden = [o for o in engine.hidden_options() if o.hint]
        self.assertTrue(hidden, "审讯里应当至少有一个被门禁挡住的话题")
        self.assertFalse([o for o in hidden if o.label in visible], "挡住的不能同时露在桌上")
        self.assertTrue(visible, "总还有问得出口的话")

    def test_asking_a_topic_marks_it_asked(self):
        engine = new_engine()
        play(engine, helpers.preface(["传唤 · 太监总管"]))
        first = [o for o in engine.options() if o.enabled and not o.asked]
        self.assertTrue(first)
        first[0].action()
        self.assertTrue(engine.state.topics_asked, "问过的话题应记进 topics_asked")

    def test_asked_topic_disappears_unless_gated(self):
        """问过的话题要收起来；被门禁挡住的本来就没摆出来。"""
        engine = new_engine()
        play(engine, helpers.preface(["传唤 · 太监总管"]))
        before = len([o for o in engine.options() if not o.asked])
        [o for o in engine.options() if not o.asked][0].action()
        after = len([o for o in engine.options() if not o.asked])
        self.assertEqual(after, before - 1)

    def test_skipping_evidence_keeps_the_present_topic_hidden(self):
        """没去尚药局拿领用簿，王德海的「出示」话题就不该露面。"""
        engine = new_engine()
        play(engine, helpers.preface(["传唤 · 太监总管"]))
        self.assertFalse([o for o in engine.options() if "出示" in o.label])
        hidden = [o for o in engine.hidden_options() if "出示" in o.label]
        self.assertTrue(hidden, "挡住的「出示」话题应当留在 hidden_options() 里")


class HiddenGateTest(unittest.TestCase):
    """门禁不显示：全剧本扫一遍——可见的没有灰项，挡住的都只在隐藏清单里。"""

    def test_no_scene_shows_a_gated_choice(self):
        checked = 0
        gated_seen = 0
        for sid, scene in CONTENT.scenes.items():
            if scene.kind == "ending":
                continue
            engine = new_engine()
            engine.state.scene = sid
            visible = [o for o in engine.options()]
            hidden = [o for o in engine.hidden_options()]
            labels = [o.label for o in visible]
            self.assertTrue(all(o.enabled for o in visible), f"{sid}: 摆出来的有灰项")
            self.assertFalse([o for o in hidden if o.label in labels],
                             f"{sid}: 同一标签又露又藏")
            gated_seen += len([o for o in hidden if o.gated])
            checked += 1
        self.assertGreater(checked, 40, f"只检查了 {checked} 个场景")
        self.assertGreater(gated_seen, 10, f"全剧本只数出 {gated_seen} 个被挡住的选项，门槛覆盖缩水了")

    def test_hidden_options_carry_a_reason_for_the_audit(self):
        """被 locked_if 挡住的必须留下原因（开发者读），visible_if 挡住的没有原因可给。"""
        engine = new_engine()
        hidden = engine.hidden_options()
        self.assertTrue(hidden)
        self.assertTrue(all(not o.enabled for o in hidden), "隐藏清单里的都不该是可选状态")
        self.assertTrue(any(o.hint for o in hidden), "至少有一条要留原因")


class AccusationTest(unittest.TestCase):
    def test_accusing_records_the_suspect(self):
        """回归：指认凶手曾不写 state.accused，结局一律判成「查不出来」。"""
        engine = new_engine()
        play(engine, helpers.preface(["整理证物", "「凶手是 —— 太监总管"]))
        self.assertEqual(engine.state.accused, "WDH")
        self.assertIn("accused", engine.state.flags)

    def test_accusing_lands_on_verdict_scene_and_finalizes(self):
        engine = new_engine()
        play(engine, helpers.preface(["整理证物", "「凶手是 —— 太监总管"]))
        self.assertTrue(engine.state.ending)
        self.assertEqual(engine.state.scene, engine.state.ending)

    def test_accusing_the_emperor_has_its_own_ending(self):
        engine = new_engine()
        play(engine, helpers.preface(["整理证物", "「凶手是 —— 陛下"]))
        self.assertEqual(engine.state.ending, "ending_treason")

    def test_accusing_the_consort_is_the_false_ending(self):
        engine = new_engine()
        play(engine, helpers.preface(["整理证物", "「凶手是 —— 贵妃"]))
        self.assertEqual(engine.state.ending, "ending_false")

    def test_giving_up_is_the_bystander_ending(self):
        engine = new_engine()
        play(engine, helpers.preface(["整理证物", "「此案 —— 暂无确证"]))
        self.assertEqual(engine.state.ending, "ending_bystander")

    def test_pressured_rule_fires_on_a_thin_state(self):
        """「按下」= 指认了王德海，却拿不出「只有凶手知晓之事」。

        真实路线也能走到：第一幕门槛过后核心已有 10 条，但 killer_knowledge
        要靠追问才拿得到——没有它，案子就立不住。
        """
        engine = new_engine()
        state = engine.state
        state.accused = "WDH"
        state.flags.add("accused")
        self.assertNotIn("killer_knowledge", state.clues)
        self.assertEqual(engine.pick_ending(), "ending_pressured")

    def test_accusing_right_after_the_gate_is_pressured(self):
        """过门槛就指认王德海：核心够多（9 条），但缺决定性的一条 → 「按下」。"""
        engine = new_engine()
        play(engine, helpers.gate_preface(["移步侧殿", "整理证物", "「凶手是 —— 太监总管"]))
        self.assertGreaterEqual(engine.state.core_count(), 6)
        self.assertNotIn("killer_knowledge", engine.state.clues)
        self.assertEqual(engine.state.ending, "ending_pressured")

    def test_resign_option_needs_enough_evidence(self):
        """「辞官」入口要求至少 8 条证据（`visible_if=at_least_clues(8)`）。

        门槛之后证据必然够，所以这里跳过门槛直接进结案屏，看证据不足时
        入口**根本不在选项表里**。
        """
        engine = new_engine()
        engine.go_to("accuse_hall")
        self.assertLess(len(engine.state.clues), 8)
        resign = [o for o in engine.options() if o.label.startswith("「臣 —— 验得出来")]
        self.assertEqual(resign, [])

    def test_resign_reachable_with_enough_evidence(self):
        engine = new_engine()
        play(engine, helpers.preface(["整理证物"]))
        resign = label_of(engine, "「臣 —— 验得出来")
        self.assertTrue(resign.enabled)
        resign.action()
        self.assertEqual(engine.state.ending, "ending_quiet")

    def test_every_ending_is_distinct(self):
        ids = [e.id for e in CONTENT.endings]
        self.assertEqual(len(ids), len(set(ids)))


class EndingRuleTest(unittest.TestCase):
    def test_pressured_when_the_decisive_clue_is_missing(self):
        """规则本身：「指认王德海 + 没有 killer_knowledge」→「按下」。"""
        engine = new_engine()
        state = engine.state
        state.accused = "WDH"
        state.flags.add("accused")
        self.assertNotIn("killer_knowledge", state.clues)
        self.assertEqual(engine.pick_ending(), "ending_pressured")

    def test_restitution_needs_motive_and_ring_and_confession(self):
        """真结局要求 accused=WDH、核心 ≥ 10、动机 + 玉扳指 + 口供三者齐全。"""
        engine = new_engine()
        play(engine, helpers.preface(["整理证物", "「凶手是 —— 太监总管"]))
        state = engine.state
        self.assertEqual(state.accused, "WDH")
        # 前奏走完第一幕，核心 9 条：真结局差的不是条数，而是
        # 「动机 + 玉扳指 + 口供」这三样，缺一样就退回下一级。
        self.assertGreaterEqual(state.core_count(), 6)
        self.assertLess(state.core_count(), 10)
        self.assertEqual(engine.pick_ending(), "ending_pressured")
        state.clues += ["killer_knowledge", "empress_motive", "empress_ring", "wdh_confessed"]
        state.flags.add("wdh_confessed")
        self.assertGreaterEqual(state.core_count(), 10)
        self.assertEqual(engine.pick_ending(), "ending_restitution")
        # 抽掉玉扳指 → 退回「尘埃落定」
        state.clues.remove("empress_ring")
        self.assertEqual(engine.pick_ending(), "ending_standard")
        # 连「只有凶手知晓之事」也没有：那就立不住案子 → 「按下」
        state.clues.remove("killer_knowledge")
        self.assertGreaterEqual(state.core_count(), 6)
        self.assertEqual(engine.pick_ending(), "ending_pressured")

    def test_pressured_route_from_real_play(self):
        """「按下」在真实路线上可达：过门槛后直接指认，但没有决定性那一条。"""
        engine = new_engine()
        play(engine, helpers.gate_preface(["移步侧殿", "整理证物", "「凶手是 —— 太监总管"]))
        self.assertGreaterEqual(engine.state.core_count(), 6)
        self.assertEqual(engine.pick_ending(), "ending_pressured")

    def test_standard_ending_from_a_thin_but_decisive_case(self):
        """只拿到「只有凶手知晓之事」、核心不足 10 条时是「尘埃落定」。"""
        engine = new_engine()
        state = engine.state
        state.accused = "WDH"
        state.flags.add("accused")
        state.clues += ["si_needle", "black_blood", "window_scratch",
                        "tea_almond", "censer_red", "pillow_letter", "killer_knowledge"]
        self.assertEqual(state.core_count(), 7)
        self.assertEqual(engine.pick_ending(), "ending_standard")

    def test_core_count_counts_items_owned(self):
        """回归：core_count 曾只数 clues，漏掉物证「安神茶盏」。"""
        engine = new_engine()
        self.assertEqual(engine.state.core_count(), 0)
        engine.state.items_owned.append("tea_set")
        self.assertEqual(engine.state.core_count(), 1)

    def test_every_ending_rule_is_callable(self):
        engine = new_engine()
        result = engine.pick_ending()
        self.assertIn(result, {e.id for e in CONTENT.endings})


class SaveTest(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        os.unlink(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_default_path_uses_env_var(self):
        old = os.environ.get("GONGWEI_SAVE")
        try:
            os.environ["GONGWEI_SAVE"] = self.path
            self.assertEqual(str(default_save_path()), self.path)
        finally:
            if old is None:
                os.environ.pop("GONGWEI_SAVE", None)
            else:
                os.environ["GONGWEI_SAVE"] = old

    def test_round_trip_restores_state(self):
        store = SaveStore(self.path)
        engine = new_engine()
        play(engine, helpers.preface(["传唤 · 太监总管", "@0f"]))
        self.assertFalse(store.exists())
        self.assertTrue(store.save(engine, stamp="单元测试"), store.last_error)
        self.assertTrue(store.exists())

        other = new_engine()
        ok, message = store.load(other)
        self.assertTrue(ok, message)
        self.assertEqual(other.state.scene, engine.state.scene)
        self.assertEqual(other.state.clues, engine.state.clues)
        self.assertEqual(other.state.trust, engine.state.trust)
        self.assertEqual(other.state.turn, engine.state.turn)
        self.assertEqual(len(other.state.log), len(engine.state.log))

    def test_summary_reports_progress(self):
        store = SaveStore(self.path)
        engine = new_engine()
        play(engine, helpers.OPENING)
        store.save(engine, stamp="半途")
        summary = store.summary()
        self.assertIsNotNone(summary)
        self.assertIn("半途", summary.describe())
        self.assertEqual(summary.clues, len(engine.state.clues))

    def test_load_without_file_fails_gracefully(self):
        store = SaveStore(self.path)
        ok, message = store.load(new_engine())
        self.assertFalse(ok)
        self.assertTrue(message)

    def test_corrupt_file_fails_gracefully(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        store = SaveStore(self.path)
        ok, message = store.load(new_engine())
        self.assertFalse(ok)
        self.assertTrue(message)

    def test_future_version_is_rejected(self):
        payload = {"v": SAVE_VERSION + 99, "state": {}}
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        store = SaveStore(self.path)
        ok, message = store.load(new_engine())
        self.assertFalse(ok)
        self.assertIn("版本", message)

    def test_a_misshapen_save_never_raises(self):
        """坏档只许安静地失败：`load()` 给理由、`summary()` 或给摘要或给 None。

        审计摸出来的形状：`state` 不是对象（AttributeError）、`state` 里的东西不是
        对象、`v` 不是数字、`dossiers` 的值不成对。标题屏的确认框会直接问
        `summary()`，一抛异常整个游戏就起不来（save.py 开头的约定）。
        """
        shapes = [
            {"v": 1, "state": "x"},
            {"v": 1, "state": {"turn": "abc"}},
            {"v": 1, "state": {"dossiers": {"01-FY-01": True}}},
            {"v": 1, "state": {"dossiers": {"01-FY-01": 5}}},
            {"v": 2, "state": {}},
            {"v": "一", "state": {}},
            {"v": 1, "state": []},
        ]
        for payload in shapes:
            with self.subTest(payload=payload):
                with open(self.path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False)
                store = SaveStore(self.path)
                ok, message = store.load(new_engine())
                self.assertFalse(ok, payload)
                self.assertTrue(message, payload)
                summary = store.summary()          # 标题屏就是这么问的：不许抛
                if summary is not None:
                    self.assertTrue(summary.describe(), payload)

    def test_summary_refuses_a_state_that_is_not_an_object(self):
        """`state` 不是对象时摘要不给半真半假的一行字，只留理由。"""
        for payload in ({"v": 1, "state": "x"}, {"v": 1, "state": [1, 2]},
                        {"v": 2, "state": {}}, {"v": "一", "state": {}}):
            with self.subTest(payload=payload):
                with open(self.path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False)
                store = SaveStore(self.path)
                self.assertIsNone(store.summary(), payload)
                self.assertTrue(store.last_error, payload)

    def test_clear_removes_file(self):
        store = SaveStore(self.path)
        store.save(new_engine())
        self.assertTrue(store.exists())
        store.clear()
        self.assertFalse(store.exists())

    def test_saving_at_the_verdict_restores_a_finished_ending(self):
        """存档停在判决过渡场景时，读档要补结算。"""
        store = SaveStore(self.path)
        engine = new_engine()
        play(engine, helpers.preface(["整理证物", "「凶手是 —— 太监总管"]))
        store.save(engine)

        other = new_engine()
        ok, _ = store.load(other)
        self.assertTrue(ok)
        self.assertTrue(other.state.ending)

    def test_save_is_atomic(self):
        """写盘走临时文件 + 替换，中途不该留下半截 JSON。"""
        store = SaveStore(self.path)
        store.save(new_engine())
        with open(self.path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["v"], SAVE_VERSION)
        self.assertIn("state", payload)
        leftovers = [n for n in os.listdir(os.path.dirname(self.path))
                     if n.startswith(".save-")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
