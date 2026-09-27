"""玩家看得见的那一层：回话只念一遍、跨场景重名的选项不许带收益、帮助不许说谎。

这三条都落在浏览器/终端之外，而且两端**对称地**错，所以 ``tools/audit_web.py``
那种逐步对比看不见它们——只有这里能拦住：

* 问询回话曾经在卷宗里出现两次（``Topic.response`` 与 ``Topic.effect.text``
  是同一段字，引擎两条都记）。
* 选项的「做过没有」按 ``Choice.key``（``{目标}::{文本}``）记，跨场景重名的
  纯导航项无害，可一旦挂上收益就会互相顶掉记录。
* 帮助浮层与「关于」页写着实际的幕数、命令表，写错了没有任何东西会报错。
"""

from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, ".")

from gongwei.data import CONTENT  # noqa: E402
from gongwei.game import GameEngine  # noqa: E402
from gongwei.game.command import HELP_SECTIONS, ParseError, parse  # noqa: E402
from gongwei.game.models import Choice, Effect  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_source(*parts: str) -> str:
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def new_engine() -> GameEngine:
    engine = GameEngine(CONTENT)
    engine.new_game()
    return engine


class TopicNarrationTest(unittest.TestCase):
    """一条问询回话只该在卷宗里留下一行。"""

    def test_a_topic_is_narrated_exactly_once(self):
        engine = new_engine()
        engine.go_to("talk_wdh")
        option = next(o for o in engine.options()
                      if o.tag == "interrogate" and o.enabled)
        said = [t.response for t in CONTENT.topics.values()
                if t.label == option.label]
        self.assertEqual(len(said), 1, "话题标签应当能唯一定位一条回话")
        option.action()
        spoken = [e.text for e in engine.state.log if e.kind == "narration"]
        self.assertEqual(spoken.count(said[0]), 1,
                         "同一条回话在卷宗里出现了两次")

    def test_the_detector_would_catch_a_second_copy(self):
        # 自检：这条测试真的看得见重复（免得以后编辑成永远为真）。
        engine = new_engine()
        engine.go_to("talk_wdh")
        option = next(o for o in engine.options()
                      if o.tag == "interrogate" and o.enabled)
        said = next(t.response for t in CONTENT.topics.values()
                    if t.label == option.label)
        option.action()
        spoken = [e.text for e in engine.state.log if e.kind == "narration"]
        self.assertEqual(spoken.count(said), 1)
        self.assertEqual(spoken.count(said + said), 0,
                         "重复两遍的字符串本来就不该出现")
        self.assertEqual(spoken.count(said), len([x for x in spoken
                                                  if x == said]))


class SharedLabelTest(unittest.TestCase):
    """同一个 `Choice.label` 被几个场景共用时，那些选项必须是纯导航。"""

    @staticmethod
    def _offenders(content) -> list:
        groups: dict = {}
        for scene in content.scenes.values():
            for choice in scene.choices:
                groups.setdefault(choice.label, []).append((scene.id, choice))
        bad = []
        for label, rows in groups.items():
            if len(rows) < 2:
                continue
            for sid, choice in rows:
                eff = choice.effect
                payload = (eff.add_clues, eff.add_items, eff.add_dossiers,
                           eff.flags, eff.score, eff.trust, eff.hurt)
                if any(payload):
                    bad.append(f"{sid} · {label}")
        return bad

    def test_a_shared_label_carries_no_payload(self):
        bad = self._offenders(CONTENT)
        self.assertEqual(bad, [], "跨场景重名的选项不能带收益，否则「做过没有」会互相顶掉")

    def test_the_checker_would_actually_catch_one(self):
        # 自检：造一个跨两个场景、且带收益的重名选项，必须被抓住。
        one = read_source("gongwei", "data", "story.py")
        self.assertIn('"回侧殿"', one)          # 剧本里确实有跨场景重名
        content = CONTENT
        twin = Choice(label="回侧殿", to="interrogate_hall",
                      effect=Effect(score=99))
        scene = next(iter(content.scenes.values()))
        original = list(scene.choices)
        scene.choices.append(twin)
        try:
            self.assertIn(f"{scene.id} · 回侧殿", self._offenders(content))
        finally:
            scene.choices[:] = original


class HelpTextTest(unittest.TestCase):
    """帮助里的每一条都必须是真命令；界面上不许写死幕数。"""

    #: 帮助条目 → 一条真的能敲的样例。加了新的帮助条目就得在这里给出样例，
    #: 等于逼着作者证明它真的能被 parse 出来。
    SAMPLES = {
        "阅 <档号>": "阅 01-FY-XFE",
        "档目 [页]": "档目 1",
        "查 <词>": "查 门闩",
        "问 <人> [话题]": "问 王德海 茶",
        "出示 <物证> <人>": "出示 tea_set 王德海",
        "前往 <地点>": "前往 尚药局",
        "查证": "查证",
        "复核": "复核",
        "记 <文字>": "记 测试",
        "改 <号> <文字>": "改 1 测试",
        "删 <号>": "删 1",
        "目 <时码> <标题>": "目 丑时 标题",
        "幕 <号> <标题>": "幕 1 标题",
        "指认 <人>": "指认 王德海",
        "存档 / 读档": "存档",
        "帮助 / 退出": "帮助",
    }

    def test_every_help_row_is_a_real_command(self):
        rows = [cmd for _section, items in HELP_SECTIONS for cmd, _desc in items]
        self.assertTrue(rows)
        missing = [cmd for cmd in rows if cmd not in self.SAMPLES]
        self.assertEqual(missing, [], "帮助里出现了没有样例的新条目")
        for cmd in rows:
            with self.subTest(cmd=cmd):
                try:
                    parse(self.SAMPLES[cmd])
                except ParseError as exc:      # pragma: no cover - 失败时给出行
                    self.fail(f"帮助里的「{cmd}」敲不出命令：{exc}")

    CN = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

    @classmethod
    def _number(cls, text: str) -> int:
        if text.isdigit():
            return int(text)
        if text == "十":
            return 10
        if text.startswith("十"):
            return 10 + cls.CN[text[1]]
        if "十" in text:
            head, _, tail = text.partition("十")
            return cls.CN[head] * 10 + (cls.CN[tail] if tail else 0)
        return cls.CN[text]

    def test_claims_about_how_big_the_game_is_stay_true(self):
        # 「三案十一幕」这类写死在文案里的规模，没人盯就会一直错
        # （网页版的「关于」曾写着「三案八幕」，实际三案十一幕）。
        cases = len({e.case for e in CONTENT.endings})
        acts = len(CONTENT.act_numbers())
        self.assertGreater(cases, 0)
        self.assertGreater(acts, 0)
        pattern = re.compile(
            r"([一二三四五六七八九十两0-9]+)案([一二三四五六七八九十两0-9]+)幕")
        seen = 0
        for name in ("web/src/ui.js", "gongwei/tui/app.py", "README.md",
                     "AGENTS.md", "gongwei/game/command.py"):
            text = read_source(*name.split("/"))
            for match in pattern.finditer(text):
                seen += 1
                claim = (self._number(match.group(1)),
                         self._number(match.group(2)))
                line = text[:match.start()].count("\n") + 1
                self.assertEqual(
                    claim, (cases, acts),
                    f"{name}:{line} 写着「{match.group(0)}」，"
                    f"实际是「{cases} 案 {acts} 幕」")
        self.assertGreater(seen, 0, "没有扫到任何规模声明，这条测试成了摆设")


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
