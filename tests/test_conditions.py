"""条件小语言单测：剧本里所有 ``visible_if`` / ``locked_if`` / 话题门禁都靠它。"""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, ".")

from gongwei.data import CONTENT
from gongwei.game.conditions import (ConditionSyntaxError, all_of, always, any_of,
                                     at_least_clues, has_clue, has_flag, never,
                                     parse_condition, trust_at_least)
from gongwei.game.engine import GameState


def make_state(**kw) -> GameState:
    state = GameState(_content=CONTENT)
    for key, value in kw.items():
        setattr(state, key, value)
    return state


class ParserTest(unittest.TestCase):
    def test_bare_clue(self):
        self.assertTrue(parse_condition("clue:tea_almond")(make_state(clues=["tea_almond"])))
        self.assertFalse(parse_condition("clue:tea_almond")(make_state()))

    def test_bare_flag(self):
        self.assertTrue(parse_condition("flag:knows_caiwei")(make_state(flags={"knows_caiwei"})))

    def test_visited(self):
        self.assertTrue(parse_condition("visited:talk_wdh")(make_state(visited={"talk_wdh"})))

    def test_time_at_is_monotonic(self):
        expr = parse_condition("time_at:丑时")
        self.assertTrue(expr(make_state(time="丑时")))
        self.assertTrue(expr(make_state(time="寅时")))
        self.assertFalse(expr(make_state(time="子时三刻")))

    def test_clues_count_expression(self):
        # clues: 后面必须给比较运算符；给了 id 列表就是「其中满足几条」
        expr = parse_condition("clues:si_needle,black_blood>=2")
        self.assertTrue(expr(make_state(clues=["si_needle", "black_blood"])))
        self.assertFalse(expr(make_state(clues=["si_needle"])))
        total = parse_condition("clues:>=2")
        self.assertTrue(total(make_state(clues=["a", "b"])))
        self.assertFalse(total(make_state(clues=["a"])))
    def test_evidence_core_threshold(self):
        core = [i.id for i in CONTENT.items.values() if i.core][:3]
        expr = parse_condition("evidence:core>=2")
        self.assertTrue(expr(make_state(clues=core[:2])))
        self.assertFalse(expr(make_state(clues=core[:1])))

    def test_evidence_counts_items_owned_too(self):
        """回归：核心证据 `tea_set` 是物证（入行囊），不算进 clues。"""
        expr = parse_condition("evidence:core>=1")
        self.assertTrue(expr(make_state(items_owned=["tea_set"])))

    def test_trust_gate(self):
        expr = parse_condition("trust:WDH>=50")
        self.assertTrue(expr(make_state(trust={"WDH": 50})))
        self.assertFalse(expr(make_state(trust={"WDH": 49})))
        self.assertFalse(expr(make_state(trust={})))

    def test_min_trust(self):
        expr = parse_condition("min_trust:WDH>=40")
        self.assertTrue(expr(make_state(trust={"WDH": 40, "HH": 55})))
        self.assertFalse(expr(make_state(trust={"WDH": 39})))

    def test_and_or_not(self):
        expr = parse_condition("clue:a and (flag:b or not clue:c)")
        self.assertTrue(expr(make_state(clues=["a"], flags={"b"})))
        self.assertTrue(expr(make_state(clues=["a"])))
        self.assertFalse(expr(make_state(clues=["a", "c"])))

    def test_bang_is_not(self):
        self.assertTrue(parse_condition("!clue:a")(make_state()))
        self.assertFalse(parse_condition("!clue:a")(make_state(clues=["a"])))

    def test_unknown_predicate_raises(self):
        with self.assertRaises(ConditionSyntaxError):
            parse_condition("nonsense:x")

    def test_incomplete_expression_raises(self):
        with self.assertRaises(ConditionSyntaxError):
            parse_condition("clue:a and")
        with self.assertRaises(ConditionSyntaxError):
            parse_condition("(clue:a")

    def test_empty_expression_means_unconditional(self):
        # 空串/None 表示「没有条件」，不是错误 —— engine 依赖这个约定
        self.assertIsNone(parse_condition(""))
        self.assertIsNone(parse_condition("   "))
        self.assertIsNone(parse_condition(None))

    def test_parser_is_cached(self):
        self.assertIs(parse_condition("clue:si_needle"), parse_condition("clue:si_needle"))


class HelperTest(unittest.TestCase):
    def test_always_never(self):
        self.assertTrue(always(make_state()))
        self.assertFalse(never(make_state()))

    def test_has_clue_checks_items_too(self):
        self.assertTrue(has_clue("tea_set")(make_state(items_owned=["tea_set"])))
        self.assertFalse(has_clue("tea_set")(make_state()))

    def test_trust_at_least_defaults_missing_to_zero(self):
        self.assertTrue(trust_at_least("WDH", 0)(make_state()))
        self.assertFalse(trust_at_least("WDH", 1)(make_state()))

    def test_at_least_clues(self):
        """``at_least_clues(n, *ids)``：在给定 id 里满足 n 条。"""
        expr = at_least_clues(2, "a", "b")
        self.assertFalse(expr(make_state()))
        self.assertFalse(expr(make_state(clues=["a"])))
        self.assertTrue(expr(make_state(clues=["a", "b"])))
        self.assertTrue(expr(make_state(clues=["a"], items_owned=["b"])))

    def test_all_of_any_of(self):
        self.assertTrue(all_of(has_clue("a"), has_flag("f"))(make_state(clues=["a"], flags={"f"})))
        self.assertFalse(all_of(has_clue("a"), has_flag("f"))(make_state(clues=["a"])))
        self.assertTrue(any_of(has_clue("a"), has_flag("f"))(make_state(flags={"f"})))
        self.assertFalse(any_of(has_clue("a"), has_flag("f"))(make_state()))


class EveryConditionInTheScriptParsesTest(unittest.TestCase):
    """把剧本里出现的每一段条件都解析一遍 —— 防止写错语法却只在玩到时才炸。"""

    def test_all_scene_choice_conditions(self):
        checked = 0
        for scene in CONTENT.scenes.values():
            for choice in scene.choices:
                for expr in (choice.visible_if, choice.locked_if, choice.locked_by):
                    if expr is not None:
                        expr(make_state())
                        checked += 1
        self.assertGreater(checked, 0)

    def test_all_ending_rules_run(self):
        state = make_state()
        for rule in CONTENT.endings:
            self.assertIsInstance(rule.rule(state), bool, rule.id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
