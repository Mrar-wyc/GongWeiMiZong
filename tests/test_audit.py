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
        正是为此存在的。所以这里盯两件事：十三条路线一条都不能断，
        而且它们要真的走出一批东西来。
        """
        from gongwei.autoplay import ENDING_ROUTES

        found, broken = self.mod.route_sweep()
        self.assertEqual(broken, [])
        self.assertEqual(found["endings"], set(ENDING_ROUTES))
        self.assertGreater(len(found["scenes"]), 10)
        self.assertGreater(len(found["dossiers"]), 30)


if __name__ == "__main__":
    unittest.main()
