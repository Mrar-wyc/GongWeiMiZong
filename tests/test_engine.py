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

    def test_opening_has_six_options(self):
        """开局六项：前五项能点，第六项「移步侧殿」被第一幕门槛锁着。

        门槛是 `missing_dossier(FIRST_ACT_SUMMARY)`——没读全勘验格目就走不掉，
        所以这一项**本来**就该是灰的，并且给出可读的提示。
        """
        engine = new_engine()
        opts = engine.options()
        self.assertEqual(len(opts), 6)
        locked = [o for o in opts if not o.enabled]
        self.assertEqual(len(locked), 1, [o.label for o in opts])
        self.assertTrue(locked[0].label.startswith("移步侧殿"), locked[0].label)
        self.assertTrue(locked[0].hint)
        self.assertTrue(all(o.enabled for o in opts if o is not locked[0]))

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

    def test_locked_topic_stays_visible_with_hint(self):
        """回归：被门禁锁住的话题曾被 `seen_choices` 直接吃掉，玩家看不到提示。"""
        engine = new_engine()
        play(engine, helpers.preface(["传唤 · 太监总管"]))
        locked = [o for o in engine.options() if not o.enabled and o.hint]
        self.assertTrue(locked, "审讯里应当至少有一个「锁住但有提示」的话题")

    def test_asking_a_topic_marks_it_asked(self):
        engine = new_engine()
        play(engine, helpers.preface(["传唤 · 太监总管"]))
        first = [o for o in engine.options() if o.enabled and not o.asked]
        self.assertTrue(first)
        first[0].action()
        self.assertTrue(engine.state.topics_asked, "问过的话题应记进 topics_asked")

    def test_asked_topic_disappears_unless_locked(self):
        """问过且已解锁的话题要收起来；锁住的即使问过也要留着（带提示）。"""
        engine = new_engine()
        play(engine, helpers.preface(["传唤 · 太监总管"]))
        before = len([o for o in engine.options() if o.enabled])
        [o for o in engine.options() if o.enabled and not o.asked][0].action()
        after = len([o for o in engine.options() if o.enabled])
        self.assertEqual(after, before - 1)

    def test_skipping_evidence_keeps_pharmacy_topic_locked(self):
        """没去尚药局拿领用簿，王德海的「出示」话题应当锁着。"""
        engine = new_engine()
        play(engine, helpers.preface(["传唤 · 太监总管"]))
        locked = [o for o in engine.options() if not o.enabled]
        self.assertTrue(any("出示" in o.label for o in locked))


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
