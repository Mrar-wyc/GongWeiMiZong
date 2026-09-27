"""图景台账：把「这一屏该是什么样子」写成名字，不写成图片。

这一层只干一件事——读剧本里**本来就有**的 `place / kind / time / act`，算出一个
名字（`hall`、`night` 之类），交给表现层去画。所以：

  * 没有图片、没有字体、没有 CDN。网页端的花样全部由 `web/src/static.css` 用
    渐变与形状画出来，构建期 `tools/build_web.py` 会把外链挡回去。
  * **不向 Content / GameState 加任何字段。** `tools/audit_web.py` 拿 27 条路线
    逐步比对两端的存档与选项表，多一个字段就会红；这里只算、不存。
  * **不 import `gongwei.data.story`。** 单测与打包都能零副作用地用它，也就不可能
    把剧情偷偷抄进来——地名、幕名一律靠 pack 在运行时传进来。
  * 终端版按同一套名字做减法（`gongwei/tui/app.py` 的幕间字幕与结局印章）。

改这里的表，等于同时改两端的观感：加一个地点，`tests/test_art.py` 会要求登记。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# --------------------------------------------------------------------------
# 色调：一屏的「地方味」
#
# 名字是给 CSS 的选择器用的（`#stage[data-tone="hall"]`），本身不带剧情。
# 只按地点分不够看，所以另有「光」这一维由时辰决定，两者叠起来才算一屏。
# --------------------------------------------------------------------------

TONE_HALL = "hall"                  # 凤仪殿系：正殿、侧殿、暖阁、廊下
TONE_PHARMACY = "pharmacy"          # 尚药局系：前厅、药库、账房、值房
TONE_ARCHIVE = "archive"            # 经卷阁系与掖庭旧档库：书格、卷帙
TONE_OFFICE = "office"              # 内官监值房：冷灰、案牍
TONE_ENCOUNTER = "interrogation"    # 有人在对面的屏风后：审讯与问询
TONE_VERDICT = "verdict"            # 结案陈词那一屏
TONE_ENDING = "ending"              # 二十个结局（地点一律是「结案」）

DEFAULT_TONE = TONE_HALL

#: 地点 → 色调。只登记 `kind == "scene"` 的场景会用到的那 18 个地点；
#: 结局的「结案」不在这里，它由 `kind` 直接定调。
PLACE_TONES: Dict[str, str] = {
    "凤仪殿": TONE_HALL,
    "凤仪殿 · 正殿": TONE_HALL,
    "凤仪殿 · 侧殿": TONE_HALL,
    "凤仪殿 · 东暖阁": TONE_HALL,
    "凤仪殿 · 西暖阁": TONE_HALL,
    "凤仪殿 · 廊下": TONE_HALL,
    "尚药局": TONE_PHARMACY,
    "尚药局 · 前厅": TONE_PHARMACY,
    "尚药局 · 药库": TONE_PHARMACY,
    "尚药局 · 药库前": TONE_PHARMACY,
    "尚药局 · 账房": TONE_PHARMACY,
    "尚药局 · 书吏值房": TONE_PHARMACY,
    "尚药局 · 值房": TONE_PHARMACY,
    "经卷阁 · 阁前": TONE_ARCHIVE,
    "经卷阁 · 丙字库": TONE_ARCHIVE,
    "经卷阁 · 掌籍厅": TONE_ARCHIVE,
    "掖庭 · 旧档库": TONE_ARCHIVE,
    "内官监 · 值房": TONE_OFFICE,
}

#: 一屏的判定顺序：结局 > 判决 > 有人在对面 > 地点。与 `web/src/ui.js` 里那三行
#: 必须一致，`tests/test_art.py` 拿真实 pack 逐场景核对。
TONES: Tuple[str, ...] = (
    TONE_HALL, TONE_PHARMACY, TONE_ARCHIVE, TONE_OFFICE,
    TONE_ENCOUNTER, TONE_VERDICT, TONE_ENDING,
)

# --------------------------------------------------------------------------
# 光：时辰决定明暗（夜里点灯、寅时天将亮、白日天光）
# --------------------------------------------------------------------------

LIGHT_NIGHT = "night"
LIGHT_DAWN = "dawn"
LIGHT_DAY = "day"

DEFAULT_LIGHT = LIGHT_DAY

TIME_LIGHT: Dict[str, str] = {
    "子时三刻": LIGHT_NIGHT,
    "丑时": LIGHT_NIGHT,
    "丑时二刻": LIGHT_NIGHT,
    "丑时三刻": LIGHT_NIGHT,
    "寅时": LIGHT_DAWN,
    "寅时三刻": LIGHT_DAWN,
    "卯时": LIGHT_DAY,
    "辰时": LIGHT_DAY,
    "巳时": LIGHT_DAY,
}

# --------------------------------------------------------------------------
# 字形：线索 / 口供 / 文书 / 物证
#
# 形状画在 CSS 里（`.glyph[data-glyph="clue"]`），这里只登记词表，好让
# `tests/test_art.py` 拿 pack 里 `items[*].tag` 的全部取值来对账。
# --------------------------------------------------------------------------

GLYPH_CLUE = "clue"
GLYPH_TESTIMONY = "testimony"
GLYPH_DOC = "doc"
GLYPH_ITEM = "item"
GLYPH_FALLBACK = "mark"

GLYPH_TAGS: Tuple[str, ...] = (GLYPH_CLUE, GLYPH_TESTIMONY, GLYPH_DOC, GLYPH_ITEM)

# --------------------------------------------------------------------------
# 算一屏的样子
# --------------------------------------------------------------------------


def tone_for(place: str = "", kind: str = "", verdict: bool = False,
             encounter: bool = False) -> str:
    """一屏的色调。顺序与网页端一致：结局 > 判决 > 有人在对面的 > 地点。"""
    if kind == "ending":
        return TONE_ENDING
    if verdict:
        return TONE_VERDICT
    if encounter:
        return TONE_ENCOUNTER
    return PLACE_TONES.get(place or "", DEFAULT_TONE)


def light_for(time: str = "") -> str:
    """一屏的明暗。认不出的时辰按白日算，绝不猜。"""
    return TIME_LIGHT.get(time or "", DEFAULT_LIGHT)


def glyph_for(tag: str = "") -> str:
    """物件的字形名；没登记的 tag 退到中性记号，不会画不出来。"""
    return tag if tag in GLYPH_TAGS else GLYPH_FALLBACK


def glyphs() -> Tuple[str, ...]:
    """CSS 里必须实现的字形（含兜底那个）。"""
    return GLYPH_TAGS + (GLYPH_FALLBACK,)


# --------------------------------------------------------------------------
# 交给网页端的那份表
# --------------------------------------------------------------------------


def art_tables() -> Dict[str, object]:
    """打包时内联进 `web/shell.html` 的 `#art` 块（键名见 web/src/ui.js）。"""
    return {
        "place_tone": dict(PLACE_TONES),
        "time_light": dict(TIME_LIGHT),
        "tones": list(TONES),
        "glyphs": list(glyphs()),
        "tone_ending": TONE_ENDING,
        "tone_verdict": TONE_VERDICT,
        "tone_encounter": TONE_ENCOUNTER,
        "default_tone": DEFAULT_TONE,
        "default_light": DEFAULT_LIGHT,
        "glyph_fallback": GLYPH_FALLBACK,
    }


#: 舞台骨架：垫在 `#app` **前面**（同级），所以 `ui.js` 的 `clear(root)` 永远碰不到它。
#: 分四层是为了让 CSS 各画各的：底子（wash）、窗格/药格（lattice）、灯与天光（glow）、
#: 浮尘与雪（mote）；过场卡单独一层，动完就自己收起来。
ART_SLOT_MARKUP = """<div id="stage" data-tone="hall" data-light="day" data-act="0" aria-hidden="true">
  <div class="stage-layer stage-wash"></div>
  <div class="stage-layer stage-lattice"></div>
  <div class="stage-layer stage-glow"></div>
  <div class="stage-layer stage-mote"></div>
  <div class="stage-card" id="stage-card"></div>
</div>"""


def art_slot() -> str:
    """`web/shell.html` 里 `__ART_SLOT__` 的替换文本。"""
    return ART_SLOT_MARKUP


def table_keys() -> List[str]:
    """表里必须齐的键（测试与构建都按这个对账）。"""
    return sorted(art_tables().keys())
