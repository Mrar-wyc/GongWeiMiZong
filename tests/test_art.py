"""图景台账的对账：这张表要自洽、要跟真剧本对得上、要跟画它的那份 CSS 一一对应。

``gongwei/web/art.py`` 里一张图片也没有——它只是一张**名字表**：地点算色调、
时辰算明暗、物件标签算字形。名字表最容易坏在两处：

* 跟剧本脱节：剧本里新添一个地点，没人去登记，它就悄悄退成默认景，谁也不会发现；
* 跟画脱节：表里有名字，`web/src/static.css` 却没为它写样式，那一屏就是白的。

所以这里分三层盯：表自己（判定顺序、兜底、键名）、表 vs 真剧本（地点 / 时辰 / 标签
全部登记过，也全部用得上）、表 vs 产物（`tools/build_web.py` 内联的那块 ``#art``
与表逐字相同，CSS 为每个名字都写了样式、也为 ``ui.js`` 会写的类名写了样式）。
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gongwei.data.story import CONTENT, TOPIC_GATES  # noqa: E402
from gongwei.web import art  # noqa: E402
from gongwei.web.pack import content_pack  # noqa: E402
from tests.helpers import load_tool  # noqa: E402

ART_RE = re.compile(r'<script id="art" type="application/json">(.*?)</script>', re.S)


class TableItselfTest(unittest.TestCase):
    """判定顺序、兜底、键名：这一层不看剧本，纯查表。"""

    def test_ending_beats_everything(self):
        self.assertEqual(
            art.tone_for("结案", "ending", verdict=True, encounter=True), art.TONE_ENDING)

    def test_verdict_beats_encounter_and_place(self):
        self.assertEqual(
            art.tone_for("尚药局 · 前厅", "scene", verdict=True, encounter=True), art.TONE_VERDICT)

    def test_encounter_beats_place(self):
        self.assertEqual(
            art.tone_for("凤仪殿 · 正殿", "scene", encounter=True), art.TONE_ENCOUNTER)

    def test_place_then_default(self):
        self.assertEqual(art.tone_for(place="经卷阁 · 阁前"), art.TONE_ARCHIVE)
        self.assertEqual(art.tone_for(place="没见过的地方"), art.DEFAULT_TONE)
        self.assertEqual(art.tone_for(), art.DEFAULT_TONE)

    def test_lights_and_glyphs_fall_back_without_guessing(self):
        self.assertEqual(art.light_for("辰时"), art.LIGHT_DAY)
        self.assertEqual(art.light_for("亥时"), art.DEFAULT_LIGHT)
        self.assertEqual(art.light_for(), art.DEFAULT_LIGHT)
        self.assertEqual(art.glyph_for("clue"), art.GLYPH_CLUE)
        self.assertEqual(art.glyph_for("medicine"), art.GLYPH_FALLBACK)
        self.assertEqual(art.glyph_for(), art.GLYPH_FALLBACK)
        self.assertEqual(art.glyphs(), art.GLYPH_TAGS + (art.GLYPH_FALLBACK,))

    def test_every_registered_name_points_at_a_declared_value(self):
        for place, tone in art.PLACE_TONES.items():
            self.assertTrue(place.strip(), "地点名不许是空的")
            self.assertIn(tone, art.TONES, place)
        for when, light in art.TIME_LIGHT.items():
            self.assertTrue(when.strip(), "时辰名不许是空的")
            self.assertIn(light, (art.LIGHT_NIGHT, art.LIGHT_DAWN, art.LIGHT_DAY), when)
        self.assertEqual(len(set(art.TONES)), len(art.TONES), "色调名不许重复")

    def test_tables_are_json_ready_and_keys_are_exactly_these(self):
        tables = art.art_tables()
        self.assertEqual(art.table_keys(), sorted(tables))
        self.assertEqual(art.table_keys(), [
            "default_light", "default_tone", "glyph_fallback", "glyphs", "place_tone",
            "time_light", "tone_encounter", "tone_ending", "tone_verdict", "tones",
        ])
        self.assertEqual(json.loads(json.dumps(tables, ensure_ascii=False)), tables)
        self.assertEqual(tables["place_tone"], dict(art.PLACE_TONES))
        self.assertEqual(tables["time_light"], dict(art.TIME_LIGHT))

    def test_slot_markup_carries_the_defaults_and_the_four_layers(self):
        slot = art.art_slot()
        self.assertEqual(slot, art.ART_SLOT_MARKUP)
        self.assertIn('<div id="stage"', slot)
        self.assertIn('id="stage-card"', slot)
        self.assertIn('aria-hidden="true"', slot)
        self.assertNotIn("<script", slot)
        for layer in ("stage-wash", "stage-lattice", "stage-glow", "stage-mote"):
            self.assertIn(layer, slot, layer)
        # 起手的三个属性必须与表里的默认值一致：ui.js 首帧照写一遍，两边不该各说各的。
        self.assertIn(f'data-tone="{art.DEFAULT_TONE}"', slot)
        self.assertIn(f'data-light="{art.DEFAULT_LIGHT}"', slot)
        self.assertIn('data-act="0"', slot)


class StoryAgreementTest(unittest.TestCase):
    """台账 vs 真剧本：剧本里出现过的地方 / 时辰 / 标签，表里一个都不能漏。"""

    @classmethod
    def setUpClass(cls):
        cls.pack = content_pack(CONTENT, TOPIC_GATES)
        cls.scenes = cls.pack["scenes"]
        cls.verdicts = set(cls.pack["verdict_scenes"])

    def _used_places(self):
        return {s.get("place", "") for s in self.scenes.values() if s.get("kind") == "scene"}

    def test_every_place_a_scene_stands_in_is_registered(self):
        missing = sorted(self._used_places() - set(art.PLACE_TONES))
        self.assertEqual(missing, [], f"这些地点还没登记色调：{missing}")

    def test_the_table_has_no_place_nobody_stands_in(self):
        dead = sorted(set(art.PLACE_TONES) - self._used_places())
        self.assertEqual(dead, [], f"登记了却没有场景用的地点：{dead}")

    def test_endings_are_pitched_by_kind_not_by_place(self):
        endings = [s for s in self.scenes.values() if s.get("kind") == "ending"]
        self.assertTrue(endings, "剧本里总得有结局场景")
        for scene in endings:
            self.assertEqual(
                art.tone_for(scene.get("place", ""), scene.get("kind", "")), art.TONE_ENDING)
        self.assertNotIn("结案", art.PLACE_TONES, "结局靠 kind 定调，不靠地点")

    def test_every_scene_gets_a_tone_and_all_seven_come_up(self):
        seen = set()
        for sid, scene in self.scenes.items():
            encounter = bool(scene.get("interlocutor") or scene.get("hall"))
            tone = art.tone_for(scene.get("place", ""), scene.get("kind", ""),
                                verdict=sid in self.verdicts, encounter=encounter)
            seen.add(tone)
            self.assertIn(tone, art.TONES, sid)
            if sid in self.verdicts:
                self.assertEqual(tone, art.TONE_VERDICT, f"{sid} 是判决屏")
            elif encounter:
                self.assertEqual(tone, art.TONE_ENCOUNTER, f"{sid} 是有人在对面的屏")
        self.assertEqual(seen, set(art.TONES), "七个色调每一个都得真用得上")

    def test_every_hour_in_the_story_is_registered(self):
        hours = {s.get("time", "") for s in self.scenes.values()}
        self.assertEqual(sorted(hours - set(art.TIME_LIGHT)), [], "有场景站在没登记的时辰上")
        self.assertEqual(sorted(set(art.TIME_LIGHT) - hours), [], "表里有剧本用不到的时辰")
        for when in self.pack["time_order"]:
            self.assertIn(when, art.TIME_LIGHT, when)

    def test_every_item_tag_has_a_glyph(self):
        tags = {i["tag"] for i in self.pack["items"].values()}
        self.assertTrue(tags)
        unregistered = sorted(t for t in tags if art.glyph_for(t) == art.GLYPH_FALLBACK)
        self.assertEqual(unregistered, [], f"这些物件标签还没登记字形：{unregistered}")


class BuiltPageTest(unittest.TestCase):
    """表 vs 画：产物里那块 JSON 与表逐字相同，CSS 也必须画全了每个名字。"""

    @classmethod
    def setUpClass(cls):
        cls.build_web = load_tool("build_web")
        outputs = cls.build_web.build()
        cls.html = outputs[cls.build_web.OUT_HTML]
        cls.css = "".join(
            (ROOT / "web" / "src" / name).read_text(encoding="utf-8")
            for name in ("style.css", "static.css"))
        cls.ui_js = (ROOT / "web" / "src" / "ui.js").read_text(encoding="utf-8")

    def test_the_page_carries_the_table_verbatim(self):
        found = ART_RE.search(self.html)
        self.assertIsNotNone(found, "产物里找不到 #art 块")
        self.assertEqual(json.loads(found.group(1)), art.art_tables())

    def test_the_slot_is_in_the_page_and_outside_app(self):
        self.assertIn('<div id="stage"', self.html)
        self.assertLess(self.html.index('<div id="stage"'),
                        self.html.index('<div id="app"></div>'),
                        "图景槽必须垫在 #app 前面：ui.js 每一屏都要 clear(#app)")

    def test_css_draws_every_name_in_the_table(self):
        self.assertIn("#stage {", self.css)
        for tone in art.TONES:
            self.assertIn(f'#stage[data-tone="{tone}"]', self.css, tone)
        for light in (art.LIGHT_NIGHT, art.LIGHT_DAWN, art.LIGHT_DAY):
            self.assertIn(f'#stage[data-light="{light}"]', self.css, light)
        for glyph in art.glyphs():
            self.assertIn(f'[data-glyph="{glyph}"]', self.css, glyph)

    def test_css_styles_what_the_ui_writes(self):
        for selector in ("#stage {", ".stage-layer", ".stage-card", ".said-name",
                         ".said-line", ".ending-seal", ".mark-row", ".bag-row",
                         ".setting-row", ".page-collection"):
            self.assertIn(selector, self.css, selector)

    def test_the_ui_reads_every_key_in_the_table(self):
        for key in art.table_keys():
            self.assertRegex(self.ui_js, r"ART\.%s\b" % re.escape(key),
                             f"ui.js 根本没读 {key}：表里的这项是死的")
