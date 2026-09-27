"""指令层：把玩家敲的一行字解析成一条结构化指令。

设计要点（这些都是被两端共用逼出来的约束）：

1. **纯函数、无状态**——`parse(text)` 只依赖文本本身，不认识引擎。因此它可以被
   终端前端、网页前端、测试脚本以完全相同的方式调用。
2. **归一化用 NFKC**——全角数字/字母（`０１`）、全角标点（`：`）、兼容字符
   （`－`）全部折成半角。玩家不会在意输入法状态，代码必须替他兜住。
3. **档号是宽容的**——`01-FY-WDH` / `01-fy-wdh` / `01fywdh` 都认，但**认出来的
   档号保留原样的大写形式**（`01-FY-WDH`），因为档目栏要按这个显示。
4. **失败不静默**——解析不出来就给出 `ParseError`，带 `hint`（最接近的候选）。
   玩家敲错档号时看到「找不到「09-FY-WDH」，是否想查「09-FY-WDH」？」比
   什么都不发生好得多。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# 指令种类
# --------------------------------------------------------------------------

#: 打开一份档案。`arg` 是档号（已归一大写）。
READ = "read"
#: 列出已收集的档案，`index` 是页码（从 1 起）。
LIST = "list"
#: 在已读档案里检索，`arg` 是关键词。
SEARCH = "search"
#: 提审：`who` 是人物，`what` 是话题。
ASK = "ask"
#: 出示证物：`arg` 是证物名，`who` 是承受者。
SHOW = "show"
#: 移步：`arg` 是地点。
GOTO = "goto"
#: 记事簿：`arg` 是内容，`index` 是要删/改的条目号。
NOTE = "note"
EDIT_NOTE = "edit_note"
DELETE_NOTE = "delete_note"
#: 给时辰/幕取标题。
TITLE = "title"
ACT = "act"
#: 案卷页。
REVIEW = "review"          # 整理证物
TIMELINE = "timeline"      # 拼时间线
#: 结案。
ACCUSE = "accuse"
#: 系统。
SAVE = "save"
LOAD = "load"
HELP = "help"
QUIT = "quit"


@dataclass
class Command:
    """一条解析好的指令。

    `raw` 保留玩家原样输入（用于历史记录与回显），`kind` 是上面那串常量之一。
    """

    kind: str
    arg: str = ""
    who: str = ""
    what: str = ""
    index: int = 0
    raw: str = ""

    @property
    def is_system(self) -> bool:
        return self.kind in (SAVE, LOAD, HELP, QUIT)


class ParseError(Exception):
    """敲的东西解析不出来。

    `hint` 是给玩家看的一句话建议，可以为空。`candidates` 是可供选择的合法写法。
    """

    def __init__(self, message: str, hint: str = "",
                 candidates: Optional[Sequence[str]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.candidates: List[str] = list(candidates or [])


# --------------------------------------------------------------------------
# 归一化
# --------------------------------------------------------------------------

# 玩家可能用「全角空格」断词，NFKC 会把它折成普通空格，但连续空格仍需压缩。
_ZWSP = "\u200b\u200c\u200d\ufeff"


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def normalize(text: str, upper: bool = False) -> str:
    """把一行输入折成可比较的形式。

    全角→半角（NFKC）、去掉零宽字符、压缩连续空白、去首尾空白。
    `upper=True` 时同时转大写——档号比较用得到。
    """
    if not text:
        return ""
    out = _nfkc(text)
    for ch in _ZWSP:
        out = out.replace(ch, "")
    out = " ".join(out.split())
    return out.upper() if upper else out


# --------------------------------------------------------------------------
# 档号
# --------------------------------------------------------------------------

#: 档号形如 `01-FY-WDH`：两位时辰码、一至三位地点码、零至多段在场人码。
#: 允许玩家省略连字符，也允许大小写混写。
_SEP = "-_—–~· 　"


def is_dossier_id(text: str) -> bool:
    """判断一段文本是否「看起来像档号」。

    只做形状判断，不校验是否真的存在——存在性由引擎回答，
    因为解析器不认识剧本。
    """
    t = normalize(text, upper=True)
    if not t:
        return False
    for sep in _SEP:
        t = t.replace(sep, "-")
    while "--" in t:
        t = t.replace("--", "-")
    t = t.strip("-")
    if not t:
        return False
    parts = t.split("-")
    head = parts[0]
    if not head.isdigit() or len(head) != 2:
        # `00` 也走这条；全是数字且长度 2 才算时辰码
        return False
    for part in parts[1:]:
        if not part:
            return False
        if not part.isascii() or not part.isalnum():
            return False
    return len(parts) >= 2


def canon_dossier_id(text: str) -> str:
    """把档号折成规范写法 `01-FY-WDH`（大写、单连字符、去首尾连字符）。"""
    t = normalize(text, upper=True)
    for sep in _SEP:
        t = t.replace(sep, "-")
    while "--" in t:
        t = t.replace("--", "-")
    return t.strip("-")


# --------------------------------------------------------------------------
# 动词表
# --------------------------------------------------------------------------

#: 主表：动词 -> 指令种类。一个动词只能有一种含义，避免歧义。
#: 「记」与「改」分开：记事簿的增删改是三种不同的操作。
VERBS: Dict[str, str] = {
    "阅": READ, "看": READ, "读": READ, "打开": READ, "调阅": READ, "启": READ,
    "档目": LIST, "目录": LIST, "案卷目录": LIST, "档": LIST, "列表": LIST,
    "查": SEARCH, "搜": SEARCH, "检索": SEARCH, "找": SEARCH,
    "问": ASK, "审": ASK, "提审": ASK, "询问": ASK,
    "出示": SHOW, "呈": SHOW, "示": SHOW, "对质": SHOW,
    "前往": GOTO, "去": GOTO, "移步": GOTO, "行": GOTO,
    "记": NOTE, "注": NOTE,
    "改": EDIT_NOTE, "修": EDIT_NOTE, "改记": EDIT_NOTE,
    "删": DELETE_NOTE, "涂": DELETE_NOTE, "划": DELETE_NOTE,
    "目": TITLE, "题": TITLE, "命名": TITLE,
    "幕": ACT, "幕题": ACT,
    "查证": REVIEW, "整理": REVIEW, "验看": REVIEW, "清点": REVIEW,
    "复核": TIMELINE, "拼": TIMELINE, "时间线": TIMELINE, "串": TIMELINE,
    "指认": ACCUSE, "结案": ACCUSE, "断定": ACCUSE, "指控": ACCUSE,
    "存档": SAVE, "保存": SAVE, "记档": SAVE,
    "读档": LOAD, "取档": LOAD, "续": LOAD, "载入": LOAD,
    "帮助": HELP, "助": HELP, "？": HELP, "?": HELP, "用法": HELP,
    "退出": QUIT, "离开": QUIT, "结束": QUIT, "罢": QUIT,
}

#: 英文别名。玩家在中文输入法里打不出来时会用这些。
VERBS_EN: Dict[str, str] = {
    "read": READ, "open": READ, "cat": READ,
    "list": LIST, "ls": LIST, "dir": LIST,
    "find": SEARCH, "search": SEARCH, "grep": SEARCH,
    "ask": ASK, "question": ASK,
    "show": SHOW, "present": SHOW,
    "go": GOTO, "goto": GOTO, "cd": GOTO,
    "note": NOTE, "notes": NOTE,
    "edit": EDIT_NOTE,
    "del": DELETE_NOTE, "delete": DELETE_NOTE, "rm": DELETE_NOTE,
    "title": TITLE, "act": ACT,
    "check": REVIEW, "review": REVIEW,
    "back": TIMELINE, "timeline": TIMELINE,
    "accuse": ACCUSE,
    "save": SAVE, "load": LOAD,
    "help": HELP, "quit": QUIT, "exit": QUIT, "q": QUIT,
}

#: 提审里「出示证物」的两个方向：「出示 X 给 Y」与「向 Y 出示 X」。
_TO_PREPS = ("给", "于", "向", "对")
_FROM_PREPS = ("向", "对", "找")

_ALL_VERBS: Dict[str, str] = {}
_ALL_VERBS.update(VERBS)
_ALL_VERBS.update(VERBS_EN)

#: 按长度倒序，保证「读档」先于「读」匹配。
_VERB_ORDER: List[str] = sorted(_ALL_VERBS, key=len, reverse=True)


def _split_verb(text: str) -> Tuple[str, str]:
    """切出开头的动词与余下部分。动词与参数之间可以没有空格（「阅01-FY-WDH」）。"""
    for verb in _VERB_ORDER:
        if text.startswith(verb):
            rest = text[len(verb):]
            return verb, rest.lstrip(" 　:：,，")
    return "", text


#: 「向 Y 出示 X」「对 Y 出示 X」——介词开头、人物在前。这类语序在
#: `_split_verb` 里切不出动词（「向」不是动词），所以在这里先剥介词再看。
_PREP_HEAD = ("向", "对", "找")


def _strip_prep_head(text: str) -> Optional[Tuple[str, str]]:
    """处理「向 Y 出示 X」这类介词开头、人物在前的语序。

    返回 `(动词, 余下参数)`；不是这种语序则返回 `None`。注意返回的余下参数是
    **已经被翻正**的——人物被移到参数末尾，于是调用方拿到的形状和
    「出示 X Y」完全一致，不必再分情况。
    """
    for prep in _PREP_HEAD:
        if not text.startswith(prep):
            continue
        inner = text[len(prep):].lstrip(" 　:：,，")
        if not inner:
            continue
        # 「向 王德海 出示 枕下密信」：先切出人物，再看后面跟的是不是动词
        who, tail = _split_two(inner)
        if not tail:
            continue
        verb, rest = _split_verb(tail)
        if verb:
            # 翻正成「证物 [人物]」：SHOW 的默认语序
            flipped = f"{rest} {who}".strip() if rest else who
            return verb, flipped
    return None


def parse(text: str) -> Command:
    """把一行输入解析成 `Command`；失败抛 `ParseError`。

    解析顺序：
      1. 空输入 → `ParseError`（调用方通常会忽略空行，但解析器不假设）
      2. 有动词 → 按该动词的规则解析参数
      3. 没动词但整行像档号 → 当作 `READ`
      4. 其余 → `ParseError`，附最接近的动词候选
    """
    raw = text or ""
    flat = normalize(raw)
    if not flat:
        raise ParseError("空指令")

    verb, rest = _split_verb(flat)
    if not verb:
        # 「向 王德海 出示 枕下密信」这类介词开头的语序
        flipped = _strip_prep_head(flat)
        if flipped is not None:
            verb, rest = flipped
    if verb:
        kind = _ALL_VERBS[verb]
        return _build(kind, rest, raw, verb)

    # 没动词：像档号就当阅档，这让「输入档号」成为最自然的操作
    if is_dossier_id(flat):
        return Command(kind=READ, arg=canon_dossier_id(flat), raw=raw)

    raise ParseError(
        f"看不懂「{flat}」。",
        hint="敲「帮助」看全部指令，或直接输入档号（如 01-FY-WDH）。",
        candidates=suggest_verbs(flat),
    )


def _build(kind: str, rest: str, raw: str, verb: str) -> Command:
    """按指令种类把 `rest` 拆成参数。"""
    if kind == READ:
        if not rest:
            raise ParseError("「阅」后面要跟档号。", hint="例如：阅 01-FY-WDH")
        return Command(kind=READ, arg=canon_dossier_id(rest), raw=raw)

    if kind == LIST:
        idx = _as_index(rest)
        return Command(kind=LIST, index=idx or 1, raw=raw)

    if kind == SEARCH:
        if not rest:
            raise ParseError("「查」后面要跟关键词。", hint="例如：查 王德海")
        return Command(kind=SEARCH, arg=rest, raw=raw)

    if kind == ASK:
        who, what = _split_two(rest)
        if not who:
            raise ParseError("「问」后面要跟人名。", hint="例如：问 王德海 采薇")
        return Command(kind=ASK, who=who, what=what, raw=raw)

    if kind == SHOW:
        item, who = _split_show(rest)
        if not item:
            raise ParseError("「出示」后面要跟证物名。", hint="例如：出示 枕下密信 王德海")
        return Command(kind=SHOW, arg=item, who=who, raw=raw)

    if kind == GOTO:
        if not rest:
            raise ParseError("「前往」后面要跟地点。", hint="例如：前往 尚药局")
        return Command(kind=GOTO, arg=rest, raw=raw)

    if kind == NOTE:
        if not rest:
            raise ParseError("「记」后面要跟内容。", hint="例如：记 香炉里有红色粉末")
        return Command(kind=NOTE, arg=rest, raw=raw)

    if kind in (EDIT_NOTE, DELETE_NOTE):
        idx = _as_index(rest)
        if idx is None:
            # 「改 <文字>」= 改写最后一条；「改 2 <文字>」= 改写第 2 条
            if kind == EDIT_NOTE and rest:
                return Command(kind=EDIT_NOTE, arg=rest, index=-1, raw=raw)
            raise ParseError(
                "「{}」后面要跟条目号。".format("改" if kind == EDIT_NOTE else "删"),
                hint="例如：{} 2".format("改" if kind == EDIT_NOTE else "删"),
            )
        body = ""
        if kind == EDIT_NOTE:
            _, tail = _strip_leading_number(rest)
            _, body = _split_two(tail)
        return Command(kind=kind, index=idx, arg=body, raw=raw)

    if kind == TITLE:
        code, title = _split_two(rest)
        if not code:
            raise ParseError("「目」后面要跟时辰码。", hint="例如：目 01 夜半验尸")
        return Command(kind=TITLE, arg=canon_dossier_id(code) if is_dossier_id(code) else code,
                       what=title, raw=raw)

    if kind == ACT:
        idx = _as_index(rest)
        if idx is None:
            raise ParseError("「幕」后面要跟幕号。", hint="例如：幕 2 三处查证")
        return Command(kind=ACT, index=idx, what=_strip_leading_number(rest)[1], raw=raw)

    if kind == ACCUSE:
        if not rest:
            raise ParseError("「指认」后面要跟人名。", hint="例如：指认 王德海")
        return Command(kind=ACCUSE, who=rest, raw=raw)

    if kind in (SAVE, LOAD, HELP, QUIT, REVIEW, TIMELINE):
        return Command(kind=kind, raw=raw)

    raise ParseError(f"指令「{verb}」还没有实现。")


def _strip_leading_number(text: str) -> str:
    """去掉开头的数字，返回（数字文本, 其余）。"""
    i = 0
    while i < len(text) and text[i].isdigit():
        i += 1
    return text[:i], text[i:].lstrip(" 　:：,，.、")


def _as_index(text: str) -> Optional[int]:
    num, _ = _strip_leading_number(text.strip())
    if not num:
        return None
    try:
        return int(num)
    except ValueError:
        return None


def _split_two(text: str) -> Tuple[str, str]:
    """按第一个空白把文本切成两段。没有空白时全归第一段。"""
    t = text.strip()
    if not t:
        return "", ""
    for i, ch in enumerate(t):
        if ch in " 　":
            return t[:i], t[i:].strip()
    return t, ""


def _split_show(text: str) -> Tuple[str, str]:
    """解析出示证物的各种语序，统一返回（证物, 承受者）。

    - `出示 枕下密信 王德海`      → 空格分隔
    - `出示 枕下密信给王德海`      → 「给」分隔
    - `出示 向 王德海 出示 枕下密信` → 语序反了：介词在前，人物在前
    - `出示 王德海 枕下密信`        → 反过来也能认：谁在前看谁的形状

    最后一条是有意的宽容：玩家记不住语序，代码替他兜住。判据是「开头那段
    像不像人名」——但这里不认识剧本，所以只做**保守**处理：只有当前面带
    介词时才交换，否则按「证物在前」解释。
    """
    t = text.strip()
    if not t:
        return "", ""

    # 「向 Y 出示 X」——介词开头，人物在前
    for prep in _FROM_PREPS:
        if t.startswith(prep):
            inner = t[len(prep):].strip()
            left, right = _split_two(inner)
            if right.startswith("出示"):
                return right[len("出示"):].strip(), left
            if "出示" in right:
                _, _, item = right.partition("出示")
                return item.strip(), left
            return right, left

    # 「A 给 B」
    for prep in _TO_PREPS:
        if prep in t:
            left, _, right = t.partition(prep)
            left, right = left.strip(), right.strip()
            if right.startswith("出示"):
                return right[len("出示"):].strip(), left
            if left.startswith("出示"):
                return right, left[len("出示"):].strip()
            return left, right

    return _split_two(t)


# --------------------------------------------------------------------------
# 纠错建议
# --------------------------------------------------------------------------


def _edit_distance(a: str, b: str, cap: int = 3) -> int:
    """带上限的编辑距离；超过 `cap` 直接返回 `cap + 1`（够用于排序）。"""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(v)
            row_min = min(row_min, v)
        if row_min > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def suggest_verbs(text: str, limit: int = 5) -> List[str]:
    """按编辑距离给出最接近的动词。"""
    t = normalize(text)
    if not t:
        return []
    head = t[:3]
    scored = []
    for verb in _ALL_VERBS:
        if not verb:
            continue
        d = _edit_distance(head, verb, cap=2)
        if d <= 2:
            scored.append((d, len(verb), verb))
    scored.sort()
    return [v for _, _, v in scored[:limit]]


def suggest_dossier_ids(text: str, known: Sequence[str], limit: int = 5) -> List[str]:
    """给出最接近的档号候选。

    先看「形状」再看「字符」：时间码或地点码错一位的档号，比随机档号更可能是
    玩家想敲的那个。所以先按「共同前缀长度」排，再按编辑距离。
    """
    want = canon_dossier_id(text)
    if not want:
        return []

    def score(did: str) -> Tuple[int, int, int]:
        shared = 0
        for a, b in zip(want, did):
            if a != b:
                break
            shared += 1
        return (-shared, _edit_distance(want, did), len(did))

    ranked = sorted(known, key=score)
    return list(ranked[:limit])


def suggest_words(text: str, known: Sequence[str], limit: int = 5) -> List[str]:
    """在给定词表里找最接近的若干项（人名、地点、证物名都用这个）。"""
    t = normalize(text)
    if not t:
        return []
    hit = [w for w in known if t in normalize(w)]
    if hit:
        return hit[:limit]
    scored = []
    for word in known:
        d = _edit_distance(t, normalize(word), cap=len(t))
        scored.append((d, len(word), word))
    scored.sort()
    return [w for d, _, w in scored[:limit] if d <= max(2, len(t) // 2)]


# --------------------------------------------------------------------------
# 帮助文本（两端共用，保证说法一致）
# --------------------------------------------------------------------------

HELP_SECTIONS: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("阅档", [
        ("阅 <档号>", "打开一份档案。也可以直接敲档号。"),
        ("档目 [页]", "列出已收集的档案，按幕分页。"),
        ("查 <词>", "在已读档案里检索。"),
    ]),
    ("查案", [
        ("问 <人> [话题]", "提审在场之人。不写话题则列出可问之事。"),
        ("出示 <物证> <人>", "把一件物证推到某人面前。"),
        ("前往 <地点>", "移步他处。"),
        ("查证", "清点证物，看还缺什么。"),
        ("复核", "把已知的时辰串成时间线。"),
    ]),
    ("笔记", [
        ("记 <文字>", "往记事簿里添一条。"),
        ("改 <号> <文字>", "改写第几条；不写号则改最后一条。"),
        ("删 <号>", "涂掉第几条。"),
        ("目 <时码> <标题>", "给某个时辰取个标题。"),
        ("幕 <号> <标题>", "给某一幕取个标题。"),
    ]),
    ("结案", [
        ("指认 <人>", "在结案陈词上写下那个名字。"),
        ("存档 / 读档", "记档与取档。"),
        ("帮助 / 退出", "看这一页；离开。"),
    ]),
]


def help_lines() -> List[str]:
    """帮助正文，纯文本，两端共用。"""
    out: List[str] = []
    for section, rows in HELP_SECTIONS:
        out.append(f"【{section}】")
        for cmd, desc in rows:
            out.append(f"  {cmd:<18}{desc}")
    return out
